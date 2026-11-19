"""Procura os melhores momentos em lives que já terminaram."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from . import camera as cam
from .deteccao import mensagens_marcantes
from .longo import DURACOES
from .momentos import PontuadorMomento, medir_pcm
from .plataformas import sem_janela
from .sentidos import ALTURA, LARGURA, Sentidos

JANELA = 10
ESPACO_MINIMO = 60
QUANTIDADES = (5, 10, 20, 30, 50)
QUALIDADES = (720, 1080)
TWITCH_GQL = "https://gql.twitch.tv/gql"
TWITCH_CLIENTE = "kimne78kx3ncx6brgo4mv6wki5h1ko"
TWITCH_CONSULTA = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"
ETAPAS_FINAIS = ("pronto", "erro", "cancelada")
FORMATOS_VIDEO = (".mp4", ".mov", ".mkv", ".webm", ".ts", ".m4v", ".avi", ".flv")
LIMITE_VIDEO = 100 * 1024 ** 3
FOLGA_DISCO = 2 * 1024 ** 3
MINIMO_ENVIO = 30
MINIMO_LINK = 120


class Cancelada(Exception):
    pass


# ------------------------------------------------------------ replay do chat

def ler_chat_youtube(arquivo: Path) -> list[tuple[float, str]]:
    """Lê o arquivo live_chat que o YouTube guarda junto da gravação."""
    mensagens = []
    with open(arquivo, encoding="utf-8", errors="replace") as f:
        for linha in f:
            try:
                dados = json.loads(linha)
            except ValueError:
                continue
            replay = dados.get("replayChatItemAction") or {}
            try:
                tempo = int(replay.get("videoOffsetTimeMsec", -1)) / 1000
            except (TypeError, ValueError):
                continue
            if tempo < 0:
                continue
            for acao in replay.get("actions") or []:
                item = ((acao.get("addChatItemAction") or {}).get("item") or {})
                render = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer") or {}
                partes = (render.get("message") or {}).get("runs") or []
                texto = "".join(p.get("text") or (p.get("emoji") or {}).get("shortcuts", [""])[0] for p in partes).strip()
                if texto:
                    mensagens.append((tempo, texto))
    return mensagens


def ler_comentarios_twitch(resposta: list | dict) -> list[tuple[float, str]]:
    bloco = resposta[0] if isinstance(resposta, list) and resposta else resposta
    bordas = (((bloco or {}).get("data") or {}).get("video") or {}).get("comments", {}) or {}
    saida = []
    for borda in bordas.get("edges") or []:
        no = borda.get("node") or {}
        texto = "".join((f.get("text") or "") for f in ((no.get("message") or {}).get("fragments") or [])).strip()
        if texto:
            saida.append((float(no.get("contentOffsetSeconds") or 0), texto))
    return saida


def baixar_chat_twitch(video: str, duracao: float, parar: threading.Event, avisar=lambda f: None) -> list[tuple[float, str]]:
    from curl_cffi import requests

    mensagens: list[tuple[float, str]] = []
    posicao = 0.0
    vazios = 0
    while posicao < duracao and vazios < 12 and not parar.is_set():
        corpo = [{"operationName": "VideoCommentsByOffsetOrCursor", "variables": {"videoID": video, "contentOffsetSeconds": int(posicao)},
                  "extensions": {"persistedQuery": {"version": 1, "sha256Hash": TWITCH_CONSULTA}}}]
        r = requests.post(TWITCH_GQL, json=corpo, headers={"Client-ID": TWITCH_CLIENTE}, impersonate="chrome", timeout=25)
        if r.status_code != 200:
            break
        lote = ler_comentarios_twitch(r.json())
        if not lote:
            vazios += 1
            posicao += 30
            continue
        vazios = 0
        mensagens += [m for m in lote if m[0] >= posicao]
        posicao = max(posicao + 1, lote[-1][0] + 0.5)
        avisar(min(1.0, posicao / max(duracao, 1)))
    return mensagens


def baixar_chat_kick(video: str, duracao: float, parar: threading.Event, avisar=lambda f: None) -> list[tuple[float, str]]:
    from curl_cffi import requests

    r = requests.get(f"https://kick.com/api/v1/video/{video}", impersonate="chrome", timeout=25)
    if r.status_code != 200:
        return []
    dados = r.json().get("livestream") or {}
    canal = dados.get("channel") or {}
    sala = (canal.get("chatroom") or {}).get("id") or canal.get("id")
    inicio = dados.get("start_time") or dados.get("created_at")
    if not sala or not inicio:
        return []
    base = datetime.fromisoformat(str(inicio).replace(" ", "T").replace("Z", "+00:00"))
    base = base if base.tzinfo else base.replace(tzinfo=timezone.utc)
    mensagens: list[tuple[float, str]] = []
    falhas = 0
    for segundo in range(0, int(duracao), JANELA):
        if parar.is_set() or falhas >= 8:
            break
        momento = (base + timedelta(seconds=segundo)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        r = requests.get(f"https://kick.com/api/v2/channels/{sala}/messages", params={"start_time": momento}, impersonate="chrome", timeout=25)
        if r.status_code != 200:
            falhas += 1
            continue
        falhas = 0
        for m in ((r.json().get("data") or {}).get("messages") or []):
            texto = re.sub(r"\[emote:\d+:([^\]]+)\]", r"\1", str(m.get("content") or "")).strip()
            if texto:
                mensagens.append((float(segundo), texto))
        avisar(segundo / max(duracao, 1))
    return mensagens


def agrupar_chat(mensagens: list[tuple[float, str]]) -> dict[int, list[str]]:
    janelas: dict[int, list[str]] = defaultdict(list)
    for tempo, texto in mensagens:
        janelas[int(tempo // JANELA)].append(texto)
    return janelas


# ------------------------------------------------------------ análise da gravação inteira

def analisar_video(video: Path, duracao: float, chat: dict[int, list[str]], parar: threading.Event,
                   avisar=lambda fracao: None, ajuste=None) -> list[dict]:
    """Lê a gravação em blocos de 10 segundos com os mesmos critérios usados nas lives."""
    pontuador = PontuadorMomento("media")
    sentidos = Sentidos(lambda pcm: None, lambda: ajuste or {"modo": "auto", "rect": None})
    audio = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **sem_janela())
    imagem = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-skip_frame", "nokey", "-i", str(video), "-an", "-vf",
         f"fps=1,scale={LARGURA}:{ALTURA}:flags=fast_bilinear", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **sem_janela(),
    )
    tamanho_audio, tamanho_quadro = 16000 * 2 * JANELA, LARGURA * ALTURA * 3
    notas: list[dict] = []
    total = max(1, int(duracao // JANELA))
    try:
        for n in range(total + 1):
            if parar.is_set():
                raise Cancelada()
            bruto = audio.stdout.read(tamanho_audio)
            if len(bruto) < 16000:
                break
            pcm = np.frombuffer(bruto[: len(bruto) // 2 * 2], dtype=np.int16)
            dados = imagem.stdout.read(tamanho_quadro * JANELA)
            quadros = len(dados) // tamanho_quadro
            visao = None
            if quadros >= 4:
                try:
                    visao = sentidos.ver_quadros(np.frombuffer(dados, np.uint8, quadros * tamanho_quadro).reshape(quadros, ALTURA, LARGURA, 3))
                except (cv2.error, ValueError):
                    visao = None
            textos = chat.get(n, [])
            nota = pontuador.avaliar(len(textos), textos, {"audio": medir_pcm(pcm), "visao": visao, "fala": None})
            notas.append({"pos": (n + 1) * JANELA, "msgs": len(textos), "textos": textos[:200], **nota})
            avisar(min(1.0, n / total))
    finally:
        for proc in (audio, imagem):
            proc.stdout.close()
            proc.kill()
            proc.wait()
        sentidos.encerrar()
    return notas


def escolher_momentos(notas: list[dict], quantos: int, espaco: float = ESPACO_MINIMO) -> list[dict]:
    """Os momentos mais fortes da live, sem dois cortes em cima do mesmo acontecimento."""
    def forca(n: dict) -> float:
        return n["nota"] + (n["chat"] + n["streamer"] + n["jogo"]) / 300

    escolhidos: list[dict] = []
    for n in sorted(notas, key=forca, reverse=True):
        if forca(n) <= 0:
            break
        if all(abs(n["pos"] - e["pos"]) >= espaco for e in escolhidos):
            escolhidos.append(n)
        if len(escolhidos) >= quantos:
            break
    return sorted(escolhidos, key=lambda n: n["pos"])


# ------------------------------------------------------------ fila de gravações

class Gravadas:
    def __init__(self, motor):
        self.motor = motor
        self.pasta = Path(motor.dados) / "gravadas"
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = self.pasta / "lista.json"
        self.itens: dict[str, dict] = {i["id"]: i for i in motor._ler(self.arquivo, [])}
        self.paradas: dict[str, threading.Event] = {}
        self.trava = threading.RLock()
        self.vez = threading.Lock()
        self.envios = self.pasta / "envios"
        self.envios.mkdir(parents=True, exist_ok=True)
        self.recebidos: dict[str, dict] = {}
        self._continuar: list[dict] = []
        em_uso = set()
        for item in self.itens.values():
            if item["status"] not in ETAPAS_FINAIS:
                if item.get("envio") and not Path(item["link"]).is_file():
                    item.update(status="erro", etapa="Interrompida", erro="O programa foi fechado antes de o vídeo terminar de chegar. Envie o vídeo de novo.")
                    continue
                item.update(status="fila", etapa="Continuando de onde parou")  # a pasta com o que já foi baixado fica guardada
                em_uso.add(Path(item["link"]).name)
                self._continuar.append(item)
        for sobra in self.envios.iterdir():  # sobras de envios que não chegaram ao fim
            if sobra.name not in em_uso:
                sobra.unlink(missing_ok=True) if sobra.is_file() else shutil.rmtree(sobra, ignore_errors=True)

    def _salvar(self) -> None:
        with self.trava:
            self.motor._gravar(self.arquivo, list(self.itens.values()))

    def retomar(self) -> None:
        for item in self._continuar:
            self.paradas[item["id"]] = threading.Event()
            threading.Thread(target=self._rodar, args=(item,), daemon=True).start()
        if self._continuar:
            self._salvar()
            self.motor.evento("Gravações", "info", f"Continuando {len(self._continuar)} {'gravação' if len(self._continuar) == 1 else 'gravações'} de onde parou")
        self._continuar = []

    def resumo(self) -> list[dict]:
        with self.trava:
            return sorted((dict(i) for i in self.itens.values()), key=lambda i: i["criado"], reverse=True)

    def conferir_envio(self, nome: str, tamanho: int) -> dict:
        """Avisa antes de começar se o arquivo não vai caber ou não pode ser usado."""
        if Path(str(nome)).suffix.lower() not in FORMATOS_VIDEO:
            raise ValueError("Use um vídeo MP4, MOV, MKV, WEBM, TS, M4V, AVI ou FLV.")
        tamanho = int(tamanho)
        if tamanho <= 0:
            raise ValueError("Este arquivo está vazio.")
        if tamanho > LIMITE_VIDEO:
            raise ValueError("O vídeo precisa ter no máximo 100 GB.")
        livre = shutil.disk_usage(self.envios).free
        if livre < tamanho + FOLGA_DISCO:
            faltam = (tamanho + FOLGA_DISCO - livre) / 1024 ** 3
            raise ValueError(f"Falta espaço no computador. Libere pelo menos {faltam:.1f} GB e tente de novo.")
        return {"ok": True}

    def receber_envio(self, nome: str, corpo, tamanho: int) -> dict:
        self.conferir_envio(nome, tamanho)
        nome = Path(str(nome).replace("\\", "/")).name[:160]
        token = uuid.uuid4().hex
        destino = self.envios / f"{token}{Path(nome).suffix.lower()}"
        try:
            restante = tamanho
            with open(destino, "wb") as f:
                while restante > 0:
                    bloco = corpo.read(min(restante, 4 * 1024 * 1024))
                    if not bloco:
                        raise ValueError("O envio foi interrompido. Tente de novo.")
                    f.write(bloco)
                    restante -= len(bloco)
            try:
                duracao = cam.dimensoes(destino)[2]
            except (IndexError, ValueError, OSError):
                duracao = 0
            if not duracao:
                raise ValueError("Não consegui ler este vídeo. Confira se o arquivo está completo.")
            if duracao < MINIMO_ENVIO:
                raise ValueError(f"O vídeo precisa ter pelo menos {MINIMO_ENVIO} segundos.")
        except BaseException:
            destino.unlink(missing_ok=True)
            raise
        with self.trava:
            self.recebidos[token] = {"caminho": str(destino), "nome": nome}
        return {"envio": token, "nome": nome, "duracao": round(duracao)}

    def adicionar(self, dados: dict) -> dict:
        envio = self.recebidos.get(str(dados.get("envio") or ""))
        if dados.get("envio") and not envio:
            raise ValueError("Envie o vídeo de novo.")
        link = envio["caminho"] if envio else str(dados.get("link") or "").strip().strip('"')
        if not link:
            raise ValueError("Escolha um vídeo ou cole o link da gravação.")
        quantos, qualidade = int(dados.get("momentos", 20)), int(dados.get("qualidade", 1080))
        minutos = int(dados.get("minutos", 10))
        if quantos not in QUANTIDADES or qualidade not in QUALIDADES or minutos not in DURACOES:
            raise ValueError("Confira as opções escolhidas.")
        if not Path(link).is_file() and not re.match(r"https?://", link, re.I):
            raise ValueError("Use o link da gravação ou o caminho de um arquivo de vídeo neste computador.")
        with self.trava:
            base = datetime.now().strftime("%Y%m%d%H%M%S")
            item_id, n = base, 2
            while item_id in self.itens:
                item_id, n = f"{base}{n}", n + 1
            item = {"id": item_id, "link": link, "status": "fila", "etapa": "Na fila", "progresso": 0, "erro": None, "criado": time.time(),
                    "envio": bool(envio), "titulo": Path(envio["nome"]).stem if envio else Path(link).stem if Path(link).is_file() else link, "canal": "", "momentos": quantos, "qualidade": qualidade,
                    "criar_longo": bool(dados.get("longo", True)), "programar": bool(dados.get("programar", False)), "minutos": minutos, "chat": None, "mensagens": 0, "achados": 0, "feitos": 0, "duracao": 0}
            self.itens[item_id] = item
            self.paradas[item_id] = threading.Event()
            if envio:
                del self.recebidos[str(dados["envio"])]
        self._salvar()
        threading.Thread(target=self._rodar, args=(item,), daemon=True).start()
        return {"id": item_id}

    def cancelar(self, item_id: str) -> None:
        item = self.itens[item_id]
        if item["status"] in ETAPAS_FINAIS:
            raise ValueError("Esta análise já terminou.")
        self.paradas[item_id].set()

    def remover(self, item_id: str) -> None:
        with self.trava:
            if self.itens[item_id]["status"] not in ETAPAS_FINAIS:
                raise ValueError("Cancele a análise antes de remover.")
            del self.itens[item_id]
        shutil.rmtree(self.pasta / item_id, ignore_errors=True)
        self._salvar()

    def _etapa(self, item: dict, status: str, etapa: str, progresso: int = 0) -> None:
        item.update(status=status, etapa=etapa, progresso=progresso)
        self._salvar()

    def _rodar(self, item: dict) -> None:
        parar = self.paradas[item["id"]]
        pasta = self.pasta / item["id"]
        with self.vez:  # uma gravação por vez para não pesar nas lives
            try:
                pasta.mkdir(parents=True, exist_ok=True)
                self._processar(item, pasta, parar)
                self._etapa(item, "pronto", "Pronto", 100)
            except Cancelada:
                self._etapa(item, "cancelada", "Cancelada", item.get("progresso", 0))
            except Exception as e:
                if parar.is_set():
                    self._etapa(item, "cancelada", "Cancelada", item.get("progresso", 0))
                    return
                item.update(status="erro", etapa="Com problema", erro=_mensagem_erro(e))
                self._salvar()
                self.motor.evento(item.get("canal") or "Gravação", "erro", "Uma live gravada não pôde ser analisada")
            finally:
                shutil.rmtree(pasta, ignore_errors=True)
                if item.get("envio"):  # os cortes já têm cópia própria, o original enviado não fica ocupando espaço
                    Path(item["link"]).unlink(missing_ok=True)

    def _processar(self, item: dict, pasta: Path, parar: threading.Event) -> None:
        origem = Path(item["link"])
        local = origem.is_file()
        info: dict = {}
        if local:
            video = origem
            nome = (item["titulo"] if item.get("envio") else origem.stem)[:60]
            item.update(canal=nome, plataforma="arquivo", nome_plataforma="Arquivo", credito=nome)
        else:
            self._etapa(item, "lendo", "Lendo a gravação")
            info = self._informacoes(item)
            self._etapa(item, "baixando", "Baixando a gravação")
            video = self._baixar(item, pasta, parar)
        duracao = cam.dimensoes(video)[2] or float(info.get("duration") or 0)
        if duracao < (MINIMO_ENVIO if item.get("envio") else MINIMO_LINK):
            raise ValueError(f"O vídeo precisa ter pelo menos {MINIMO_ENVIO} segundos." if item.get("envio") else "A gravação precisa ter pelo menos 2 minutos.")
        item["duracao"] = round(duracao)
        momentos = item.get("pontos")  # se o programa fechou depois da análise, não precisa analisar de novo
        if not momentos:
            self._etapa(item, "chat", "Lendo o chat da live")
            mensagens = self._chat(item, info, origem if local else None, pasta, duracao, parar)
            item.update(mensagens=len(mensagens), chat=bool(mensagens))
            self._etapa(item, "analisando", "Procurando os melhores momentos")
            notas = analisar_video(video, duracao, agrupar_chat(mensagens), parar, lambda f: item.__setitem__("progresso", round(f * 100)))
            espaco = max(20.0, min(ESPACO_MINIMO, duracao / (item["momentos"] + 1))) if item.get("envio") else ESPACO_MINIMO
            momentos = escolher_momentos(notas, item["momentos"], espaco)
            if not momentos:
                raise ValueError("Não encontrei momentos com som ou movimento nesta gravação.")
            item["pontos"] = momentos
        item["achados"] = len(momentos)
        self._etapa(item, "cortando", f"Cortando {len(momentos)} momentos")
        ids = [i for i in item.get("ids") or [] if i in self.motor.cortes]
        for n, momento in enumerate(momentos, 1):
            if n <= len(item.get("ids") or []):
                continue  # este momento já virou corte antes de o programa fechar
            if parar.is_set():
                raise Cancelada()
            while self.motor.fila.qsize() >= 2 and not parar.is_set():
                time.sleep(1)  # os cortes da live ao vivo têm prioridade
            ids.append(self.motor.corte_gravado(item, video, duracao, momento))
            item["ids"] = list(ids)
            item["progresso"] = round(n / len(momentos) * 50)
            self._salvar()
        while any(self.motor.cortes.get(i, {}).get("status") not in ("pronto", "erro", None) for i in ids):
            if parar.is_set():
                raise Cancelada()
            prontos = sum(1 for i in ids if self.motor.cortes.get(i, {}).get("status") in ("pronto", "erro"))
            item.update(feitos=prontos, progresso=50 + round(prontos / len(ids) * 50))
            time.sleep(1)
        item["feitos"] = sum(1 for i in ids if self.motor.cortes.get(i, {}).get("status") == "pronto")
        if item["criar_longo"] and item["feitos"] >= 3:
            self.motor.longos.criar(f"gravada-{item['id']}", item["minutos"])

    def _informacoes(self, item: dict) -> dict:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(item["link"], download=False)
        if info.get("live_status") == "is_live":
            raise ValueError("Esta live ainda está no ar. Use a aba Ao vivo para acompanhar.")
        extrator = str(info.get("extractor_key") or info.get("extractor") or "").lower()
        plataforma = next((p for p in ("youtube", "twitch", "kick", "twitter") if p in extrator), "video")
        nomes = {"youtube": "YouTube", "twitch": "Twitch", "kick": "Kick", "twitter": "X", "video": "Vídeo"}
        canal = info.get("uploader") or info.get("channel") or info.get("uploader_id") or "Live gravada"
        item.update(titulo=info.get("title") or item["titulo"], canal=canal, plataforma="x" if plataforma == "twitter" else plataforma,
                    nome_plataforma=nomes[plataforma], credito=f"{nomes[plataforma]}: {canal}", ident=info.get("id") or item["id"])
        return info

    def _baixar(self, item: dict, pasta: Path, parar: threading.Event) -> Path:
        import yt_dlp

        def gancho(d: dict) -> None:
            if parar.is_set():
                raise Cancelada()
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if total:
                    item["progresso"] = min(99, round(d.get("downloaded_bytes", 0) / total * 100))

        altura = item["qualidade"]
        opcoes = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "progress_hooks": [gancho],
                  "format": f"bv*[height<={altura}]+ba/b[height<={altura}]/bv*+ba/b", "merge_output_format": "mp4",
                  "outtmpl": str(pasta / "video.%(ext)s"), "retries": 10, "fragment_retries": 10, "concurrent_fragment_downloads": 4}
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            ydl.download([item["link"]])
        videos = [p for p in pasta.glob("video.*") if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".ts", ".mov")]
        if not videos:
            raise RuntimeError("download sem arquivo")
        return max(videos, key=lambda p: p.stat().st_size)

    def _chat(self, item: dict, info: dict, local: Path | None, pasta: Path, duracao: float, parar: threading.Event) -> list[tuple[float, str]]:
        avisar = lambda f: item.__setitem__("progresso", round(f * 100))
        try:
            if local is not None:
                vizinho = local.with_suffix(".live_chat.json")
                return ler_chat_youtube(vizinho) if vizinho.exists() else []
            plataforma = item.get("plataforma")
            if plataforma == "youtube":
                import yt_dlp

                opcoes = {"quiet": True, "no_warnings": True, "skip_download": True, "writesubtitles": True, "subtitleslangs": ["live_chat"],
                          "outtmpl": str(pasta / "chat.%(ext)s"), "noplaylist": True}
                with yt_dlp.YoutubeDL(opcoes) as ydl:
                    ydl.download([item["link"]])
                arquivo = next(iter(pasta.glob("chat*.json")), None)
                return ler_chat_youtube(arquivo) if arquivo else []
            if plataforma == "twitch":
                return baixar_chat_twitch(str(info.get("id") or "").lstrip("v"), duracao, parar, avisar)
            if plataforma == "kick":
                return baixar_chat_kick(str(info.get("id") or ""), duracao, parar, avisar)
        except Cancelada:
            raise
        except Exception:
            return []  # sem replay do chat, a análise segue pela voz, pelo rosto e pelo jogo
        return []


def _mensagem_erro(erro: Exception) -> str:
    texto = re.sub(r"\x1b\[[0-9;]*m", "", str(erro)).replace("ERROR: ", "").strip()
    if re.search(r"private|members|sign in|login|age", texto, re.I):
        return "Esta gravação é privada ou exige login. Use uma gravação pública."
    if re.search(r"unsupported url|no video|404", texto, re.I):
        return "Não encontrei uma gravação neste link. Confira se ela ainda está disponível."
    return texto[:280] or "Não foi possível analisar esta gravação."
