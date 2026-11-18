"""Conexão com o canal e envio de vídeos pela API oficial do YouTube."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL_LOGIN = os.environ.get("CLIPADOR_GOOGLE_LOGIN", "https://accounts.google.com/o/oauth2/v2/auth")
URL_TOKEN = os.environ.get("CLIPADOR_GOOGLE_TOKEN", "https://oauth2.googleapis.com/token")
URL_API = os.environ.get("CLIPADOR_YOUTUBE_API", "https://www.googleapis.com/youtube/v3")
URL_ENVIO = os.environ.get("CLIPADOR_YOUTUBE_UPLOAD", "https://www.googleapis.com/upload/youtube/v3/videos")
ESCOPOS = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
TAMANHO_BLOCO = 8 * 1024 * 1024
TENTATIVAS = 8


class ErroYouTube(Exception):
    def __init__(self, mensagem: str, motivo: str = "", codigo: int = 0):
        super().__init__(mensagem)
        self.motivo = motivo
        self.codigo = codigo


class _SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_abridor = urllib.request.build_opener(_SemRedirecionar)


def _pedir(metodo: str, url: str, cabecalhos: dict | None = None, corpo: bytes | None = None, limite: int = 120):
    pedido = urllib.request.Request(url, data=corpo, method=metodo, headers=cabecalhos or {})
    try:
        with _abridor.open(pedido, timeout=limite) as r:
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()


def _erro_da_resposta(codigo: int, corpo: bytes) -> ErroYouTube:
    motivo, mensagem = "", ""
    try:
        erro = json.loads(corpo.decode("utf-8")).get("error", {})
        if isinstance(erro, dict):
            mensagem = erro.get("message", "")
            motivo = ((erro.get("errors") or [{}])[0]).get("reason", "") or erro.get("status", "")
        else:
            motivo = str(erro)
    except (ValueError, AttributeError):
        pass
    return ErroYouTube(mensagem or f"O YouTube respondeu com o código {codigo}.", motivo, codigo)


class ContaYouTube:
    def __init__(self, pasta: Path):
        self.arq_cliente = Path(pasta) / "youtube_cliente.json"
        self.arq_token = Path(pasta) / "youtube_token.json"
        self.trava = threading.RLock()
        self.login: dict | None = None
        self.canal: dict | None = self._ler(self.arq_token).get("canal")

    @staticmethod
    def _ler(arquivo: Path) -> dict:
        try:
            return json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _gravar(arquivo: Path, dados: dict) -> None:
        tmp = arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(dados), encoding="utf-8")
        tmp.replace(arquivo)
        try:
            os.chmod(arquivo, 0o600)
        except OSError:
            pass

    @property
    def tem_cliente(self) -> bool:
        return bool(self._ler(self.arq_cliente).get("client_id"))

    @property
    def conectada(self) -> bool:
        return bool(self._ler(self.arq_token).get("refresh_token"))

    def salvar_cliente(self, texto: str) -> None:
        try:
            dados = json.loads(texto)
        except ValueError:
            raise ValueError("Esse arquivo não é a credencial baixada do Google Cloud.") from None
        if "web" in dados:
            raise ValueError("Crie a credencial do tipo App para computador, não Aplicativo da Web.")
        cliente = dados.get("installed") or {}
        if not cliente.get("client_id") or not cliente.get("client_secret"):
            raise ValueError("Esse arquivo não é a credencial baixada do Google Cloud.")
        self._gravar(self.arq_cliente, {"client_id": cliente["client_id"], "client_secret": cliente["client_secret"]})

    def iniciar_login(self, retorno: str) -> str:
        cliente = self._ler(self.arq_cliente)
        if not cliente.get("client_id"):
            raise ValueError("Envie primeiro o arquivo de credencial do Google Cloud.")
        verificador = secrets.token_urlsafe(64)
        desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
        estado = secrets.token_urlsafe(24)
        self.login = {"estado": estado, "verificador": verificador, "retorno": retorno, "criado": time.time()}
        return URL_LOGIN + "?" + urllib.parse.urlencode({
            "client_id": cliente["client_id"], "redirect_uri": retorno, "response_type": "code", "scope": ESCOPOS,
            "access_type": "offline", "prompt": "consent", "state": estado,
            "code_challenge": desafio, "code_challenge_method": "S256",
        })

    def concluir_login(self, codigo: str, estado: str) -> None:
        login = self.login
        if not login or not secrets.compare_digest(login["estado"], estado or "") or time.time() - login["criado"] > 900:
            raise ValueError("A conexão expirou. Clique em Conectar canal de novo.")
        self.login = None
        cliente = self._ler(self.arq_cliente)
        resposta = self._token({
            "code": codigo, "client_id": cliente["client_id"], "client_secret": cliente["client_secret"],
            "redirect_uri": login["retorno"], "grant_type": "authorization_code", "code_verifier": login["verificador"],
        })
        if not resposta.get("refresh_token"):
            raise ValueError("O Google não liberou o acesso contínuo. Remova o acesso do app na sua conta e conecte de novo.")
        self._guardar_token(resposta, resposta["refresh_token"])
        self.buscar_canal()

    def desconectar(self) -> None:
        self.arq_token.unlink(missing_ok=True)
        self.canal = None

    @staticmethod
    def _token(campos: dict) -> dict:
        codigo, _, corpo = _pedir(
            "POST", URL_TOKEN, {"Content-Type": "application/x-www-form-urlencoded"},
            urllib.parse.urlencode(campos).encode(), 30,
        )
        if codigo != 200:
            raise _erro_da_resposta(codigo, corpo)
        return json.loads(corpo)

    def _guardar_token(self, resposta: dict, refresh: str) -> None:
        self._gravar(self.arq_token, {
            "access_token": resposta["access_token"], "refresh_token": refresh,
            "expira": time.time() + int(resposta.get("expires_in", 3600)), "canal": self.canal,
        })

    def acesso(self) -> str:
        with self.trava:
            token = self._ler(self.arq_token)
            if not token.get("refresh_token"):
                raise ErroYouTube("Conecte o canal do YouTube.", "semConta")
            if token.get("expira", 0) > time.time() + 90:
                return token["access_token"]
            cliente = self._ler(self.arq_cliente)
            try:
                nova = self._token({
                    "client_id": cliente.get("client_id", ""), "client_secret": cliente.get("client_secret", ""),
                    "refresh_token": token["refresh_token"], "grant_type": "refresh_token",
                })
            except ErroYouTube as e:
                if e.motivo in ("invalid_grant", "invalid_client", "unauthorized_client"):
                    self.desconectar()
                    raise ErroYouTube("O acesso ao canal expirou. Conecte o canal de novo.", "semConta") from None
                raise
            self._guardar_token(nova, nova.get("refresh_token") or token["refresh_token"])
            return nova["access_token"]

    def buscar_canal(self) -> dict | None:
        codigo, _, corpo = _pedir(
            "GET", f"{URL_API}/channels?part=snippet&mine=true", {"Authorization": f"Bearer {self.acesso()}"}, None, 30,
        )
        if codigo != 200:
            raise _erro_da_resposta(codigo, corpo)
        itens = json.loads(corpo).get("items") or []
        if not itens:
            raise ValueError("Esta conta Google ainda não tem um canal no YouTube.")
        self.canal = {"id": itens[0]["id"], "nome": itens[0]["snippet"]["title"]}
        token = self._ler(self.arq_token)
        token["canal"] = self.canal
        self._gravar(self.arq_token, token)
        return self.canal

    def _consultar_api(self, caminho: str) -> dict:
        codigo, _, corpo = _pedir("GET", f"{URL_API}/{caminho}", {"Authorization": f"Bearer {self.acesso()}"}, None, 30)
        if codigo != 200:
            raise _erro_da_resposta(codigo, corpo)
        return json.loads(corpo)

    def videos_do_canal(self, limite: int = 500) -> list[dict]:
        """Vídeos enviados ao canal conectado, inclusive os privados e programados."""
        itens = self._consultar_api("channels?part=contentDetails&mine=true").get("items") or []
        lista = ((itens[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") if itens else None
        if not lista:
            return []
        videos: list[dict] = []
        pagina = ""
        while len(videos) < limite:
            consulta = {"part": "snippet", "maxResults": "50", "playlistId": lista}
            if pagina:
                consulta["pageToken"] = pagina
            try:
                dados = self._consultar_api("playlistItems?" + urllib.parse.urlencode(consulta))
            except ErroYouTube as e:
                if e.codigo == 404:
                    return videos
                raise
            for item in dados.get("items") or []:
                trecho = item.get("snippet") or {}
                video = (trecho.get("resourceId") or {}).get("videoId")
                if video:
                    videos.append({"id": video, "titulo": trecho.get("title") or "", "publicado": _segundos(trecho.get("publishedAt")), "publicar_em": 0.0})
            pagina = dados.get("nextPageToken") or ""
            if not pagina:
                break
        for i in range(0, len(videos), 50):
            lote = videos[i:i + 50]
            dados = self._consultar_api("videos?" + urllib.parse.urlencode({"part": "status", "id": ",".join(v["id"] for v in lote)}))
            situacao = {v.get("id"): v.get("status") or {} for v in dados.get("items") or []}
            for v in lote:
                v["publicar_em"] = _segundos(situacao.get(v["id"], {}).get("publishAt"))
        return videos

    def enviar(self, arquivo: Path, titulo: str, descricao: str, tags: list[str], publicar_em: float | None,
               progresso=lambda fracao: None) -> str:
        """Envia em partes, retoma quedas de conexão e devolve o ID do vídeo."""
        tamanho = arquivo.stat().st_size
        status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False, "embeddable": True}
        if publicar_em:
            status["publishAt"] = datetime.fromtimestamp(publicar_em, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        corpo = json.dumps({
            "snippet": {"title": titulo, "description": descricao, "tags": tags, "categoryId": "20",
                        "defaultLanguage": "pt-BR", "defaultAudioLanguage": "pt-BR"},
            "status": status,
        }, ensure_ascii=False).encode("utf-8")
        codigo, cabecalhos, resposta = _pedir(
            "POST", f"{URL_ENVIO}?uploadType=resumable&part=snippet,status",
            {"Authorization": f"Bearer {self.acesso()}", "Content-Type": "application/json; charset=UTF-8",
             "X-Upload-Content-Length": str(tamanho), "X-Upload-Content-Type": "video/mp4"},
            corpo, 60,
        )
        if codigo not in (200, 201):
            raise _erro_da_resposta(codigo, resposta)
        sessao = {k.lower(): v for k, v in cabecalhos.items()}.get("location")
        if not sessao:
            raise ErroYouTube("O YouTube não abriu o envio.", "semSessao")

        enviado, falhas = 0, 0
        with open(arquivo, "rb") as f:
            while True:
                f.seek(enviado)
                bloco = f.read(TAMANHO_BLOCO)
                fim = enviado + len(bloco) - 1
                try:
                    codigo, cabecalhos, resposta = _pedir(
                        "PUT", sessao,
                        {"Authorization": f"Bearer {self.acesso()}", "Content-Type": "video/mp4",
                         "Content-Range": f"bytes {enviado}-{fim}/{tamanho}"},
                        bloco, 300,
                    )
                except OSError:
                    codigo, cabecalhos, resposta = 0, {}, b""
                if codigo in (200, 201):
                    progresso(1.0)
                    return json.loads(resposta)["id"]
                if codigo == 308:
                    enviado, falhas = _proximo_byte(cabecalhos), 0
                    progresso(enviado / tamanho)
                    continue
                if codigo and codigo < 500 and codigo != 429:
                    raise _erro_da_resposta(codigo, resposta)
                falhas += 1
                if falhas > TENTATIVAS:
                    raise ErroYouTube("A conexão com o YouTube caiu várias vezes.", "conexao", codigo)
                time.sleep(min(2 ** falhas, 60) * float(os.environ.get("CLIPADOR_ESPERA_ENVIO", "1")))
                enviado = self._consultar(sessao, tamanho, enviado)

    def _consultar(self, sessao: str, tamanho: int, atual: int) -> int:
        try:
            codigo, cabecalhos, _ = _pedir(
                "PUT", sessao, {"Authorization": f"Bearer {self.acesso()}", "Content-Range": f"bytes */{tamanho}"}, b"", 60,
            )
        except OSError:
            return atual
        return _proximo_byte(cabecalhos) if codigo == 308 else atual


def _segundos(texto: str | None) -> float:
    try:
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _proximo_byte(cabecalhos: dict) -> int:
    faixa = {k.lower(): v for k, v in cabecalhos.items()}.get("range", "")
    return int(faixa.rsplit("-", 1)[1]) + 1 if "-" in faixa else 0
