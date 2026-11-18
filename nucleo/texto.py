"""Desenha textos e legendas com controle total de estilo. A exportação e a prévia exata usam este mesmo código."""
from __future__ import annotations

import math
import re
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .contexto import FORTES

PASTA_FONTES = Path(__file__).resolve().parent.parent / "fontes"
FONTE_PADRAO = "Poppins-Bold"
ESTILO_PADRAO = {
    "fonte": FONTE_PADRAO, "tamanho": 66, "cor": "#FFFFFF", "opacidade": 100, "maiusculas": False, "alinhamento": "centro", "ancora": "centro",
    "espacamento": 0, "entrelinha": 115, "largura": 900, "contorno": 0, "contorno_cor": "#000000",
    "sombra": False, "sombra_cor": "#000000", "sombra_opac": 60, "sombra_x": 0, "sombra_y": 4, "sombra_blur": 8,
    "fundo": False, "fundo_cor": "#000000", "fundo_opac": 75, "fundo_raio": 14, "fundo_pad": 18, "borda": 0, "borda_cor": "#FFFFFF",
    "destaque": "nenhum", "cor_destaque": "#FFC933", "destaque_caixa": False, "palavra_a_palavra": False,
    "entrada": "nenhuma", "saida": "nenhuma", "tempo_anim": 0.15, "efeito_texto": "nenhum", "efeito_forca": 100,
}
EFEITOS_PIXEL = ("neon", "brilho", "reflexo", "ouro", "fogo", "gelo", "arcoiris", "glitch", "rgb", "onda")
ANIMACOES = ("nenhuma", "fade", "pop", "zoom", "subir", "descer", "esquerda", "direita", "quique", "digitando")
_extras: list[Path] = []
_fontes: dict[tuple, ImageFont.FreeTypeFont] = {}
_sprites: OrderedDict = OrderedDict()


def usar_pasta_extra(pasta: Path) -> None:
    if pasta not in _extras:
        _extras.append(pasta)


def catalogo() -> list[dict]:
    achadas = {}
    for pasta in (PASTA_FONTES, *_extras):
        for arq in sorted([*pasta.glob("*.ttf"), *pasta.glob("*.otf")]):
            achadas[arq.stem] = {"id": arq.stem, "nome": arq.stem.replace("-", " "), "url": f"/fontes/{arq.name}"}
    return sorted(achadas.values(), key=lambda f: f["nome"])


def caminho_fonte(nome: str) -> Path:
    for pasta in (*_extras, PASTA_FONTES):
        for ext in (".ttf", ".otf"):
            if re.fullmatch(r"[\w .-]+", nome or "") and (pasta / f"{nome}{ext}").exists():
                return pasta / f"{nome}{ext}"
    return PASTA_FONTES / f"{FONTE_PADRAO}.ttf"


def _fonte(nome: str, tamanho: int) -> ImageFont.FreeTypeFont:
    chave = (nome, tamanho)
    if chave not in _fontes:
        if len(_fontes) > 80:
            _fontes.clear()
        _fontes[chave] = ImageFont.truetype(str(caminho_fonte(nome)), tamanho)
    return _fontes[chave]


