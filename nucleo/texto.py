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
    "destaque_escala": 100, "sublinhado": False, "sublinhado_cor": "#FF3B30", "sublinhado_esp": 8,
    "relevo": 0, "relevo_cor": "#1E1E1E", "sem_pontuacao": False,
}
EFEITOS_PIXEL = ("neon", "brilho", "reflexo", "ouro", "fogo", "gelo", "arcoiris", "glitch", "rgb", "onda",
                 "cromado", "por_do_sol", "doce", "holografico")
ANIMACOES = ("nenhuma", "fade", "pop", "zoom", "subir", "descer", "esquerda", "direita", "quique", "digitando",
             "desfocar", "carimbo", "cair", "girar", "piscar", "glitch", "esticar", "encolher")
# Regras de destaque por palavra (como nos packs de texto): quais palavras ganham a cor de destaque.
REGRAS_DESTAQUE = ("nenhum", "palavra", "importantes", "ambos", "falado", "primeira", "ultima", "alternadas")
PONTUACAO = re.compile(r"[.,;:!?…\"“”()¿¡]+")
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


def acento(est: dict, k: int, q: str, total: int, ativa: int | None, original: str = "") -> bool:
    """A palavra `k` recebe a cor de destaque? `ativa` é a palavra sendo falada."""
    modo = est.get("destaque", "nenhum")
    if modo in ("palavra", "ambos") and k == ativa:
        return True
    if modo in ("importantes", "ambos") and importante(original or q):
        return True
    if modo == "falado":
        return ativa is not None and k <= ativa
    if modo == "primeira":
        return k == 0
    if modo == "ultima":
        return k == total - 1
    if modo == "alternadas":
        return k % 2 == 1
    return False


