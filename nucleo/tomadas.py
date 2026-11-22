"""Câmera dinâmica para cortes com webcam em cima e jogo embaixo.

Os cortes de react mais assistidos não ficam o tempo todo divididos ao meio. Eles trocam de "câmera":
- o jogo ocupa a tela inteira quando é ele que conta a história (o que causou a reação, um trecho sem fala);
- o rosto do streamer ocupa a tela inteira, bem perto, quando ele reage (grito, risada, palavrão, susto);
- no resto do tempo a tela volta para a divisão, que mostra as duas coisas.

As trocas são curtas (1 a 2,5 s), nunca coladas umas nas outras e não passam de um terço do vídeo,
para a pessoa nunca perder o fio do que está acontecendo.
"""
from __future__ import annotations

import re

import numpy as np

from . import contexto as ctx

RISO = re.compile(r"^(k{3,}|(ha){2,}h?|(he){2,}h?|(rs){2,}|kakak\w*)$", re.I)
INICIO_LIVRE = 1.4      # os primeiros segundos mostram as duas coisas: é o gancho
INTERVALO = 1.8         # tempo mínimo na tela dividida entre duas trocas
PARTE_MAXIMA = 0.34     # fração máxima do vídeo fora da tela dividida
ROSTO_Y_LEGENDA = 1180  # altura da legenda quando o rosto ou o jogo ocupam a tela toda


def _palavras(grupos: list[dict]) -> list[dict]:
    return sorted((p for g in grupos or [] for p in g.get("palavras") or []), key=lambda p: float(p["ini"]))


def planejar(grupos: list[dict], duracao: float, momento: float | None, picos: list[tuple[float, float]], fim_util: float | None = None, inicio: float = INICIO_LIVRE) -> list[dict]:
    """Devolve as trocas como [{"ini", "fim", "tipo": "rosto" | "jogo"}], em ordem."""
    fim_util = min(duracao, fim_util or duracao) - 0.5
    if fim_util - inicio < 4:
        return []
    palavras = _palavras(grupos)
    candidatos: list[tuple[float, float, float, str, int]] = []  # (prioridade, ini, fim, tipo, bloco)

    # 1. O momento: primeiro o que aconteceu no jogo, depois a cara do streamer.
    if momento is not None:
        m = float(momento)
        if m - 1.5 >= inicio:
            candidatos.append((10, m - 1.5, m + 0.25, "jogo", 1))
        candidatos.append((10, max(inicio, m + 0.25), m + 2.5, "rosto", 1))

    # 2. Fala com emoção: grito, risada, palavrão, exclamação.
    forca_pico = {round(t, 1): f for t, f in picos}
    for p in palavras:
        texto = ctx._nucleo(p["p"])
        if not (RISO.match(texto) or ctx.FORTES.search(p["p"]) or p["p"].endswith("!")):
            continue
        a = float(p["ini"]) - 0.12
        b = min(a + 2.3, max(float(p["fim"]) + 0.9, a + 1.4))
        perto = max((f for t, f in picos if abs(t - a) < 0.8), default=0.0)
        candidatos.append((6 + 2 * perto + (1 if RISO.match(texto) else 0), a, b, "rosto", 0))

    # 3. Picos fortes de som sem palavra reconhecida perto (grito, susto, risada sem texto).
    if picos:
        corte = float(np.quantile([f for _, f in picos], .6))
        for t, f in picos:
            if f >= corte and not any(abs(float(p["ini"]) - t) < 0.7 for p in palavras):
                candidatos.append((4 + f, t - 0.1, t + 1.6, "rosto", 0))

    # 4. Silêncio do streamer: o jogo conta a história sozinho.
    marcos = [(0.0, 0.0)] + [(float(p["ini"]), float(p["fim"])) for p in palavras] + [(duracao, duracao)]
    for (_, fim_a), (ini_b, _) in zip(marcos, marcos[1:]):
        if ini_b - fim_a >= 2.6:
            a = fim_a + 0.45
            candidatos.append((5, a, min(ini_b - 0.15, a + 2.2), "jogo", 0))

    escolhidas: list[dict] = []
    teto = PARTE_MAXIMA * duracao
    usado = 0.0
    for prio, a, b, tipo, bloco in sorted(candidatos, key=lambda c: -c[0]):
        a, b = max(a, inicio), min(b, fim_util)
        if b - a < 0.9 or usado + (b - a) > teto:
            continue
        livre = True
        for e in escolhidas:
            colado = bloco and e["bloco"] == bloco  # o jogo e a reação do momento podem vir em seguida
            folga = 0.0 if colado else INTERVALO
            if a < e["fim"] + folga and b > e["ini"] - folga:
                livre = False
                break
        if livre:
            escolhidas.append({"ini": round(a, 3), "fim": round(b, 3), "tipo": tipo, "bloco": bloco})
            usado += b - a
    # Respiro: mais de 8 s parado na tela dividida cansa; entra o rosto no pico de som mais forte do trecho.
    escolhidas.sort(key=lambda e: e["ini"])
    bordas = [max(3.5, inicio + 2) - INTERVALO] + [x for e in escolhidas for x in (e["ini"], e["fim"])] + [fim_util + INTERVALO]
    for a, b in zip(bordas[::2], bordas[1::2]):
        livre_a, livre_b = a + INTERVALO, b - INTERVALO
        if livre_b - livre_a < 8 - 2 * INTERVALO or usado + 1.4 > teto:
            continue
        dentro = [(t, f) for t, f in picos if livre_a <= t - .1 and t + 1.3 <= livre_b]
        t = max(dentro, key=lambda x: x[1])[0] - .1 if dentro else (livre_a + livre_b) / 2 - .7
        escolhidas.append({"ini": round(t, 3), "fim": round(t + 1.4, 3), "tipo": "rosto", "bloco": 0})
        usado += 1.4
    return [{k: v for k, v in e.items() if k != "bloco"} for e in sorted(escolhidas, key=lambda e: e["ini"])]