def cor(hexa: str, alfa: float = 255) -> tuple[int, int, int, int]:
    h = str(hexa or "#FFFFFF").lstrip("#")
    h = "".join(c * 2 for c in h) if len(h) == 3 else h.ljust(6, "0")
    try:
        return int(h[:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(alfa)
    except ValueError:
        return 255, 255, 255, int(alfa)


def importante(palavra: str) -> bool:
    return bool(FORTES.search(palavra)) or palavra[-1:] in "!?"


def _largura(f, texto: str, esp: float) -> float:
    return f.getlength(texto) + esp * max(0, len(texto) - 1)


def desenhar(texto: str, est: dict, escala: float = 1.0, ativa: int | None = None) -> np.ndarray:
    """Devolve o texto em RGBA, sem fundo. `ativa` é a palavra sendo falada."""
    chave = (texto, escala, ativa, tuple(sorted((k, str(v)) for k, v in est.items() if k not in ("x", "y", "entrada", "saida", "tempo_anim"))))
    if chave in _sprites:
        _sprites.move_to_end(chave)
        return _sprites[chave]
    s = est["tamanho"] * escala
    f = _fonte(est["fonte"], max(4, round(s)))
    esp = est["espacamento"] * escala
    limite = est["largura"] * escala
    vazio = _largura(f, " ", esp)
    linhas: list[list[tuple[str, int]]] = []
    n = 0
    for bloco in str(texto).split("\n"):
        atual: list[tuple[str, int]] = []
        usado = 0.0
        for p in bloco.split():
            q = p.upper() if est["maiusculas"] else p
            w = _largura(f, q, esp)
            if atual and usado + vazio + w > limite:
                linhas.append(atual); atual, usado = [], 0.0
            usado += (vazio if atual else 0) + w
            atual.append((q, n)); n += 1
        linhas.append(atual)
    subida, descida = f.getmetrics()
    passo = s * est["entrelinha"] / 100
    alt_texto = (subida + descida) + passo * max(0, len(linhas) - 1)
    larguras = [sum(_largura(f, q, esp) for q, _ in l) + vazio * max(0, len(l) - 1) for l in linhas]
    lar_texto = max(larguras, default=1)
    pad = est["fundo_pad"] * escala if est["fundo"] else 0
    cont = est["contorno"] * escala
    folga = int(pad + cont + est["borda"] * escala + (abs(est["sombra_x"]) + abs(est["sombra_y"]) + est["sombra_blur"] * 2.5) * escala * bool(est["sombra"])) + 6
    W, H = int(lar_texto + 2 * folga) + 2, int(alt_texto + 2 * folga) + 2
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mascara = Image.new("L", (W, H), 0)
    tinta = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dm, dt = ImageDraw.Draw(mascara), ImageDraw.Draw(tinta)

    def escrever(x: float, y: float, q: str, preenchimento, traco: int) -> None:
        for alvo, c in ((dm, 255), (dt, preenchimento)):
            if esp == 0:
                alvo.text((x, y), q, font=f, fill=c, stroke_width=traco, stroke_fill=(c if alvo is dm else cor(est["contorno_cor"])))
            else:
                px = x
                for ch in q:
                    alvo.text((px, y), ch, font=f, fill=c, stroke_width=traco, stroke_fill=(c if alvo is dm else cor(est["contorno_cor"])))
                    px += f.getlength(ch) + esp

    posicoes = []
    for i, l in enumerate(linhas):
        x = folga + {"esquerda": 0, "direita": lar_texto - larguras[i]}.get(est["alinhamento"], (lar_texto - larguras[i]) / 2)
        y = folga + passo * i
        for q, k in l:
            posicoes.append((x, y, q, k))
            x += _largura(f, q, esp) + vazio
    if est["destaque_caixa"] and ativa is not None:
        for x, y, q, k in posicoes:
            if k == ativa:
                folga_c = s * 0.14
                dt.rounded_rectangle((x - folga_c, y + s * .08, x + _largura(f, q, esp) + folga_c, y + subida + descida - s * .02), radius=s * .16, fill=cor(est["cor_destaque"]))
    for x, y, q, k in posicoes:
        modo, c = est["destaque"], cor(est["cor"])
        if modo in ("palavra", "ambos") and k == ativa:
            c = (20, 20, 20, 255) if est["destaque_caixa"] else cor(est["cor_destaque"])
        elif modo in ("importantes", "ambos") and importante(q):
            c = cor(est["cor_destaque"])
        escrever(x, y, q, c, 0 if (est["destaque_caixa"] and k == ativa) else round(cont))
    if est["fundo"]:
        caixa = (folga - pad, folga - pad, folga + lar_texto + pad, folga + alt_texto + pad)
        ImageDraw.Draw(base).rounded_rectangle(caixa, radius=est["fundo_raio"] * escala, fill=cor(est["fundo_cor"], est["fundo_opac"] * 2.55),
                                               outline=cor(est["borda_cor"]) if est["borda"] else None, width=round(est["borda"] * escala))
    if est["sombra"]:
        origem = Image.new("L", (W, H), 0)
        origem.paste(mascara, (round(est["sombra_x"] * escala), round(est["sombra_y"] * escala)))
        if est["sombra_blur"]:
            origem = origem.filter(ImageFilter.GaussianBlur(est["sombra_blur"] * escala))
        sombra = Image.new("RGBA", (W, H), cor(est["sombra_cor"]))
        sombra.putalpha(origem.point(lambda v: int(v * est["sombra_opac"] / 100)))
        base = Image.alpha_composite(base, sombra)
    saida = np.array(Image.alpha_composite(base, tinta))
    saida.setflags(write=False)
    _sprites[chave] = saida
    if len(_sprites) > 400:
        _sprites.popitem(last=False)
    return saida


def efeito_movimento(est: dict, u: float, escala: float = 1.0) -> dict:
    """Movimento contínuo do texto enquanto ele está na tela."""
    r = {"dx": 0.0, "dy": 0.0, "escala": 1.0, "rot": 0.0, "alfa": 1.0}
    tipo, f = est.get("efeito_texto", "nenhum"), float(est.get("efeito_forca", 100)) / 100
    t = float(est.get("tamanho", 66))
    if tipo == "pulsar":
        r["escala"] = 1 + .07 * f * math.sin(u * math.tau * 1.6)
    elif tipo == "batida":
        fase = (u * 1.5) % 1
        r["escala"] = 1 + .16 * f * (math.exp(-fase * 9) + .55 * math.exp(-max(0, fase - .24) * 11) * (fase > .24))
    elif tipo == "tremer":
        n = int(u * 24)
        r["dx"], r["dy"] = t * .05 * f * math.sin(n * 12.9898), t * .05 * f * math.sin(n * 78.233)
    elif tipo == "balancar":
        r["rot"] = 5 * f * math.sin(u * math.tau * .9)
    elif tipo == "flutuar":
        r["dy"] = t * .14 * f * math.sin(u * math.tau * .7)
    elif tipo == "piscar":
        r["alfa"] = 1 - min(1.0, f) * .75 * (math.sin(u * math.tau * 3) < -.2)
    return r


def _halo(spr: np.ndarray, rgb: tuple, raio: float, forca: float) -> np.ndarray:
    a = spr[..., 3].astype(np.float32) / 255
    h = cv2.GaussianBlur(a, (0, 0), max(.8, raio))
    h = np.clip(h * forca, 0, 1)
    saida_a = a + h * (1 - a)
    base = np.dstack([np.full(a.shape, c, np.float32) for c in rgb[:3]])
    cor_final = (spr[..., :3].astype(np.float32) * a[..., None] + base * (h * (1 - a))[..., None]) / np.maximum(saida_a[..., None], 1e-4)
    return np.dstack([np.clip(cor_final, 0, 255), saida_a * 255]).astype(np.uint8)


def _pintar(spr: np.ndarray, tinta: np.ndarray) -> np.ndarray:
    """Troca a cor das letras e mantém o contorno escuro."""
    luz = spr[..., :3].astype(np.float32).max(axis=2, keepdims=True) / 255
    saida = spr.copy()
    saida[..., :3] = np.clip(tinta * luz, 0, 255).astype(np.uint8)
    return saida


def _degrade(h: int, w: int, paradas: list) -> np.ndarray:
    pos = np.linspace(0, 1, h)
    xs = [p[0] for p in paradas]
    linhas = np.stack([np.interp(pos, xs, [p[1][c] for p in paradas]) for c in range(3)], axis=1).astype(np.float32)
    return np.repeat(linhas[:, None, :], w, axis=1)


def _separar(spr: np.ndarray, d: int) -> np.ndarray:
    if d < 1:
        return spr
    a = spr[..., 3].astype(np.float32) / 255
    r = np.roll(spr[..., 0] * a, d, axis=1); g = spr[..., 1] * a; b = np.roll(spr[..., 2] * a, -d, axis=1)
    alfa = np.maximum.reduce([a, np.roll(a, d, axis=1), np.roll(a, -d, axis=1)])
    cores = np.dstack([r, g, b]) / np.maximum(alfa[..., None], 1e-4)
    return np.dstack([np.clip(cores, 0, 255), alfa * 255]).astype(np.uint8)


def efeito_pixels(spr: np.ndarray, est: dict, u: float, escala: float = 1.0) -> np.ndarray:
    """Aplica o efeito visual escolhido sobre as letras já desenhadas."""
    tipo, f = est.get("efeito_texto", "nenhum"), float(est.get("efeito_forca", 100)) / 100
    if tipo not in EFEITOS_PIXEL or f <= 0:
        return spr
    t = float(est.get("tamanho", 66)) * escala
    m = max(4, int(t * .5))
    spr = cv2.copyMakeBorder(spr, m, m, m, m, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
    h, w = spr.shape[:2]
    if tipo == "neon":
        return _halo(_halo(spr, cor(est["cor_destaque"]), t * .07, 1.5 * f), cor(est["cor_destaque"]), t * .2, (.85 + .25 * math.sin(u * 9)) * f)
    if tipo == "brilho":
        return _halo(spr, cor(est["cor"]), t * .16, 1.2 * f)
    if tipo == "reflexo":
        x = np.arange(w, dtype=np.float32)
        centro = ((u % 1.7) / 1.1) * (w * 1.4) - w * .2
        banda = np.exp(-((x - centro) / max(4.0, t * .35)) ** 2) * min(1.0, f) * .9
        saida = spr.astype(np.float32)
        saida[..., :3] += (255 - saida[..., :3]) * banda[None, :, None]
        return saida.astype(np.uint8)
    if tipo == "ouro":
        return _halo(_pintar(spr, _degrade(h, w, [(.2, (255, 247, 190)), (.5, (245, 190, 70)), (.8, (168, 102, 15))])), (245, 170, 40), t * .1, .55 * f)
    if tipo == "gelo":
        return _halo(_pintar(spr, _degrade(h, w, [(.25, (255, 255, 255)), (.75, (110, 215, 255))])), (90, 200, 255), t * .13, .9 * f)
    if tipo == "fogo":
        tinta = _degrade(h, w, [(.25, (255, 60, 20)), (.55, (255, 150, 25)), (.8, (255, 235, 120))])
        return _halo(_pintar(spr, tinta), (255, 90, 15), t * (.15 + .03 * math.sin(u * 17)), (1 + .25 * math.sin(u * 23)) * f)
    if tipo == "arcoiris":
        matiz = ((np.arange(w) / max(1, w) * 1.2 + u * .45) % 1 * 179).astype(np.uint8)
        hsv = np.stack([matiz, np.full(w, 225, np.uint8), np.full(w, 255, np.uint8)], axis=1)[None, ...]
        linha = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(np.float32)
        return _pintar(spr, np.repeat(linha, h, axis=0))
    if tipo == "rgb":
        return _separar(spr, int(t * .06 * f * (1 + .45 * math.sin(u * 8))))
    if tipo == "glitch":
        rng = np.random.default_rng(int(u * 14))
        saida = _separar(spr, int(t * .05 * f))
        if rng.random() < .55:
            for _ in range(5):
                y0 = int(rng.integers(0, max(1, h - 2))); alt = int(rng.integers(2, max(3, int(t * .28))))
                saida[y0:y0 + alt] = np.roll(saida[y0:y0 + alt], int(rng.integers(-int(t * .3 * f) - 1, int(t * .3 * f) + 2)), axis=1)
        return saida
    if tipo == "onda":
        xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
        ys = ys + np.sin(xs / max(6.0, t * 1.1) - u * 6) * t * .13 * f
        return cv2.remap(spr, xs, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return spr


def animar(est: dict, u: float, dur: float) -> dict:
    """Quanto da animação de entrada e de saída vale neste instante."""
    r = {"alfa": 1.0, "dx": 0.0, "dy": 0.0, "escala": 1.0, "mostrar": 1.0}
    tempo = max(0.01, float(est["tempo_anim"]))
    for tipo, p in ((est["entrada"], min(1.0, u / tempo)), (est["saida"], min(1.0, (dur - u) / tempo))):
        if p >= 1 or tipo == "nenhuma":
            continue
        e = 1 - (1 - p) ** 3
        if tipo == "fade":
            r["alfa"] *= p
        elif tipo == "pop":
            r["escala"] *= 0.7 + 0.3 * (e + np.sin(p * np.pi) * .12); r["alfa"] *= min(1, p * 2)
        elif tipo == "zoom":
            r["escala"] *= 1.5 - .5 * e; r["alfa"] *= p
        elif tipo == "subir":
            r["dy"] += (1 - e) * 60; r["alfa"] *= p
        elif tipo == "descer":
            r["dy"] -= (1 - e) * 60; r["alfa"] *= p
        elif tipo == "esquerda":
            r["dx"] += (1 - e) * 90; r["alfa"] *= p
        elif tipo == "direita":
            r["dx"] -= (1 - e) * 90; r["alfa"] *= p
        elif tipo == "quique":
            r["escala"] *= 1 + np.sin(p * np.pi * 2.5) * (1 - p) * .35; r["alfa"] *= min(1, p * 3)
        elif tipo == "digitando":
            r["mostrar"] = min(r["mostrar"], p)
    return r
