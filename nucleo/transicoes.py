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


# ------------------------------------------------------------ transições que misturam as duas cenas
# Wipes, íris, relógio, persianas, pixelar e tinta. Elas rodam
# em NumPy, quadro a quadro, para a prévia exata e a exportação darem o mesmo resultado.

MISTURAS = ("limpar_esquerda", "limpar_direita", "limpar_cima", "limpar_baixo", "diagonal", "iris", "relogio",
            "persianas", "pixelar", "zoom_cruzado", "tinta", "luz")
_campos: dict[tuple, np.ndarray] = {}


def _campo(tipo: str, h: int, w: int, semente: int = 0) -> np.ndarray:
    """Valor de 0 a 1 por pixel: a ordem em que a cena nova aparece."""
    chave = (tipo, h, w, semente if tipo == "tinta" else 0)
    if chave in _campos:
        return _campos[chave]
    x = np.linspace(0, 1, w, dtype=np.float32)[None, :]
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    if tipo == "limpar_esquerda":
        c = np.broadcast_to(1 - x, (h, w))
    elif tipo == "limpar_direita":
        c = np.broadcast_to(x, (h, w))
    elif tipo == "limpar_cima":
        c = np.broadcast_to(1 - y, (h, w))
    elif tipo == "limpar_baixo":
        c = np.broadcast_to(y, (h, w))
    elif tipo == "diagonal":
        c = (x * w + y * h) / float(w + h)
    elif tipo == "iris":
        dx, dy = (x - .5) * w, (y - .5) * h
        c = np.sqrt(dx ** 2 + dy ** 2) / (np.hypot(w, h) / 2)
    elif tipo == "relogio":
        ang = np.arctan2((x - .5) * w, -(y - .5) * h)  # começa ao meio-dia e gira no sentido do relógio
        c = (ang % (2 * np.pi)) / (2 * np.pi)
    elif tipo == "persianas":
        faixas = 9
        c = np.broadcast_to((y * faixas) % 1.0, (h, w))
    elif tipo == "tinta":
        rng = np.random.default_rng(1234 + semente)
        p = rng.random((max(2, h // 60), max(2, w // 60))).astype(np.float32)
        c = cv2.GaussianBlur(cv2.resize(p, (w, h), interpolation=cv2.INTER_CUBIC), (0, 0), max(2, min(w, h) / 40))
        c = (c - c.min()) / max(1e-6, float(c.max() - c.min()))
    else:
        c = np.zeros((h, w), np.float32)
    c = np.ascontiguousarray(c, dtype=np.float32)
    if len(_campos) > 40:
        _campos.clear()
    _campos[chave] = c
    return c


def _pixelado(q: np.ndarray, bloco: int) -> np.ndarray:
    if bloco < 2:
        return q
    h, w = q.shape[:2]
    p = cv2.resize(q, (max(1, w // bloco), max(1, h // bloco)), interpolation=cv2.INTER_AREA)
    return cv2.resize(p, (w, h), interpolation=cv2.INTER_NEAREST)


def misturar(a: np.ndarray, b: np.ndarray, tipo: str, p: float, semente: int = 0) -> np.ndarray:
    """`a` é a cena que sai, `b` a que entra e `p` vai de 0 a 1 ao longo da transição."""
    p = float(np.clip(p, 0, 1))
    if p <= .001:
        return a
    if p >= .999:
        return b
    h, w = a.shape[:2]
    if tipo == "pixelar":
        bloco = int(2 + max(w, h) * .06 * (1 - abs(2 * p - 1)))
        base = a if p < .5 else b
        mistura = float(np.clip((p - .4) / .2, 0, 1))
        if 0 < mistura < 1:
            base = cv2.addWeighted(a, 1 - mistura, b, mistura, 0)
        return _pixelado(base, bloco)
    if tipo == "zoom_cruzado":  # calculado em metade do tamanho: o desfoque esconde a diferença
        e = p * p * (3 - 2 * p)
        pa, pb = (cv2.resize(x, (max(2, w // 2), max(2, h // 2)), interpolation=cv2.INTER_AREA) for x in (a, b))
        sa = _borrar(_afim(pa, 1 + e * .8, 0), int(w * .05 * e) + 1, int(w * .05 * e) + 1)
        sb = _borrar(_afim(pb, 1.8 - .8 * e, 0), int(w * .05 * (1 - e)) + 1, int(w * .05 * (1 - e)) + 1)
        k = float(np.clip((p - .35) / .3, 0, 1))
        return cv2.resize(cv2.addWeighted(sa, 1 - k, sb, k, 0), (w, h), interpolation=cv2.INTER_LINEAR)
    if tipo == "luz":  # clarão quente que lava a imagem no meio da troca
        k = float(np.clip((p - .4) / .2, 0, 1))
        base = cv2.addWeighted(a, 1 - k, b, k, 0)
        brilho = 1 - abs(2 * p - 1)
        tinta = np.empty_like(base); tinta[:] = (120, 200, 255)
        return cv2.addWeighted(base, 1 - .85 * brilho, tinta, .85 * brilho, 0)
    campo = _campo(tipo, h, w, semente % 7)
    suave_ = .12 if tipo in ("tinta", "iris") else .06 if tipo != "persianas" else .08
    m = np.clip((p * (1 + suave_) - campo) / suave_, 0, 1)[..., None]
    return (a.astype(np.float32) * (1 - m) + b.astype(np.float32) * m).astype(np.uint8)


# ------------------------------------------------------------ efeitos de vídeo contínuos

EFEITOS_EXTRA = ("grao", "vhs", "estrobo", "luz_vazada", "pixelar", "duotone", "contorno_neon", "caleidoscopio",
                 "meio_tom", "super8", "desfoque_movimento")
_vinheta_cache: dict[tuple, np.ndarray] = {}


def _ruido(h: int, w: int, n: int, forca: float) -> np.ndarray:
    rng = np.random.default_rng(n * 7919 + h)
    pequeno = rng.normal(0, 1, (max(1, h // 2), max(1, w // 2))).astype(np.float32)
    return cv2.resize(pequeno, (w, h), interpolation=cv2.INTER_NEAREST) * forca


def _vinheta_mascara(h: int, w: int) -> np.ndarray:
    chave = (h // 4, w // 4)
    if chave not in _vinheta_cache:
        x, y = np.linspace(-1, 1, chave[1])[None, :], np.linspace(-1, 1, chave[0])[:, None]
        _vinheta_cache[chave] = np.clip((np.sqrt(x ** 2 + y ** 2) - .5) / .9, 0, 1).astype(np.float32)
    return cv2.resize(_vinheta_cache[chave], (w, h), interpolation=cv2.INTER_LINEAR)


def efeito_extra(q: np.ndarray, tipo: str, forca: float, u: float, n: int) -> np.ndarray | None:
    h, w = q.shape[:2]
    if h < 4 or w < 4:
        return q
    f = float(max(0.0, forca))
    if tipo == "grao":
        return np.clip(q.astype(np.float32) + _ruido(h, w, n, 22 * f)[..., None], 0, 255).astype(np.uint8)
    if tipo == "desfoque_movimento":
        k = max(1, int(w * .045 * f))
        return cv2.blur(q, (k, 1))
    if tipo == "pixelar":
        return _pixelado(q, int(2 + max(w, h) * .035 * f))
    if tipo == "estrobo":
        if (n // 3) % 2 == 0:
            return cv2.addWeighted(q, 1 - .75 * min(1.0, f), np.full_like(q, 255), .75 * min(1.0, f), 0)
        return q
    if tipo == "vhs":
        s = separar_cores(q, max(1, int(w * .008 * f)))
        rng = np.random.default_rng(n)
        if rng.random() < .35:
            y = int(rng.integers(0, h)); a = max(2, int(h * .04))
            s[y:y + a] = np.roll(s[y:y + a], int(w * .03 * f), axis=1)
        linhas = np.ones((h, 1), np.float32); linhas[::3] = 1 - .22 * min(1.0, f)
        s = (s.astype(np.float32) * linhas[..., None] + _ruido(h, w, n, 9 * f)[..., None])
        return cv2.GaussianBlur(np.clip(s, 0, 255).astype(np.uint8), (3, 1), 0)
    if tipo == "luz_vazada":
        x = np.linspace(0, 1, max(2, w // 8), dtype=np.float32)[None, :]
        y = np.linspace(0, 1, max(2, h // 8), dtype=np.float32)[:, None]
        cx, cy = .5 + .45 * math.sin(u * .9), .3 + .25 * math.cos(u * .7)
        m = np.exp(-(((x - cx) / .45) ** 2 + ((y - cy) / .55) ** 2)).astype(np.float32)
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)[..., None] * min(1.0, f) * .85
        cor = np.array([60, 140, 255], np.float32)  # laranja quente, em BGR
        base = q.astype(np.float32)
        return np.clip(255 - (255 - base) * (1 - m * cor / 255), 0, 255).astype(np.uint8)
    if tipo == "duotone":
        luz = cv2.cvtColor(q, cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None] / 255
        escuro, claro = np.array([90, 20, 40], np.float32), np.array([120, 210, 255], np.float32)
        d = escuro * (1 - luz) + claro * luz
        return cv2.addWeighted(q, 1 - min(1.0, f), d.astype(np.uint8), min(1.0, f), 0)
    if tipo == "contorno_neon":
        cinza = cv2.cvtColor(cv2.resize(q, (max(2, w // 2), max(2, h // 2))), cv2.COLOR_BGR2GRAY)
        bordas = cv2.Canny(cv2.GaussianBlur(cinza, (3, 3), 0), 60, 140)
        bordas = cv2.resize(cv2.dilate(bordas, np.ones((2, 2), np.uint8)), (w, h)).astype(np.float32) / 255
        matiz = (u * 40) % 180
        hsv = np.uint8([[[matiz, 220, 255]]]); cor = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0].astype(np.float32)
        brilho = cv2.GaussianBlur(bordas, (0, 0), 3) * 1.4
        escuro = q.astype(np.float32) * (1 - .7 * min(1.0, f))
        return np.clip(escuro + (np.maximum(bordas, brilho)[..., None] * cor) * min(1.0, f), 0, 255).astype(np.uint8)
    if tipo == "caleidoscopio":
        a = q[: (h + 1) // 2, : (w + 1) // 2]
        topo = np.concatenate([a, cv2.flip(a, 1)], axis=1)[:, :w]
        tudo = np.concatenate([topo, cv2.flip(topo, 0)], axis=0)[:h]
        return cv2.addWeighted(q, 1 - min(1.0, f), tudo, min(1.0, f), 0)
    if tipo == "meio_tom":
        celula = max(4, int(min(w, h) / (42 / max(.3, f))))
        gh, gw = max(1, h // celula), max(1, w // celula)
        media = cv2.resize(q, (gw, gh), interpolation=cv2.INTER_AREA)
        luz = cv2.cvtColor(media, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
        raio = (1 - luz) * .75 + .08
        rr = cv2.resize(raio, (gw * celula, gh * celula), interpolation=cv2.INTER_NEAREST)
        cor = cv2.resize(media, (gw * celula, gh * celula), interpolation=cv2.INTER_NEAREST)
        yy, xx = np.mgrid[0:gh * celula, 0:gw * celula].astype(np.float32)
        d = np.hypot((xx % celula) - celula / 2, (yy % celula) - celula / 2) / (celula / 2)
        ponto = (d < rr)[..., None]
        papel = np.full_like(cor, 238)
        saida = np.where(ponto, (cor * .85).astype(np.uint8), papel)
        return cv2.resize(saida, (w, h), interpolation=cv2.INTER_NEAREST)
    if tipo == "super8":
        rng = np.random.default_rng(n)
        dx, dy = rng.normal(0, w * .002 * f), rng.normal(0, h * .002 * f)
        s = cv2.warpAffine(q, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h), borderMode=cv2.BORDER_REFLECT)
        tab = np.arange(256, dtype=np.float32)
        lut = np.stack([np.clip(tab * .86 + 10, 0, 255), np.clip(tab * .98 + 6, 0, 255), np.clip(tab * 1.06 + 4, 0, 255)], axis=1).astype(np.uint8)[:, None, :]
        s = cv2.LUT(s, lut).astype(np.float32)
        s *= (1 - _vinheta_mascara(h, w) * .55 * min(1.0, f))[..., None]
        s *= 1 + .05 * f * math.sin(n * 1.7)
        s += _ruido(h, w, n, 14 * f)[..., None]
        return np.clip(s, 0, 255).astype(np.uint8)
    return None