def tipo_em(tomadas: list[dict], t: float) -> str:
    for e in tomadas:
        if e["ini"] <= t < e["fim"]:
            return e["tipo"]
    return "dividido"


def enquadrar_rosto(plano: dict, largura: int, altura: int) -> dict:
    """Recorte 9:16 bem perto do rosto, dentro da moldura da webcam."""
    mx, my, mw, mh = plano["moldura"]
    mx, my, mw, mh = mx * largura, my * altura, mw * largura, mh * altura
    rosto = plano.get("rosto")
    if rosto:
        cx, cy, rh = (rosto[0] + rosto[2] / 2) * largura, (rosto[1] + rosto[3] / 2) * altura, rosto[3] * altura
        h = max(rh * 3.1, min(mh, 300.0))
    else:
        cx, cy, h = mx + mw / 2, my + mh * .45, mh * .9
    h = min(h, mh)
    w = h * 9 / 16
    if w > mw:
        w, h = mw, mw * 16 / 9
    x = float(np.clip(cx - w / 2, mx, mx + mw - w))
    y = float(np.clip(cy - h * .46, my, my + mh - h))
    w2, h2 = int(w) // 2 * 2, int(h) // 2 * 2
    return {"x": int(x), "y": int(y), "w": max(2, w2), "h": max(2, h2)}


def enquadrar_jogo(plano: dict, largura: int, altura: int) -> dict:
    """Recorte 9:16 no meio da área do jogo."""
    j = plano["jogo"]
    h = j["h"]
    w = h * 9 / 16
    if w > j["w"]:
        w, h = j["w"], j["w"] * 16 / 9
    x = j["x"] + (j["w"] - w) / 2
    y = j["y"] + (j["h"] - h) / 2
    return {"x": int(x), "y": int(y), "w": int(w) // 2 * 2, "h": int(h) // 2 * 2}


def enable(tomadas: list[dict], tipo: str) -> str:
    partes = [f"between(t,{e['ini']:.3f},{e['fim'] - 0.001:.3f})" for e in tomadas if e["tipo"] == tipo]
    return "+".join(partes)
