"""Encontra a câmera do streamer na tela e decide o enquadramento vertical."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import cv2
import numpy as np

from .plataformas import sem_janela

MODELO = Path(__file__).resolve().parent.parent / "modelos" / "centerface.onnx"
ASPECTO_CAMERA = 1080 / 760
ASPECTO_JOGO = 1080 / 1160
ASPECTO_VERTICAL = 1080 / 1920
LARGURA, ALTURA = 960, 544

_rede = None
_trava = threading.Lock()


def detectar_rostos(quadro: np.ndarray, confianca: float = 0.55) -> list[tuple[float, float, float, float]]:
    """Rostos como (x, y, largura, altura), em frações da imagem."""
    global _rede
    h, w = quadro.shape[:2]
    blob = cv2.dnn.blobFromImage(quadro, 1.0, (LARGURA, ALTURA), (0, 0, 0), swapRB=False, crop=False)
    with _trava:
        if _rede is None:
            _rede = cv2.dnn.readNetFromONNX(str(MODELO))
        _rede.setInput(blob)
        calor, escala, deslocamento, _ = _rede.forward(["537", "538", "539", "540"])
    calor = np.squeeze(calor)
    linhas, colunas = np.where(calor > confianca)
    caixas, notas = [], []
    for l, c in zip(linhas, colunas):
        alt = float(np.exp(escala[0, 0, l, c]) * 4)
        lar = float(np.exp(escala[0, 1, l, c]) * 4)
        x = (c + float(deslocamento[0, 1, l, c]) + 0.5) * 4 - lar / 2
        y = (l + float(deslocamento[0, 0, l, c]) + 0.5) * 4 - alt / 2
        caixas.append([int(x), int(y), int(lar), int(alt)])
        notas.append(float(calor[l, c]))
    if not caixas:
        return []
    manter = cv2.dnn.NMSBoxes(caixas, notas, confianca, 0.3)
    return [
        (caixas[i][0] / LARGURA, caixas[i][1] / ALTURA, caixas[i][2] / LARGURA, caixas[i][3] / ALTURA)
        for i in np.array(manter).flatten()
    ]


def dimensoes(video: Path) -> tuple[int, int, float]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, **sem_janela(),
    )
    partes = r.stdout.split()
    return int(partes[0]), int(partes[1]), float(partes[2]) if len(partes) > 2 and partes[2] != "N/A" else 0.0


def amostrar(video: Path, quantidade: int = 18) -> list[np.ndarray]:
    w, h, dur = dimensoes(video)
    lar = 960
    alt = int(round(lar * h / w / 2)) * 2
    passo = max(dur / quantidade, 0.5) if dur else 3.0
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps=1/{passo:.3f},scale={lar}:{alt}",
         "-frames:v", str(quantidade), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        capture_output=True, **sem_janela(),
    )
    tamanho = lar * alt * 3
    return [
        np.frombuffer(r.stdout, np.uint8, tamanho, i * tamanho).reshape(alt, lar, 3)
        for i in range(len(r.stdout) // tamanho)
    ]


def _agrupar_rostos(por_quadro: list[list[tuple]]) -> list[dict]:
    """Junta rostos que ficam no mesmo lugar: é assim que a webcam se separa dos personagens do jogo."""
    grupos: list[dict] = []
    for q, rostos in enumerate(por_quadro):
        for x, y, w, h in rostos:
            cx, cy = x + w / 2, y + h / 2
            for g in grupos:
                if abs(g["cx"] - cx) < 0.05 and abs(g["cy"] - cy) < 0.08:
                    g["itens"].append((x, y, w, h))
                    g["quadros"].add(q)
                    n = len(g["itens"])
                    g["cx"] += (cx - g["cx"]) / n
                    g["cy"] += (cy - g["cy"]) / n
                    break
            else:
                grupos.append({"cx": cx, "cy": cy, "itens": [(x, y, w, h)], "quadros": {q}})
    return grupos


def _linha_fixa(forca: np.ndarray, inicio: int, fim: int, passo: int, minimo: float = 0.5) -> int | None:
    """Primeira linha reta persistente encontrada a partir do rosto."""
    for i in range(inicio, fim, passo):
        if 0 < i < len(forca) - 1 and forca[i] >= minimo and forca[i] >= forca[i - 1] and forca[i] >= forca[i + 1]:
            return i
    return None


def encontrar_moldura(quadros: list[np.ndarray], rosto: tuple) -> list[float]:
    """Procura as bordas da webcam; sem borda visível, estima pelo tamanho do rosto."""
    alt, lar = quadros[0].shape[:2]
    x, y, w, h = rosto
    fx0, fy0, fx1, fy1 = int(x * lar), int(y * alt), int((x + w) * lar), int((y + h) * alt)
    fw, fh = max(fx1 - fx0, 1), max(fy1 - fy0, 1)

    bordas_v, bordas_h = [], []
    for q in quadros:
        cinza = cv2.cvtColor(q, cv2.COLOR_BGR2GRAY).astype(np.int16)
        bordas_v.append(np.abs(np.diff(cinza, axis=1)) > 18)
        bordas_h.append(np.abs(np.diff(cinza, axis=0)) > 18)
    media_v, media_h = np.mean(bordas_v, axis=0), np.mean(bordas_h, axis=0)

    faixa_y = (max(0, fy0 - fh // 2), min(alt, fy1 + fh // 2))
    faixa_x = (max(0, fx0 - fw // 2), min(lar, fx1 + fw // 2))
    colunas = np.pad(media_v[faixa_y[0]:faixa_y[1]].mean(axis=0), (0, 1))
    linhas = np.pad(media_h[:, faixa_x[0]:faixa_x[1]].mean(axis=1), (0, 1))

    margem_x, margem_y = int(fw * 0.35), int(fh * 0.35)
    esq = _linha_fixa(colunas, fx0 - margem_x, max(fx0 - fw * 5, 0), -1)
    dir_ = _linha_fixa(colunas, fx1 + margem_x, min(fx1 + fw * 5, lar), 1)
    topo = _linha_fixa(linhas, fy0 - margem_y, max(fy0 - fh * 4, 0), -1)
    base = _linha_fixa(linhas, fy1 + margem_y, min(fy1 + fh * 4, alt), 1)

    centro_x, centro_y = (fx0 + fx1) / 2, (fy0 + fy1) / 2
    meia_l, meia_a = fw * 2.3, fh * 1.9
    x0 = (esq + 1) if esq is not None else max(0, centro_x - meia_l)
    x1 = (dir_ + 1) if dir_ is not None else min(lar, centro_x + meia_l)
    y0 = (topo + 1) if topo is not None else max(0, centro_y - meia_a)
    y1 = (base + 1) if base is not None else min(alt, centro_y + meia_a)

    # A webcam costuma encostar no canto da tela.
    if esq is None and x0 < lar * 0.04:
        x0 = 0
    if dir_ is None and x1 > lar * 0.96:
        x1 = lar
    if topo is None and y0 < alt * 0.05:
        y0 = 0
    if base is None and y1 > alt * 0.95:
        y1 = alt
    return [x0 / lar, y0 / alt, (x1 - x0) / lar, (y1 - y0) / alt]


def analisar(video: Path) -> dict:
    quadros = amostrar(video)
    if not quadros:
        return {"layout": "inteiro"}
    por_quadro = [detectar_rostos(q) for q in quadros]
    grupos = _agrupar_rostos(por_quadro)
    presenca = len(quadros) * 0.4

    grandes = [r for rostos in por_quadro for r in rostos if r[3] >= 0.2]
    com_grande = sum(1 for rostos in por_quadro if any(r[3] >= 0.2 for r in rostos))
    if com_grande >= len(quadros) * 0.5:
        return {"layout": "tela_cheia", "centro_x": float(np.median([r[0] + r[2] / 2 for r in grandes])),
                "centro_y": float(np.median([r[1] + r[3] / 2 for r in grandes]))}

    fixos = [g for g in grupos if len(g["quadros"]) >= presenca]
    if not fixos:
        return {"layout": "inteiro"}
    grupo = max(fixos, key=lambda g: (len(g["quadros"]), np.median([i[3] for i in g["itens"]])))
    rosto = tuple(float(v) for v in np.median(np.array(grupo["itens"]), axis=0))
    moldura = encontrar_moldura(quadros, rosto)
    if moldura[2] * moldura[3] > 0.6:
        return {"layout": "tela_cheia", "centro_x": rosto[0] + rosto[2] / 2, "centro_y": rosto[1] + rosto[3] / 2}
    return {"layout": "dividido", "camera": moldura, "rosto": list(rosto)}


def _recorte(x: float, y: float, w: float, h: float, largura: int, altura: int) -> dict:
    cw = max(2, int(round(w * largura / 2)) * 2)
    ch = max(2, int(round(h * altura / 2)) * 2)
    cx = int(np.clip(round(x * largura), 0, largura - cw))
    cy = int(np.clip(round(y * altura), 0, altura - ch))
    return {"w": cw, "h": ch, "x": cx, "y": cy}


def enquadrar_camera(moldura: list[float], rosto: list[float] | None, largura: int, altura: int) -> dict:
    """Maior área com a proporção da faixa superior, sem sair da moldura da webcam."""
    x, y, w, h = moldura
    px_w, px_h = w * largura, h * altura
    cx, cy = (rosto[0] + rosto[2] / 2, rosto[1] + rosto[3] / 2) if rosto else (x + w / 2, y + h / 2)
    if px_w / px_h > ASPECTO_CAMERA:
        novo_w = px_h * ASPECTO_CAMERA / largura
        nx = float(np.clip(cx - novo_w / 2, x, x + w - novo_w))
        return _recorte(nx, y, novo_w, h, largura, altura)
    novo_h = px_w / ASPECTO_CAMERA / altura
    ny = float(np.clip(cy - novo_h * 0.42, y, y + h - novo_h))
    return _recorte(x, ny, w, novo_h, largura, altura)


def enquadrar_jogo(moldura: list[float] | None, largura: int, altura: int) -> dict:
    """Centro da tela, deslocado para não repetir a webcam quando ela estiver no meio do caminho."""
    if largura / altura > ASPECTO_JOGO:
        w = altura * ASPECTO_JOGO / largura
        x = 0.5 - w / 2
        if moldura:
            cam0, cam1 = moldura[0], moldura[0] + moldura[2]
            if cam0 < x + w and cam1 > x:
                x = cam1 if (cam0 + cam1) / 2 < 0.5 else cam0 - w
                x = float(np.clip(x, 0, 1 - w))
        return _recorte(x, 0, w, 1, largura, altura)
    h = largura / ASPECTO_JOGO / altura
    return _recorte(0, 0.5 - h / 2, 1, h, largura, altura)


def planejar(video: Path, ajuste: dict | None = None) -> dict:
    """Une a detecção automática com o ajuste manual feito no painel."""
    ajuste = ajuste or {}
    modo = ajuste.get("modo") or "auto"
    largura, altura, _ = dimensoes(video)
    analise: dict = {}
    if modo == "auto" or (modo == "tela_cheia" and not ajuste.get("rect")):
        analise = analisar(video)
    if modo == "dividido" and not ajuste.get("rect"):
        analise = analisar(video)
    layout = analise.get("layout", "inteiro") if modo == "auto" else modo

    if altura > largura:
        layout = "inteiro"  # transmissão já vertical
    if layout == "dividido":
        moldura = ajuste.get("rect") or analise.get("camera")
        if not moldura:
            layout = "inteiro"
        else:
            rosto = analise.get("rosto") if not ajuste.get("rect") else None
            return {"layout": "dividido", "moldura": moldura, "rosto": rosto,
                    "camera": enquadrar_camera(moldura, rosto, largura, altura),
                    "jogo": enquadrar_jogo(moldura, largura, altura), "origem": "manual" if ajuste.get("rect") else "auto"}
    if layout == "tela_cheia":
        if ajuste.get("rect"):
            r = ajuste["rect"]
            centro = r[0] + r[2] / 2
        else:
            centro = analise.get("centro_x", 0.5)
        w = altura * ASPECTO_VERTICAL / largura
        x = float(np.clip(centro - w / 2, 0, max(0.0, 1 - w)))
        return {"layout": "tela_cheia", "recorte": _recorte(x, 0, min(w, 1), 1, largura, altura), "origem": modo}
    return {"layout": "inteiro", "origem": modo}
