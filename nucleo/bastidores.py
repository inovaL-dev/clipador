"""Bastidores da edição: o que o Clipador está fazendo em cada corte, para a tela "Assistir a edição".

Cada etapa conta o que decidiu (a fala que ouviu, onde a história começa e termina, onde achou o rosto,
os zooms, as trocas de câmera, as legendas, os sons) e, na montagem, um quadro pequeno do vídeo de vez em quando.
O relato é guardado por linha de execução: quem processa o corte liga o relator antes e desliga depois.
"""
from __future__ import annotations

import threading
from pathlib import Path

import cv2

_local = threading.local()
A_CADA = 6  # um quadro de prévia a cada 6 (5 por segundo do vídeo)


def ligar(relator, pasta: Path | None = None) -> None:
    _local.relator, _local.pasta = relator, pasta


def desligar() -> None:
    _local.relator, _local.pasta = None, None


def contar(**dados) -> None:
    relator = getattr(_local, "relator", None)
    if relator:
        try:
            relator(dados)
        except Exception:
            pass  # os bastidores nunca atrapalham a edição


def ligado() -> bool:
    return getattr(_local, "relator", None) is not None


def acompanhar_fala(trechos):
    """Repassa os trechos da transcrição e conta cada frase assim que ela é ouvida."""
    for t in trechos:
        if ligado():
            palavras = [{"p": p.word.strip(), "ini": round(p.start, 2), "fim": round(p.end, 2)} for p in (t.words or []) if p.word.strip()]
            contar(fala=palavras, ouvido=round(float(t.end), 2), log=("fala", (t.text or "").strip()))
        yield t


def acompanhar_quadros(quadros, total: int):
    """Repassa os quadros do vídeo e guarda uma prévia pequena de vez em quando."""
    pasta = getattr(_local, "pasta", None)
    for n, q in enumerate(quadros):
        if pasta is not None and n % A_CADA == 0 and ligado():
            try:
                pequeno = cv2.resize(q, (270, 480), interpolation=cv2.INTER_AREA)
                tmp = pasta / "bastidores_tmp.jpg"
                if cv2.imwrite(str(tmp), pequeno, [cv2.IMWRITE_JPEG_QUALITY, 72]):
                    tmp.replace(pasta / "bastidores.jpg")
            except OSError:
                pass
            contar(render=[n, total])
        yield q
    contar(render=[total, total])
