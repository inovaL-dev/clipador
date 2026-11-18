"""Transições e efeitos de imagem usados na edição automática e no editor."""
from __future__ import annotations

import math

import cv2
import numpy as np

TIPOS = ("chicote", "queda", "impulso", "giro", "glitch", "rgb", "clarao_rapido", "desfoque_rapido")


def _borrar(q: np.ndarray, kx: int, ky: int) -> np.ndarray:
    h, w = q.shape[:2]
    p = cv2.resize(q, (w // 3, h // 3), interpolation=cv2.INTER_LINEAR)
    p = cv2.blur(p, (max(1, kx // 3), max(1, ky // 3)))
    return cv2.resize(p, (w, h), interpolation=cv2.INTER_LINEAR)


def separar_cores(q: np.ndarray, d: int) -> np.ndarray:
    if d < 1:
        return q
    b, g, r = cv2.split(q)
    return cv2.merge([np.roll(b, -d, axis=1), g, np.roll(r, d, axis=1)])


def falha(q: np.ndarray, forca: float, semente: int) -> np.ndarray:
    """Faixas da imagem saltam para os lados, como um sinal com defeito."""
    h, w = q.shape[:2]
    rng = np.random.default_rng(semente)
    s = separar_cores(q, int(w * .03 * forca)).copy()
    for _ in range(int(4 + 12 * forca)):
        y, a = int(rng.integers(0, h)), int(rng.integers(max(2, h // 90), max(3, h // 14)))
        s[y:y + a] = np.roll(s[y:y + a], int(rng.integers(-w // 5, w // 5) * forca), axis=1)
    return s


def _afim(q: np.ndarray, escala: float, angulo: float) -> np.ndarray:
    h, w = q.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angulo, escala)
    return cv2.warpAffine(q, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def aplicar(q: np.ndarray, tipo: str, p: float, lado: int, semente: int = 0) -> np.ndarray:
    """`p` vai de 0 (sem efeito) a 1 (no ponto do corte). `lado` é -1 na saída da cena e 1 na entrada."""
    p = float(np.clip(p, 0, 1))
    if p <= .01:
        return q
    h, w = q.shape[:2]
    e = p * p
    if tipo in ("chicote", "queda"):
        horizontal = tipo == "chicote"
        d = int(e * (w if horizontal else h) * .9) * lado  # a cena sai e a próxima entra no mesmo sentido
        s = np.roll(q, d, axis=1 if horizontal else 0)
        k = int(max(w, h) * .22 * p)
        return _borrar(s, k, 1) if horizontal else _borrar(s, 1, k)
    if tipo == "impulso":
        a = _afim(q, 1 + e * .9, 0)
        return cv2.addWeighted(a, .6, _afim(q, 1 + e * .45, 0), .4, 0)
    if tipo == "giro":
        return _borrar(_afim(q, 1 + e * .7, e * 28 * lado), int(w * .05 * p), int(w * .05 * p))
    if tipo == "glitch":
        return falha(q, p, semente)
    if tipo == "rgb":
        return separar_cores(_afim(q, 1 + e * .25, 0), int(w * .07 * p))
    if tipo == "clarao_rapido":
        return cv2.addWeighted(q, 1 - p, np.full_like(q, 255), p, 0)
    if tipo == "desfoque_rapido":
        return _borrar(q, int(w * .12 * p), int(w * .12 * p))
    return q


def efeito_continuo(q: np.ndarray, tipo: str, forca: float, u: float, n: int) -> np.ndarray | None:
    """Efeitos de imagem que ficam ativos durante um trecho."""
    h, w = q.shape[:2]
    if tipo == "rgb":
        return separar_cores(q, int(w * .018 * forca * (1 + .5 * math.sin(u * 22))))
    if tipo == "glitch":
        return falha(q, forca, n // 3) if (n // 5) % 3 != 2 else q
    if tipo == "pulso":
        return _afim(q, 1 + .09 * forca * abs(math.sin(u * math.pi * 2)), 0)
    if tipo == "sacudir":
        return cv2.warpAffine(q, np.array([[1, 0, 14 * forca * math.sin(n * 2.1)], [0, 1, 14 * forca * math.cos(n * 2.9)]], np.float64), (w, h), borderMode=cv2.BORDER_REFLECT)
    if tipo == "barras":
        s = q.copy(); a = int(h * .11 * forca); s[:a] = 0; s[h - a:] = 0
        return s
    if tipo == "pb":
        c = cv2.cvtColor(cv2.cvtColor(q, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        return cv2.addWeighted(q, 1 - forca, c, forca, 0)
    if tipo == "brilho":
        s = _borrar(q, int(w * .05), int(w * .05))
        return 255 - cv2.multiply(255 - q, 255 - cv2.convertScaleAbs(s, alpha=.55 * forca), scale=1 / 255)
    if tipo == "negativo":
        return cv2.addWeighted(q, 1 - forca, 255 - q, forca, 0)
    if tipo == "espelho":
        s = q.copy(); s[:, w // 2:] = cv2.flip(q[:, :w - w // 2], 1)
        return s
    return None
