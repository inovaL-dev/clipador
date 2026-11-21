"""Segue quem está falando: com duas ou mais pessoas na tela, o vertical mostra quem tem a palavra.

Ideia do TopClip (MIT), refeita aqui: o rosto certo não é o maior, é o que mexe a boca enquanto há voz.
1. acha os rostos uma vez por segundo e junta cada pessoa numa trilha;
2. mede o movimento da região da boca de cada trilha cinco vezes por segundo;
3. só conta o movimento quando o áudio tem voz (uma foto ou alguém mastigando não ganham a vez);
4. decide por janelas de um segundo, com histerese: só troca de pessoa quando a outra
   ganha com folga por duas janelas seguidas, e nenhum trecho fica com menos de dois segundos.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

from . import camera as cam
from . import efeitos
from .plataformas import sem_janela

FPS = 5
LAR, ALT = 640, 360
JANELA = 1.0
FOLGA = 1.3          # quem desafia precisa vencer por 30%
SEGUIDAS = 2         # ...em duas janelas seguidas
TRECHO_MINIMO = 2.0  # segundos


def _trilhas(deteccoes: list[tuple[float, list]]) -> list[dict]:
    """Junta os rostos de cada pessoa ao longo do vídeo (as pessoas costumam ficar no mesmo lugar)."""
    trilhas: list[dict] = []
    for t, rostos in deteccoes:
        for x, y, w, h in rostos:
            cx, cy = x + w / 2, y + h / 2
            perto = [tr for tr in trilhas if abs(tr["cx"] - cx) < max(.07, w * .9) and abs(tr["cy"] - cy) < max(.1, h)]
            if perto:
                tr = min(perto, key=lambda tr: abs(tr["cx"] - cx))
                tr["caixas"].append((t, (x, y, w, h)))
                n = len(tr["caixas"])
                tr["cx"] += (cx - tr["cx"]) / n
                tr["cy"] += (cy - tr["cy"]) / n
            else:
                trilhas.append({"cx": cx, "cy": cy, "caixas": [(t, (x, y, w, h))]})
    amostras = max(1, len(deteccoes))
    boas = [tr for tr in trilhas if len(tr["caixas"]) >= max(2, amostras * .3) and np.median([c[1][3] for c in tr["caixas"]]) >= .06]
    return sorted(boas, key=lambda tr: tr["cx"])


def _caixa(tr: dict, t: float) -> tuple:
    """A caixa da pessoa no instante `t`: a detecção mais próxima no tempo."""
    return min(tr["caixas"], key=lambda c: abs(c[0] - t))[1]


def _boca(cinza: np.ndarray, caixa: tuple) -> np.ndarray | None:
    x, y, w, h = caixa
    x0, x1 = int((x + w * .22) * LAR), int((x + w * .78) * LAR)
    y0, y1 = int((y + h * .6) * ALT), int((y + h * 1.02) * ALT)
    if x1 - x0 < 4 or y1 - y0 < 3:
        return None
    parte = cinza[max(0, y0):min(ALT, y1), max(0, x0):min(LAR, x1)]
    if parte.size == 0:
        return None
    parte = cv2.resize(parte, (24, 12), interpolation=cv2.INTER_AREA).astype(np.float32)
    return parte - parte.mean()  # tira a mudança de luz geral, fica o formato da boca


def _voz(video: Path, ini: float, dur: float, n: int) -> np.ndarray:
    """Para cada amostra de vídeo, se há voz naquele instante."""
    pcm = efeitos.ler_pcm(video, ini, dur).astype(np.float32) / 32768
    passo = 16000 // FPS
    q = min(n, len(pcm) // passo)
    voz = np.zeros(n, bool)
    if q < 3:
        return voz
    db = 10 * np.log10(np.mean(pcm[: q * passo].reshape(q, passo) ** 2, axis=1) + 1e-10)
    if float(np.percentile(db, 90) - np.percentile(db, 10)) < 6:
        voz[:q] = db > -48  # som contínuo (música, jogo, microfone sempre aberto): vale o que não for silêncio
    else:
        voz[:q] = db > max(-48.0, float(np.percentile(db, 30)) + 6)
    return voz


def decidir(energia: np.ndarray, voz: np.ndarray) -> list[tuple[float, float, int]]:
    """Quem fala em cada trecho, a partir do movimento da boca (amostras x pessoas) e da voz."""
    n, pessoas = energia.shape
    if n == 0 or pessoas == 0:
        return []
    base = np.maximum(np.percentile(energia, 35, axis=0), .8)  # boca parada de cada pessoa (cada rosto tem a sua textura e o seu ruído)
    sinal = np.clip(energia / base - 1.0, 0, 6) * voz[:, None]
    por_janela = max(1, int(JANELA * FPS))
    janelas = [sinal[i:i + por_janela].sum(axis=0) for i in range(0, n, por_janela)]
    atual = int(np.argmax(sum(janelas[:3]))) if janelas else 0
    escolha, desafio, quem = [], 0, None
    for k, j in enumerate(janelas):
        melhor = int(np.argmax(j))
        if melhor != atual and j[melhor] > max(j[atual] * FOLGA, .6):
            desafio = desafio + 1 if melhor == quem else 1
            quem = melhor
            if desafio >= SEGUIDAS:
                atual, desafio = melhor, 0
                if len(escolha) >= SEGUIDAS - 1:
                    for v in range(1, SEGUIDAS):
                        escolha[-v] = atual  # a troca vale desde quando a pessoa começou a falar
        else:
            desafio, quem = 0, None
        escolha.append(atual)
    trechos: list[list] = []
    for k, p in enumerate(escolha):
        t0, t1 = k * JANELA, min(n / FPS, (k + 1) * JANELA)
        if trechos and trechos[-1][2] == p:
            trechos[-1][1] = t1
        else:
            trechos.append([t0, t1, p])
    mudou = True
    while mudou and len(trechos) > 1:  # trechos curtos demais entram no vizinho
        mudou = False
        for i, (a, b, p) in enumerate(trechos):
            if b - a < TRECHO_MINIMO:
                viz = i - 1 if i > 0 else i + 1
                trechos[viz][0], trechos[viz][1] = min(trechos[viz][0], a), max(trechos[viz][1], b)
                del trechos[i]
                juntos = []
                for tr in trechos:
                    if juntos and juntos[-1][2] == tr[2]:
                        juntos[-1][1] = tr[1]
                    else:
                        juntos.append(tr)
                trechos = juntos
                mudou = True
                break
    return [(round(a, 2), round(b, 2), int(p)) for a, b, p in trechos]


def seguir_quem_fala(video: Path, ini: float = 0.0, dur: float | None = None) -> dict | None:
    """Trechos [(início, fim, pessoa)] e as pessoas com a posição de cada uma, ou None se só há uma pessoa."""
    _, _, total = cam.dimensoes(video)
    dur = float(dur or max(0.0, total - ini))
    if dur < 3:
        return None
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{ini:.3f}"] if ini > 0 else []) + ["-i", str(video), "-t", f"{dur:.3f}", "-an",
           "-vf", f"fps={FPS},scale={LAR}:{ALT}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **sem_janela())
    tamanho = LAR * ALT * 3
    cinzas, deteccoes = [], []
    try:
        n = 0
        while True:
            dados = proc.stdout.read(tamanho)
            if len(dados) < tamanho:
                break
            quadro = np.frombuffer(dados, np.uint8).reshape(ALT, LAR, 3)
            if n % FPS == 0:
                deteccoes.append((n / FPS, cam.detectar_rostos(quadro, .5)))
            cinzas.append(cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY))
            n += 1
    finally:
        proc.stdout.close(); proc.kill(); proc.wait()
    pessoas = _trilhas(deteccoes)
    if len(pessoas) < 2:
        return None
    energia = np.zeros((len(cinzas), len(pessoas)), np.float32)
    anteriores: list[np.ndarray | None] = [None] * len(pessoas)
    for k, cinza in enumerate(cinzas):
        t = k / FPS
        for p, tr in enumerate(pessoas):
            boca = _boca(cinza, _caixa(tr, t))
            if boca is not None and anteriores[p] is not None and boca.shape == anteriores[p].shape:
                energia[k, p] = float(np.mean(np.abs(boca - anteriores[p])))
            anteriores[p] = boca
    trechos = decidir(energia, _voz(video, ini, dur, len(cinzas)))
    if len({p for _, _, p in trechos}) < 2:
        quem = trechos[0][2] if trechos else 0
        trechos = [(0.0, round(dur, 2), quem)]
    return {"trechos": trechos, "pessoas": [{"cx": round(tr["cx"], 4), "cy": round(tr["cy"], 4),
                                            "h": round(float(np.median([c[1][3] for c in tr["caixas"]])), 4)} for tr in pessoas]}
