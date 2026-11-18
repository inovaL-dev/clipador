"""Reconhece os links e descobre se cada canal está ao vivo."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

KICK_API = os.environ.get("CLIPADOR_KICK_API", "https://kick.com/api/v2/channels")


def cmd_streamlink() -> list[str]:
    exe = shutil.which("streamlink")
    return [exe] if exe else [sys.executable, "-m", "streamlink_cli"]


def sem_janela() -> dict:
    """Evita abrir janelas de console no Windows."""
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


@dataclass
class Live:
    fonte: str
    titulo: str = ""
    chat: dict = field(default_factory=dict)


class Canal:
    plataforma = ""
    nome_plataforma = ""

    def __init__(self, ident: str, link: str):
        self.ident = ident
        self.link = link
        self.id = re.sub(r"[^\w-]", "_", f"{self.plataforma}-{ident}")
        self.nome = ident
        self.credito = ident
        self.encerra_ao_acabar = False
        self.motivo = ""

    def verificar(self) -> Live | None:
        raise NotImplementedError


class CanalKick(Canal):
    plataforma = "kick"
    nome_plataforma = "Kick"

    def __init__(self, ident, link):
        super().__init__(ident, link)
        self.credito = f"kick.com/{ident}"

    def verificar(self):
        from curl_cffi import requests

        r = requests.get(f"{KICK_API}/{self.ident}", impersonate="chrome", timeout=20)
        if r.status_code == 404:
            raise ValueError("canal não encontrado no Kick")
        if r.status_code != 200:
            raise RuntimeError(f"o Kick respondeu com o código {r.status_code}")
        dados = r.json()
        self.nome = (dados.get("user") or {}).get("username") or self.ident
        live = dados.get("livestream")
        if not live or not live.get("is_live", True):
            return None
        url = dados.get("playback_url")
        fonte = f"hls://{url}" if url else f"https://kick.com/{self.ident}"
        sala = (dados.get("chatroom") or {}).get("id")
        return Live(fonte, live.get("session_title") or "", {"tipo": "kick", "sala": sala})


class CanalTwitch(Canal):
    plataforma = "twitch"
    nome_plataforma = "Twitch"

    def __init__(self, ident, link):
        super().__init__(ident.lower(), link)
        self.credito = f"twitch.tv/{self.ident}"

    def verificar(self):
        url = f"https://www.twitch.tv/{self.ident}"
        r = subprocess.run(
            [*cmd_streamlink(), "--json", url], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=90, **sem_janela(),
        )
        try:
            dados = json.loads(r.stdout)
        except ValueError:
            return None
        if not (dados.get("streams") or {}).get("best"):
            return None
        meta = dados.get("metadata") or {}
        self.nome = meta.get("author") or self.ident
        return Live(url, meta.get("title") or "", {"tipo": "twitch", "sala": self.ident})


class CanalX(Canal):
    plataforma = "x"
    nome_plataforma = "X"

    def __init__(self, ident, link):
        super().__init__(ident, link)
        self.credito = "x.com"
        self.encerra_ao_acabar = True

    def verificar(self):
        import yt_dlp

        url = f"https://x.com/i/broadcasts/{self.ident}"
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "format": "best"}) as ydl:
            info = ydl.extract_info(url, download=False)
        if info.get("uploader"):
            self.nome = info["uploader"]
        if info.get("uploader_id"):
            self.credito = f"x.com/{info['uploader_id']}"
        if info.get("live_status") != "is_live" or not info.get("url"):
            return None
        return Live(f"hls://{info['url']}", info.get("title") or "", {"tipo": "x", "sala": self.ident})


class CanalYoutube(Canal):
    plataforma = "youtube"
    nome_plataforma = "YouTube"

    def __init__(self, ident, link, url, video_id=None, credito=None):
        super().__init__(ident, link)
        self.url = url
        self.video_id = video_id
        self.credito = credito or "youtube.com"
        self.encerra_ao_acabar = video_id is not None

    def verificar(self):
        self.motivo = ""
        return self._pelo_streamlink() or self._pelo_ytdlp()

    def _pelo_streamlink(self) -> Live | None:
        try:
            r = subprocess.run(
                [*cmd_streamlink(), "--json", self.url], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=90, **sem_janela(),
            )
            dados = json.loads(r.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        # Live no YouTube é sempre HLS ("hls" ou "hls-multi", com áudio separado).
        tipo = str(((dados.get("streams") or {}).get("best") or {}).get("type") or "")
        if not tipo.startswith("hls"):
            return None
        meta = dados.get("metadata") or {}
        self._identificar(meta.get("author"))
        video = meta.get("id") or self.video_id
        fonte = f"https://www.youtube.com/watch?v={meta['id']}" if meta.get("id") else self.url
        return Live(fonte, meta.get("title") or "", {"tipo": "youtube", "sala": video})

    def _pelo_ytdlp(self) -> Live | None:
        """Segunda opinião: o YouTube às vezes esconde a live de um dos dois programas."""
        import yt_dlp

        opcoes = {
            "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "format": "b*",
            "ignore_no_formats_error": True, "socket_timeout": 20, "retries": 1, "extractor_retries": 1,
        }
        try:
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                info = ydl.extract_info(self.url, download=False)
        except yt_dlp.utils.DownloadError as e:
            return self._sem_resposta(str(e))
        self._identificar(info.get("channel") or info.get("uploader"))
        situacao = info.get("live_status")
        if situacao == "is_live":
            endereco = info.get("manifest_url") or info.get("url")
            if not endereco:
                raise ValueError("O YouTube mostrou a live, mas não liberou o vídeo. Nova tentativa em instantes")
            video = info.get("id") or self.video_id
            return Live(f"hls://{endereco}", info.get("title") or "", {"tipo": "youtube", "sala": video})
        self.motivo = {
            "is_upcoming": "A live ainda não começou. A gravação inicia sozinha quando ela abrir",
            "was_live": "Esta transmissão já terminou. Para aproveitar, use Analisar uma live que já acabou",
            "post_live": "Esta transmissão acabou de terminar",
            "not_live": "Este link é de um vídeo comum, não de uma live",
        }.get(situacao, "")
        return None

    def _sem_resposta(self, erro: str) -> None:
        texto = erro.lower()
        if any(t in texto for t in ("not currently live", "will begin", "premieres in", "is not live", "no live")):
            self.motivo = "A live ainda não começou. A gravação inicia sozinha quando ela abrir"
            return None
        if any(t in texto for t in ("confirm you", "not a bot", "429", "too many requests")):
            raise ValueError("O YouTube bloqueou a consulta deste computador por um tempo. Nova tentativa em instantes")
        if any(t in texto for t in ("private", "members-only", "members only", "age", "sign in")):
            raise ValueError("O YouTube só mostra esta live para quem entra na conta, então ela não pode ser gravada")
        if any(t in texto for t in ("unavailable", "removed", "does not exist", "404")):
            raise ValueError("Esta live não existe mais ou o link está errado")
        raise ValueError("Não foi possível falar com o YouTube. Confira a internet. Nova tentativa em instantes")

    def _identificar(self, autor: str | None) -> None:
        if autor:
            self.nome = autor
            if self.credito == "youtube.com":
                self.credito = f"YouTube: {autor}"


def _criar_youtube(url: str) -> Canal | None:
    m = re.search(r"youtube\.com/(?:watch\?(?:.*&)?v=|live/|v/)([\w-]{11})", url, re.I) or re.search(
        r"youtu\.be/([\w-]{11})", url, re.I
    )
    if m:
        return CanalYoutube(m[1], url, f"https://www.youtube.com/watch?v={m[1]}", video_id=m[1])
    m = re.search(r"youtube\.com/(@[\w.%-]+|(?:channel|c|user)/[\w.%-]+)", url, re.I)
    if m:
        caminho = m[1]
        nome = caminho.rsplit("/", 1)[-1].lstrip("@")
        credito = f"youtube.com/{caminho}" if caminho.startswith("@") else None
        return CanalYoutube(nome, url, f"https://www.youtube.com/{caminho}/live", credito=credito)
    return None


def criar_canal(url: str) -> Canal:
    url = url.strip()
    if re.search(r"youtube\.com/|youtu\.be/", url, re.I):
        canal = _criar_youtube(url)
        if canal:
            return canal
        raise ValueError("No YouTube, use o link do canal (youtube.com/@canal) ou da live (youtube.com/watch?v=...).")
    if m := re.search(r"kick\.com/([\w-]+)", url, re.I):
        return CanalKick(m[1].lower(), url)
    if m := re.search(r"twitch\.tv/(\w+)", url, re.I):
        return CanalTwitch(m[1], url)
    if m := re.search(r"(?:x|twitter)\.com/i/broadcasts/(\w+)", url, re.I):
        return CanalX(m[1], url)
    if re.search(r"(?:x|twitter)\.com/", url, re.I):
        raise ValueError("No X, use o link da transmissão (x.com/i/broadcasts/...). O link do perfil não funciona.")
    raise ValueError("Link não reconhecido. Use um link do Kick, X, Twitch ou YouTube.")