def desenhar(texto: str, est: dict, escala: float = 1.0, ativa: int | None = None) -> np.ndarray:
    """Devolve o texto em RGBA, sem fundo. `ativa` é a palavra sendo falada."""
    est = {**ESTILO_PADRAO, **est}
    chave = (texto, escala, ativa, tuple(sorted((k, str(v)) for k, v in est.items() if k not in ("x", "y", "entrada", "saida", "tempo_anim"))))
    if chave in _sprites:
        _sprites.move_to_end(chave)
        return _sprites[chave]
    s = est["tamanho"] * escala
    f = _fonte(est["fonte"], max(4, round(s)))
    k_esc = max(.5, min(2.0, float(est.get("destaque_escala", 100)) / 100))
    f_acento = _fonte(est["fonte"], max(4, round(s * k_esc))) if abs(k_esc - 1) > .01 else f
    esp = est["espacamento"] * escala
    limite = est["largura"] * escala
    vazio = _largura(f, " ", esp)
    blocos = []
    for bloco in str(texto).split("\n"):
        itens = []
        for p in bloco.split():
            q = p.upper() if est["maiusculas"] else p
            if est.get("sem_pontuacao"):
                q = PONTUACAO.sub("", q) or q
            itens.append((q, p))
        blocos.append(itens)
    total = sum(len(b) for b in blocos)
    linhas: list[list[tuple[str, int, bool]]] = []
    n = 0
    for itens in blocos:
        atual: list[tuple[str, int, bool]] = []
        usado = 0.0
        for q, original in itens:
            ac = acento(est, n, q, total, ativa, original)
            w = _largura(f_acento if ac else f, q, esp)
            if atual and usado + vazio + w > limite:
                linhas.append(atual); atual, usado = [], 0.0
            usado += (vazio if atual else 0) + w
            atual.append((q, n, ac)); n += 1
        linhas.append(atual)
    subida, descida = f.getmetrics()
    sobe_a = f_acento.getmetrics()[0] - subida if f_acento is not f else 0
    passo = s * est["entrelinha"] / 100 + max(0, sobe_a)
    alt_texto = (subida + descida) + passo * max(0, len(linhas) - 1) + max(0, sobe_a)
    larg = lambda q, ac: _largura(f_acento if ac else f, q, esp)
    larguras = [sum(larg(q, ac) for q, _, ac in l) + vazio * max(0, len(l) - 1) for l in linhas]
    lar_texto = max(larguras, default=1)
    pad = est["fundo_pad"] * escala if est["fundo"] else 0
    cont = est["contorno"] * escala
    relevo = max(0.0, float(est.get("relevo", 0))) * escala
    sub_esp = float(est.get("sublinhado_esp", 8)) * escala if est.get("sublinhado") else 0
    folga = int(pad + cont + est["borda"] * escala + relevo + sub_esp * 2 + (abs(est["sombra_x"]) + abs(est["sombra_y"]) + est["sombra_blur"] * 2.5) * escala * bool(est["sombra"])) + 6
    W, H = int(lar_texto + 2 * folga) + 2, int(alt_texto + 2 * folga) + 2
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mascara = Image.new("L", (W, H), 0)
    tinta = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dm, dt = ImageDraw.Draw(mascara), ImageDraw.Draw(tinta)

    def escrever(x: float, y: float, q: str, preenchimento, traco: int, fonte) -> None:
        for alvo, c in ((dm, 255), (dt, preenchimento)):
            if esp == 0:
                alvo.text((x, y), q, font=fonte, fill=c, stroke_width=traco, stroke_fill=(c if alvo is dm else cor(est["contorno_cor"])))
            else:
                px = x
                for ch in q:
                    alvo.text((px, y), ch, font=fonte, fill=c, stroke_width=traco, stroke_fill=(c if alvo is dm else cor(est["contorno_cor"])))
                    px += fonte.getlength(ch) + esp

    posicoes = []
    for i, l in enumerate(linhas):
        x = folga + {"esquerda": 0, "direita": lar_texto - larguras[i]}.get(est["alinhamento"], (lar_texto - larguras[i]) / 2)
        y = folga + passo * i + max(0, sobe_a)
        for q, k, ac in l:
            posicoes.append((x, y, q, k, ac))
            x += larg(q, ac) + vazio
    if est["destaque_caixa"] and ativa is not None:
        for x, y, q, k, ac in posicoes:
            if k == ativa:
                folga_c = s * 0.14
                dt.rounded_rectangle((x - folga_c, y + s * .08, x + larg(q, ac) + folga_c, y + subida + descida - s * .02), radius=s * .16, fill=cor(est["cor_destaque"]))
    for x, y, q, k, ac in posicoes:
        c = cor(est["cor"])
        if ac:
            c = (20, 20, 20, 255) if (est["destaque_caixa"] and k == ativa) else cor(est["cor_destaque"])
        fonte = f_acento if ac else f
        dy = -(fonte.getmetrics()[0] - subida) if fonte is not f else 0
        escrever(x, y + dy, q, c, 0 if (est["destaque_caixa"] and k == ativa) else round(cont), fonte)
    if sub_esp:
        for i, l in enumerate(linhas):
            itens_l = [pz for pz in posicoes if pz[3] in {k for _, k, _ in l}]
            if not itens_l:
                continue
            x0 = itens_l[0][0]; x1 = itens_l[-1][0] + larg(itens_l[-1][2], itens_l[-1][4])
            y0 = itens_l[0][1] + subida + sub_esp * .6
            for alvo, c in ((dm, 255), (dt, cor(est.get("sublinhado_cor", "#FF3B30")))):
                alvo.rounded_rectangle((x0, y0, x1, y0 + sub_esp), radius=sub_esp / 2, fill=c)
    if est["fundo"]:
        caixa = (folga - pad, folga - pad, folga + lar_texto + pad, folga + alt_texto + pad)
        ImageDraw.Draw(base).rounded_rectangle(caixa, radius=est["fundo_raio"] * escala, fill=cor(est["fundo_cor"], est["fundo_opac"] * 2.55),
                                               outline=cor(est["borda_cor"]) if est["borda"] else None, width=round(est["borda"] * escala))
    if est["sombra"]:
        origem = Image.new("L", (W, H), 0)
        origem.paste(mascara, (round(est["sombra_x"] * escala + relevo * .7), round(est["sombra_y"] * escala + relevo * .7)))
        if est["sombra_blur"]:
            origem = origem.filter(ImageFilter.GaussianBlur(est["sombra_blur"] * escala))
        sombra = Image.new("RGBA", (W, H), cor(est["sombra_cor"]))
        sombra.putalpha(origem.point(lambda v: int(v * est["sombra_opac"] / 100)))
        base = Image.alpha_composite(base, sombra)
    if relevo >= 1:  # letras em 3D: camadas da cor do relevo empurradas na diagonal, escurecendo
        passos = int(min(24, max(2, relevo)))
        r0, g0, b0, _ = cor(est.get("relevo_cor", "#1E1E1E"))
        for n_p in range(passos, 0, -1):
            d = relevo * n_p / passos
            escurece = 1 - .45 * n_p / passos
            camada = Image.new("RGBA", (W, H), (int(r0 * escurece), int(g0 * escurece), int(b0 * escurece), 255))
            sombra_m = Image.new("L", (W, H), 0)
            sombra_m.paste(mascara, (round(d * .7), round(d * .7)))
            camada.putalpha(sombra_m)
            base = Image.alpha_composite(base, camada)
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
    elif tipo == "respirar":
        r["escala"] = 1 + .04 * f * math.sin(u * math.tau * .45)
        r["alfa"] = 1 - .12 * min(1.0, f) * (.5 - .5 * math.cos(u * math.tau * .45))
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
    if tipo == "cromado":
        tinta = _degrade(h, w, [(.0, (250, 252, 255)), (.42, (205, 215, 230)), (.5, (70, 80, 100)), (.62, (150, 160, 180)), (1.0, (245, 248, 255))])
        return _halo(_pintar(spr, tinta), (180, 200, 230), t * .06, .35 * f)
    if tipo == "por_do_sol":
        return _halo(_pintar(spr, _degrade(h, w, [(.2, (255, 214, 90)), (.55, (255, 110, 80)), (.85, (180, 50, 140))])), (255, 120, 80), t * .1, .4 * f)
    if tipo == "doce":
        return _pintar(spr, _degrade(h, w, [(.2, (255, 150, 220)), (.55, (255, 110, 199)), (.85, (120, 200, 255))]))
    if tipo == "holografico":
        x = np.arange(w, dtype=np.float32)[None, :]; y = np.arange(h, dtype=np.float32)[:, None]
        matiz = (((x + y * .6) / max(1, w) * .8 + u * .15) % 1 * 179).astype(np.uint8)
        hsv = np.dstack([matiz, np.full_like(matiz, 95), np.full_like(matiz, 255)])
        return _halo(_pintar(spr, cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB).astype(np.float32)), (255, 255, 255), t * .12, .6 * f)
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
    r = {"alfa": 1.0, "dx": 0.0, "dy": 0.0, "escala": 1.0, "mostrar": 1.0, "rot": 0.0, "sx": 1.0, "sy": 1.0, "desfoque": 0.0, "glitch": 0.0}
    tempo = max(0.01, float(est["tempo_anim"]))
    t = float(est.get("tamanho", 66))
    for lado, tipo, p in ((1, est["entrada"], min(1.0, u / tempo)), (-1, est["saida"], min(1.0, (dur - u) / tempo))):
        if p >= 1 or tipo == "nenhuma":
            continue
        p = max(0.0, p)
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
        elif tipo == "desfocar":
            r["desfoque"] = max(r["desfoque"], (1 - e) * t * .35); r["alfa"] *= min(1, p * 1.6); r["escala"] *= 1.08 - .08 * e
        elif tipo == "carimbo":  # cai de grande e bate na tela
            q = p * p
            r["escala"] *= 2.2 - 1.2 * q + (.06 * np.sin(min(1.0, (p - .8) / .2) * np.pi) if p > .8 else 0); r["alfa"] *= min(1, p * 2.5)
        elif tipo == "cair":
            quica = abs(np.cos(p * np.pi * 1.5)) * (1 - p) ** 1.6
            r["dy"] -= quica * t * 2.4 * lado; r["alfa"] *= min(1, p * 4)
        elif tipo == "girar":
            r["rot"] += (1 - e) * -200 * lado; r["escala"] *= .3 + .7 * e; r["alfa"] *= min(1, p * 2)
        elif tipo == "piscar":
            r["alfa"] *= 0.0 if (p < .85 and int(p * 14) % 2 == 0) else min(1.0, .4 + p)
        elif tipo == "glitch":
            r["glitch"] = max(r["glitch"], 1 - p); r["dx"] += np.sin(p * 91) * t * .25 * (1 - p); r["alfa"] *= min(1, .3 + p)
        elif tipo == "esticar":
            r["sx"] *= .6 + .4 * e + np.sin(p * np.pi) * .15; r["sy"] *= 1.5 - .5 * e - np.sin(p * np.pi) * .1; r["alfa"] *= min(1, p * 2)
        elif tipo == "encolher":
            r["escala"] *= e; r["alfa"] *= min(1, p * 1.5)
    return r


