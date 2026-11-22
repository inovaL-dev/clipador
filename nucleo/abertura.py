"""Gancho de abertura dos Shorts: começar pelo auge.

Quem rola o feed decide em 1 a 2 segundos se fica. Por isso o corte abre com 2 a 3 segundos do melhor
momento (o grito, a risada, o susto), volta com um efeito de fita rebobinando e então conta a história
do começo. Quem viu o auge fica para entender como se chegou nele.

O auge é escolhido pelo pico de som perto do momento e pelas falas fortes da reação. Se a história já
começa no auge, não tem prévia: o começo já prende sozinho.
"""
from __future__ import annotations

import re

from . import contexto as ctx

RISO = re.compile(r"^(k{3,}|(ha){2,}h?|(he){2,}h?|(rs){2,}|kakak\w*)$", re.I)
DURACAO = (1.5, 2.4, 3.0)  # mínima, ideal e máxima da prévia
SEM_PREVIA_ANTES = 4.5      # se o auge já está nos primeiros segundos, o começo prende sozinho


def _palavras(grupos: list[dict]) -> list[dict]:
    return sorted((p for g in grupos or [] for p in g.get("palavras") or []), key=lambda p: float(p["ini"]))


def escolher(grupos: list[dict], duracao: float, momento: float | None, picos: list[tuple[float, float]]) -> list[float] | None:
    """Devolve [início, fim] da prévia no tempo do corte, ou None quando não precisa."""
    if duracao < 14 or momento is None:
        return None
    palavras = _palavras(grupos)
    a0, b0 = max(0.0, momento - 1.0), min(duracao - 1.0, momento + 5.0)
    candidatos: dict[float, float] = {}
    for t, f in picos:
        if a0 <= t <= b0:
            candidatos[round(t, 1)] = candidatos.get(round(t, 1), 0.0) + float(f)
    for p in palavras:
        t = float(p["ini"])
        if a0 <= t <= b0 and (ctx.FORTES.search(p["p"]) or p["p"].endswith("!") or RISO.match(ctx._nucleo(p["p"]))):
            for c in list(candidatos) or [round(t, 1)]:
                if abs(c - t) < .9:
                    candidatos[c] = candidatos.get(c, 0.0) + .6
            candidatos.setdefault(round(t, 1), .6)
    centro = max(candidatos, key=candidatos.get) if candidatos else momento + .6
    ini = centro - .9
    if ini < SEM_PREVIA_ANTES:
        return None
    # Não começa nem termina no meio de uma palavra
    for p in palavras:
        if float(p["ini"]) < ini < float(p["fim"]):
            ini = float(p["ini"]) - .05
            break
    fim = ini + DURACAO[1]
    for p in palavras:
        if float(p["ini"]) < fim < float(p["fim"]):
            fim = float(p["fim"]) + .08 if float(p["fim"]) + .08 - ini <= DURACAO[2] else float(p["ini"]) - .03
            break
    fim = min(fim, duracao - .5, ini + DURACAO[2])
    if fim - ini < DURACAO[0]:
        return None
    return [round(max(0.0, ini), 3), round(fim, 3)]


def descrever(abertura: list[float]) -> str:
    a, b = abertura
    return f"Gancho de abertura: começa com o auge ({int(a // 60)}:{int(a % 60):02d}, {b - a:.1f} s) e volta para o começo da história".replace(".", ",", 1)
