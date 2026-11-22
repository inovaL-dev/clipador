"""Quanto do processador o Clipador usa: leve ou total.

Total: a legenda e a montagem dos vídeos usam quase todos os núcleos. Mais rápido, mas o computador
trabalha no máximo e um PC fraco ou mal ventilado esquenta.
Leve: metade dos núcleos e prioridade baixa. Demora mais, o computador esquenta menos e continua
usável enquanto os cortes são feitos.
A gravação da live nunca fica com prioridade baixa: perder um pedaço da live é pior.
"""
from __future__ import annotations

import os

MODOS = ("auto", "leve", "total")
_modo = "auto"


def definir(modo: str) -> None:
    global _modo
    _modo = modo if modo in MODOS else "auto"


def recomendado() -> str:
    from .fala import memoria_gb

    return "leve" if memoria_gb() < 11.5 or (os.cpu_count() or 2) <= 4 else "total"


def valendo() -> str:
    return recomendado() if _modo == "auto" else _modo


def leve() -> bool:
    return valendo() == "leve"


def nucleos_legenda() -> int:
    n = os.cpu_count() or 4
    return max(1, n // 2) if leve() else max(1, min(8, n - 2))


def resumo() -> dict:
    from .fala import memoria_gb

    return {"modo": _modo, "valendo": valendo(), "recomendado": recomendado(), "nucleos": os.cpu_count() or 1, "memoria_gb": round(memoria_gb())}
