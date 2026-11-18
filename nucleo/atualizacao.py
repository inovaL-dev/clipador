"""Descobre se saiu uma versão nova do Clipador e avisa dentro do programa."""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
import webbrowser

from .versao import VERSAO

ENDERECO = os.environ.get("CLIPADOR_ATUALIZACAO", "https://inoval-dev.github.io/versao.json")
ORIGENS = ("https://github.com/inovaL-dev/clipador/", "https://inoval-dev.github.io/")
ESPERA_INICIAL = 15
INTERVALO = 6 * 3600
LIMITE = 256 * 1024


def numero(versao: str) -> tuple[int, ...]:
    if not re.fullmatch(r"\d{1,4}(\.\d{1,4}){0,3}", str(versao)):
        raise ValueError("Número de versão inválido.")
    partes = [int(p) for p in str(versao).split(".")]
    return tuple(partes + [0] * (4 - len(partes)))


def ler_publicacao(dados: dict) -> dict:
    """Aceita só o que o programa sabe mostrar com segurança."""
    url = str(dados.get("baixar") or "")
    if not url.startswith(ORIGENS):
        raise ValueError("Endereço de download inválido.")
    numero(dados.get("versao"))
    notas = [str(n).strip()[:200] for n in (dados.get("notas") or []) if str(n).strip()][:8]
    return {"versao": str(dados["versao"]), "notas": notas, "baixar": url}


class Atualizacao:
    def __init__(self):
        self.trava = threading.Lock()
        self.nova: dict | None = None
        self.verificado = 0.0
        self.erro = False
        self.parar = threading.Event()
        threading.Thread(target=self._vigiar, daemon=True).start()

    def _vigiar(self) -> None:
        if self.parar.wait(ESPERA_INICIAL):
            return
        while True:
            self.verificar()
            if self.parar.wait(INTERVALO):
                return

    def verificar(self) -> dict:
        try:
            pedido = urllib.request.Request(ENDERECO, headers={"User-Agent": f"Clipador/{VERSAO}", "Cache-Control": "no-cache"})
            with urllib.request.urlopen(pedido, timeout=12) as r:
                pub = ler_publicacao(json.loads(r.read(LIMITE).decode("utf-8")))
            with self.trava:
                self.nova = pub if numero(pub["versao"]) > numero(VERSAO) else None
                self.verificado, self.erro = time.time(), False
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            with self.trava:
                self.erro = True  # sem internet o programa segue normalmente
        return self.resumo()

    def resumo(self) -> dict:
        with self.trava:
            return {"atual": VERSAO, "nova": self.nova, "verificado": self.verificado, "erro": self.erro}

    def abrir(self) -> dict:
        with self.trava:
            url = self.nova["baixar"] if self.nova else None
        if not url:
            raise ValueError("Nenhuma atualização disponível.")
        webbrowser.open(url)
        return {"ok": True}