def desfocar_rgba(spr: np.ndarray, raio: float) -> np.ndarray:
    """Desfoque com alfa pré-multiplicado, para não escurecer as bordas das letras."""
    if raio < .5:
        return spr
    m = int(raio * 2) + 2
    spr = cv2.copyMakeBorder(spr, m, m, m, m, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
    a = spr[..., 3:4].astype(np.float32) / 255
    cor_p = spr[..., :3].astype(np.float32) * a
    cor_p = cv2.GaussianBlur(cor_p, (0, 0), raio)
    a2 = cv2.GaussianBlur(a[..., 0], (0, 0), raio)[..., None]
    rgb = cor_p / np.maximum(a2, 1e-4)
    return np.dstack([np.clip(rgb, 0, 255), np.clip(a2 * 255, 0, 255)]).astype(np.uint8)


def glitch_rgba(spr: np.ndarray, forca: float, semente: int, tamanho: float) -> np.ndarray:
    if forca <= .02:
        return spr
    saida = _separar(spr, int(tamanho * .08 * forca))
    rng = np.random.default_rng(semente)
    h = saida.shape[0]
    for _ in range(4):
        y0 = int(rng.integers(0, max(1, h - 2))); alt = int(rng.integers(2, max(3, int(tamanho * .3))))
        saida[y0:y0 + alt] = np.roll(saida[y0:y0 + alt], int(rng.integers(-int(tamanho * .35 * forca) - 1, int(tamanho * .35 * forca) + 2)), axis=1)
    return saida
