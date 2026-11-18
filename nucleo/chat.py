"""Lê o chat das lives sem login e reconecta sozinho."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from collections import deque

KICK_WS = os.environ.get(
    "CLIPADOR_KICK_WS",
    "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=js&version=8.4.0&flash=false",
)
TWITCH_WS = "wss://irc-ws.chat.twitch.tv:443"
YT_BASE = os.environ.get("CLIPADOR_YT_BASE", "https://www.youtube.com")


class Chat:
    def __init__(self, config: dict, aviso=lambda texto: None):
        self.config = config
        self.aviso = aviso
        self.total = 0
        self.ultima = 0.0
        self.conectado = False
        self.recentes: deque[dict] = deque(maxlen=400)
        self.fim = threading.Event()
        self.trava = threading.Lock()
        self.thread = threading.Thread(target=self._rodar, daemon=True)

    def iniciar(self):
        self.thread.start()

    def encerrar(self):
        self.fim.set()

    def pegar(self) -> int:
        with self.trava:
            n, self.total = self.total, 0
        return n

    def ativo(self, janela=120) -> bool:
        return time.time() - self.ultima < janela

    def textos_desde(self, instante: float) -> list[str]:
        with self.trava:
            return [m["texto"] for m in self.recentes if m["t"] >= instante]

    def ultimas(self, limite=14) -> list[dict]:
        with self.trava:
            return list(self.recentes)[-limite:]

    def _registrar(self, autor: str, texto: str):
        agora = time.time()
        with self.trava:
            self.total += 1
            self.recentes.append({"t": agora, "autor": autor or "", "texto": texto or ""})
        self.ultima = agora

    def _rodar(self):
        funcoes = {"kick": self._kick, "twitch": self._twitch, "x": self._x, "youtube": self._youtube}
        func = funcoes[self.config["tipo"]]
        espera = 2
        while not self.fim.is_set():
            try:
                asyncio.run(self._com_fim(func()))
                espera = 2
            except Exception as e:  # o chat nunca pode derrubar a gravação
                self.conectado = False
                self.aviso(f"Chat desconectado: {e}")
            self.conectado = False
            self.fim.wait(espera)
            espera = min(espera * 2, 60)

    async def _com_fim(self, coro):
        tarefa = asyncio.ensure_future(coro)
        while not tarefa.done():
            if self.fim.is_set():
                tarefa.cancel()
                break
            await asyncio.sleep(0.5)
        try:
            await tarefa
        except asyncio.CancelledError:
            pass

    async def _kick(self):
        import websockets

        canal = f"chatrooms.{self.config['sala']}.v2"
        async with websockets.connect(KICK_WS, ping_interval=30) as ws:
            async for bruto in ws:
                ev = json.loads(bruto)
                nome = ev.get("event", "")
                if nome == "pusher:connection_established":
                    await ws.send(json.dumps({"event": "pusher:subscribe", "data": {"auth": "", "channel": canal}}))
                    self.conectado = True
                elif nome == "pusher:ping":
                    await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                elif nome == "App\\Events\\ChatMessageEvent":
                    try:
                        dados = json.loads(ev.get("data") or "{}")
                    except ValueError:
                        dados = {}
                    texto = re.sub(r"\[emote:\d+:([^\]]*)\]", r"\1", dados.get("content") or "")
                    self._registrar((dados.get("sender") or {}).get("username"), texto)

    async def _twitch(self):
        import websockets

        async with websockets.connect(TWITCH_WS, ping_interval=30) as ws:
            await ws.send("PASS SCHMOOPIIE")
            await ws.send(f"NICK justinfan{int(time.time()) % 89999 + 10000}")
            await ws.send(f"JOIN #{self.config['sala']}")
            self.conectado = True
            async for bruto in ws:
                for linha in str(bruto).split("\r\n"):
                    if linha.startswith("PING"):
                        await ws.send(linha.replace("PING", "PONG", 1))
                    elif m := re.match(r":(\w+)!\S+ PRIVMSG #\S+ :(.*)", linha):
                        self._registrar(m[1], m[2])

    async def _x(self):
        import websockets

        acesso = await asyncio.to_thread(_acesso_chat_x, self.config["sala"])
        url = acesso["endpoint"].replace("https://", "wss://").rstrip("/") + "/chatapi/v1/chatnow"
        async with websockets.connect(url, ping_interval=30) as ws:
            await ws.send(json.dumps({"kind": 3, "payload": json.dumps({"access_token": acesso["access_token"]})}))
            corpo = json.dumps({"room": acesso["sala"]})
            await ws.send(json.dumps({"kind": 2, "payload": json.dumps({"kind": 1, "body": corpo})}))
            self.conectado = True
            async for bruto in ws:
                ev = json.loads(bruto)
                if ev.get("kind") != 1:
                    continue
                try:
                    envelope = json.loads(ev.get("payload") or "{}")
                    corpo = json.loads(envelope.get("body") or "{}")
                except ValueError:
                    continue
                if corpo.get("body"):
                    self._registrar(corpo.get("username") or (envelope.get("sender") or {}).get("username"), corpo["body"])

    async def _youtube(self):
        from curl_cffi import requests

        video = self.config.get("sala")
        if not video:
            raise RuntimeError("live sem identificador de chat")
        sessao = requests.Session(impersonate="chrome")
        pagina = await asyncio.to_thread(
            sessao.get, f"{YT_BASE}/live_chat?is_popout=1&v={video}", timeout=20,
            headers={"Accept-Language": "pt-BR,pt;q=0.9"}, cookies={"SOCS": "CAI"},
        )
        pagina.raise_for_status()
        chave, contexto, continuacao = yt_dados_iniciais(pagina.text)
        versao = (contexto.get("client") or {}).get("clientVersion", "")
        url = f"{YT_BASE}/youtubei/v1/live_chat/get_live_chat?key={chave}&prettyPrint=false"
        vistos: dict[str, None] = {}
        primeira = True
        self.conectado = True
        ultima_novidade = time.time()
        while True:
            if time.time() - ultima_novidade > 90:
                raise RuntimeError("o chat parou de atualizar")
            r = await asyncio.to_thread(
                sessao.post, url, json={"context": contexto, "continuation": continuacao}, timeout=20,
                headers={"X-YouTube-Client-Name": "1", "X-YouTube-Client-Version": versao},
            )
            r.raise_for_status()
            chat = (r.json().get("continuationContents") or {}).get("liveChatContinuation")
            if not chat:
                raise RuntimeError("o YouTube não devolveu o chat")
            novas = yt_mensagens(chat.get("actions") or [], vistos)
            if novas:
                ultima_novidade = time.time()
            # A primeira resposta traz o histórico, que não é reação de agora.
            if not primeira:
                for autor, texto in novas:
                    self._registrar(autor, texto)
            primeira = False
            proxima = yt_proxima(chat)
            if not proxima:
                raise RuntimeError("o chat foi encerrado")
            continuacao, espera = proxima
            await asyncio.sleep(min(max(espera, 1.0), 8.0))


def yt_dados_iniciais(html: str) -> tuple[str, dict, str]:
    """Extrai da página do chat a chave, o contexto e o token do chat completo."""
    leitor = json.JSONDecoder()
    chave = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
    ctx = re.search(r'"INNERTUBE_CONTEXT"\s*:\s*\{', html)
    ini = re.search(r'ytInitialData"?\]?\s*=\s*\{', html)
    if not (chave and ctx and ini):
        raise RuntimeError("chat indisponível nesta live")
    contexto = leitor.raw_decode(html, ctx.end() - 1)[0]
    dados = leitor.raw_decode(html, ini.end() - 1)[0]
    render = (dados.get("contents") or {}).get("liveChatRenderer") or {}
    try:
        # O segundo item é o "Chat ao vivo"; o primeiro é o filtrado ("Principais").
        menu = render["header"]["liveChatHeaderRenderer"]["viewSelector"]["sortFilterSubMenuRenderer"]["subMenuItems"]
        token = menu[1]["continuation"]["reloadContinuationData"]["continuation"]
    except (KeyError, IndexError, TypeError):
        try:
            token = next(iter(render["continuations"][0].values()))["continuation"]
        except (KeyError, IndexError, StopIteration, TypeError):
            raise RuntimeError("chat indisponível nesta live") from None
    return chave[1], contexto, token


def yt_mensagens(acoes: list[dict], vistos: dict[str, None]) -> list[tuple[str, str]]:
    novas = []
    for acao in acoes:
        item = (acao.get("addChatItemAction") or {}).get("item") or {}
        msg = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
        if not msg:
            continue
        ident = msg.get("id")
        if ident and ident in vistos:
            continue
        if ident:
            vistos[ident] = None
            if len(vistos) > 5000:
                del vistos[next(iter(vistos))]
        partes = (msg.get("message") or {}).get("runs") or []
        texto = "".join(p.get("text") or ((p.get("emoji") or {}).get("shortcuts") or [""])[0] for p in partes)
        novas.append(((msg.get("authorName") or {}).get("simpleText") or "", texto))
    return novas


def yt_proxima(chat: dict) -> tuple[str, float] | None:
    for item in chat.get("continuations") or []:
        for tipo in ("invalidationContinuationData", "timedContinuationData", "reloadContinuationData"):
            dados = item.get(tipo)
            if dados and dados.get("continuation"):
                return dados["continuation"], float(dados.get("timeoutMs") or 5000) / 1000
    return None


def _acesso_chat_x(broadcast_id: str) -> dict:
    import yt_dlp
    from curl_cffi import requests

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        ie = ydl.get_info_extractor("TwitterBroadcast")
        dados = ie._call_api("broadcasts/show.json", broadcast_id, {"ids": broadcast_id})
        chave = dados["broadcasts"][broadcast_id]["media_key"]
        status = ie._call_api(f"live_video_stream/status/{chave}", chave)
    r = requests.post(
        "https://proxsee.pscp.tv/api/v2/accessChatPublic",
        json={"chat_token": status["chatToken"]}, impersonate="chrome", timeout=20,
    )
    r.raise_for_status()
    return {**r.json(), "sala": broadcast_id}
