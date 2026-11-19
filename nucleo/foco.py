"""Aproxima o que o streamer está mostrando, como as estrelas de procurado ou o minimapa."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np

CANTOS = {
    "topo_direita": (.58, 0, .42, .28), "topo_esquerda": (0, 0, .42, .28), "topo_meio": (.25, 0, .5, .2),
    "baixo_esquerda": (0, .62, .36, .38), "baixo_direita": (.6, .66, .4, .34), "baixo_meio": (.25, .78, .5, .22), "lado_esquerdo": (0, .12, .36, .46),
}
# Cada assunto aponta para os lugares onde os jogos costumam mostrar essa informação.
ASSUNTOS = (
    (r"estrelas?$|procurad[oa]s?$", "Estrelas", ("topo_direita", "topo_esquerda")),
    (r"minimapa$|mapinha$|radar$|mapa$", "Mapa", ("baixo_esquerda", "topo_direita", "topo_esquerda")),
    (r"vida$|colete$|escudo$|armadura$|hp$", "Vida", ("baixo_esquerda", "topo_esquerda", "baixo_meio")),
    (r"dinheiro$|grana$|reais$|dolares?$|moedas?$|saldo$", "Dinheiro", ("topo_direita", "topo_esquerda")),
    (r"municao$|balas?$|pente$", "Munição", ("baixo_direita", "topo_direita")),
    (r"placar$|kills?$|abates?$|pontos$|pontuacao$", "Placar", ("topo_meio", "topo_direita")),
    (r"missao$|objetivo$", "Missão", ("lado_esquerdo", "topo_esquerda")),
    (r"nivel$|level$|xp$", "Nível", ("topo_esquerda", "baixo_meio")),
    (r"inventario$|mochila$", "Inventário", ("baixo_direita", "baixo_meio")),
    (r"cronometro$|timer$", "Tempo", ("topo_meio", "topo_direita")),
)
APONTAR = re.compile(r"^(olha|ve|viu|ta|olhem|repara) (isso|aqui|ali|la|so|vendo|ai)$")
MAXIMO = 3
ESPACO = 5.0
LARGURA = 480


def _normal(p: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFD", p.lower()).encode("ascii", "ignore").decode())


def gatilhos(palavras: list[dict]) -> list[dict]:
    """Encontra na fala os momentos em que vale mostrar algo da tela."""
    saida = []
    limpas = [_normal(str(p["p"])) for p in palavras]
    for n, p in enumerate(palavras):
        for padrao, nome, lugares in ASSUNTOS:
            if re.search(padrao, limpas[n]):
                saida.append({"t": float(p["ini"]), "fim": float(p["fim"]), "nome": nome, "lugares": lugares})
                break
        else:
            if n + 1 < len(palavras) and APONTAR.match(f"{limpas[n]} {limpas[n + 1]}"):
                saida.append({"t": float(p["ini"]), "fim": float(palavras[n + 1]["fim"]), "nome": "Olha isso", "lugares": ()})
    return saida


def _ler(fonte: Path, tempos: list[float]) -> list[np.ndarray]:
    v = cv2.VideoCapture(str(fonte))
    saida = []
    for t in tempos:
        v.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
        ok, q = v.read()
        if ok:
            h, w = q.shape[:2]
            saida.append(cv2.cvtColor(cv2.resize(q, (LARGURA, round(LARGURA * h / w)), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32))
    v.release()
    return saida


def _maior_bloco(mascara: np.ndarray, minimo: float, maximo: float) -> tuple[int, int, int, int] | None:
    k = max(3, mascara.shape[1] // 22) | 1
    junto = cv2.morphologyEx(mascara.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(junto)
    total = mascara.size
    blocos = [s for s in st[1:] if minimo * total <= s[4] <= maximo * total and s[2] >= 8 and s[3] >= 5]
    if not blocos:
        return None
    s = max(blocos, key=lambda b: b[4])
    return int(s[0]), int(s[1]), int(s[2]), int(s[3])


def achar_hud(quadros: list[np.ndarray], lugar: tuple[float, float, float, float], proibido: np.ndarray | None = None) -> tuple[float, float, float, float] | None:
    """Informação de jogo fica parada e bem desenhada enquanto o cenário se move."""
    pilha = np.stack(quadros)
    H, W = pilha.shape[1:]
    x0, y0, x1, y1 = int(lugar[0] * W), int(lugar[1] * H), int((lugar[0] + lugar[2]) * W), int((lugar[1] + lugar[3]) * H)
    if float((pilha.std(axis=0) > 12).mean()) < .12:
        return None  # com a imagem parada não dá para separar a informação do cenário
    media = pilha[:, y0:y1, x0:x1].mean(axis=0)
    parado = pilha[:, y0:y1, x0:x1].std(axis=0) < 9
    borda = np.abs(cv2.Laplacian(media, cv2.CV_32F, ksize=3)) > 34
    mascara = parado & cv2.dilate(borda.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    if proibido is not None:
        mascara &= ~proibido[y0:y1, x0:x1]
    b = _maior_bloco(mascara, .004, .5)
    if not b:
        return None
    return ((b[0] + x0) / W, (b[1] + y0) / H, b[2] / W, b[3] / H)


def achar_mudanca(quadros: list[np.ndarray], proibido: np.ndarray | None = None) -> tuple[float, float, float, float] | None:
    """Sem assunto na fala, procura o ponto que mudou enquanto o resto da tela ficou igual."""
    a, b = quadros[0], quadros[-1]
    H, W = a.shape
    mascara = cv2.GaussianBlur(np.abs(a - b), (0, 0), 2) > 38
    if proibido is not None:
        mascara &= ~proibido
    if not .002 <= float(mascara.mean()) <= .2:
        return None
    r = _maior_bloco(mascara, .002, .2)
    return (r[0] / W, r[1] / H, r[2] / W, r[3] / H) if r else None


def enquadrar(alvo: tuple[float, float, float, float], aspecto: float, vw: int, vh: int) -> dict:
    """Abre o recorte em volta do alvo no formato exato do painel do vídeo."""
    x, y, w, h = alvo[0] * vw, alvo[1] * vh, alvo[2] * vw, alvo[3] * vh
    cx, cy = x + w / 2, y + h / 2
    nw = max(w * 1.5, vw * .2)
    nh = max(h * 1.5, nw / aspecto)
    nw = max(nw, nh * aspecto)
    escala = min(1.0, vw / nw, vh / nh)
    nw, nh = nw * escala, nh * escala
    nx, ny = float(np.clip(cx - nw / 2, 0, vw - nw)), float(np.clip(cy - nh / 2, 0, vh - nh))
    par = lambda v: int(v) // 2 * 2
    return {"x": par(nx), "y": par(ny), "w": max(2, par(nw)), "h": max(2, par(nh))}


def painel(plano: dict) -> tuple[int, int, int, int]:
    """Onde o jogo aparece no vídeo vertical."""
    layout = plano.get("layout")
    if layout == "dividido":
        return 0, 763, 1080, 1157
    if layout == "inteiro":
        return 0, 420, 1080, 1080
    return 0, 0, 1080, 1920


def _proibido(plano: dict, vw: int, vh: int, altura: int) -> np.ndarray | None:
    c = plano.get("camera")
    if not c:
        return None
    m = np.zeros((altura, LARGURA), bool)
    ex, ey = LARGURA / vw, altura / vh
    m[int(c["y"] * ey):int((c["y"] + c["h"]) * ey) + 1, int(c["x"] * ex):int((c["x"] + c["w"]) * ex) + 1] = True
    return m


def achar_focos(fonte: Path, grupos: list[dict], plano: dict, duracao: float, momento: float | None = None) -> list[dict]:
    """Só aproxima quando encontra na imagem o que foi citado. Na dúvida, não mexe no vídeo."""
    palavras = [p for g in grupos for p in g.get("palavras", [])]
    cap = cv2.VideoCapture(str(fonte))
    vw, vh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if not vw or not vh:
        return []
    px, py, pw, ph = painel(plano)
    focos: list[dict] = []
    for g in gatilhos(palavras):
        if len(focos) >= MAXIMO:
            break
        ini = max(.2, g["t"] - .12)
        dur = float(np.clip(g["fim"] - ini + 1.5, 2.0, 3.2))
        if ini + dur > duracao - .3 or any(abs(ini - f["t"]) < ESPACO for f in focos):
            continue
        if plano.get("layout") == "pip" and momento is not None and ini < momento + 2 and ini + dur > momento - .1:
            continue  # nessa hora a webcam cresce no meio da tela
        quadros = _ler(fonte, list(np.linspace(max(0.0, ini - .6), min(duracao, ini + 1.8), 8)))
        if len(quadros) < 5:
            continue
        proibido = _proibido(plano, vw, vh, quadros[0].shape[0])
        alvo = next((a for a in (achar_hud(quadros, CANTOS[l], proibido) for l in g["lugares"]) if a), None) if g["lugares"] else achar_mudanca(quadros, proibido)
        if alvo:
            focos.append({"t": round(ini, 3), "dur": round(dur, 3), "nome": g["nome"], **enquadrar(alvo, pw / ph, vw, vh)})
    return focos
