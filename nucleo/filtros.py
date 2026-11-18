"""Filtros de cor aplicados aos vídeos."""
from __future__ import annotations

FILTROS = {
    "nenhum": ("Original", "", "none"),
    "cinema": ("Cinema", "colorbalance=rs=-0.07:gs=-0.02:bs=0.08:rh=0.09:gh=0.02:bh=-0.08,eq=contrast=1.1:saturation=1.08", "contrast(1.1) saturate(1.08) sepia(.1)"),
    "vibrante": ("Vibrante", "eq=saturation=1.42:contrast=1.07", "saturate(1.42) contrast(1.07)"),
    "gamer": ("Gamer", "eq=saturation=1.58:contrast=1.15:brightness=0.01,colorbalance=rh=0.05:bh=0.11", "saturate(1.58) contrast(1.15) hue-rotate(-6deg)"),
    "quente": ("Quente", "colorbalance=rs=0.09:gs=0.02:bs=-0.09:rm=0.07:bm=-0.07,eq=saturation=1.1", "sepia(.22) saturate(1.2)"),
    "frio": ("Frio", "colorbalance=rs=-0.08:bs=0.1:rm=-0.06:bm=0.08,eq=saturation=0.96", "saturate(.95) hue-rotate(12deg) brightness(1.02)"),
    "por_do_sol": ("Pôr do sol", "colorbalance=rs=0.12:gs=-0.01:bs=-0.05:rh=0.1:gh=0.03:bh=-0.1,eq=contrast=1.06:saturation=1.22", "sepia(.32) saturate(1.45) contrast(1.06)"),
    "dramatico": ("Dramático", "eq=contrast=1.3:saturation=0.86:brightness=-0.03,vignette=PI/4.3", "contrast(1.3) saturate(.86) brightness(.94)"),
    "noir": ("Preto e branco", "hue=s=0,eq=contrast=1.24:brightness=-0.01", "grayscale(1) contrast(1.24)"),
    "vintage": ("Vintage", "curves=preset=vintage,eq=saturation=0.88", "sepia(.42) saturate(.88) contrast(.94)"),
    "desbotado": ("Desbotado", "curves=all='0/0.09 0.5/0.52 1/0.93',eq=saturation=0.82", "contrast(.84) saturate(.82) brightness(1.06)"),
    "vhs": ("Fita VHS", "chromashift=cbh=5:crh=-5,noise=alls=13:allf=t,eq=saturation=0.86:contrast=0.96", "saturate(.86) contrast(.96) blur(.5px)"),
    "sonho": ("Sonho", "split=2[sa][sb];[sb]gblur=sigma=14[sc];[sa][sc]blend=all_mode=screen:all_opacity=0.32", "brightness(1.1) saturate(1.1) contrast(.94)"),
}


def validar(nome) -> str | None:
    if nome in (None, "", "padrao"):
        return None
    if nome not in FILTROS:
        raise ValueError("Escolha um filtro válido.")
    return nome


def lista() -> list[dict]:
    return [{"id": k, "nome": v[0], "css": v[2]} for k, v in FILTROS.items()]


def cadeia(nome: str | None, intensidade: float = 100) -> str:
    """Trecho de filtro do FFmpeg, misturado com a imagem original conforme a intensidade."""
    if not nome or nome == "nenhum" or intensidade <= 0:
        return ""
    filtro = FILTROS[nome][1]
    if intensidade >= 100:
        return f"format=yuv420p,{filtro},format=yuv420p"
    return (f"format=yuv420p,split=2[fa][fb];[fb]{filtro},format=yuv420p[fc];"
            f"[fa][fc]blend=all_mode=normal:all_opacity={intensidade / 100:.2f},format=yuv420p")


# ------------------------------------------------------------ versão usada pelo estúdio, quadro a quadro

import cv2  # noqa: E402
import numpy as np  # noqa: E402

PARAMETROS = {
    "cinema": {"c": 1.1, "s": 1.08, "g": (1.03, 1.0, 0.95)}, "vibrante": {"c": 1.07, "s": 1.42}, "gamer": {"c": 1.15, "s": 1.58, "b": 0.01, "g": (1.02, 1.0, 1.06)},
    "quente": {"s": 1.1, "g": (1.09, 1.01, 0.9)}, "frio": {"s": 0.96, "g": (0.92, 1.0, 1.1)}, "por_do_sol": {"c": 1.06, "s": 1.22, "g": (1.12, 1.0, 0.92)},
    "dramatico": {"c": 1.3, "s": 0.86, "b": -0.03, "v": 0.45}, "noir": {"c": 1.24, "s": 0.0, "b": -0.01}, "vintage": {"c": 0.94, "s": 0.88, "sepia": 0.32},
    "desbotado": {"c": 0.84, "s": 0.82, "b": 0.05}, "vhs": {"c": 0.96, "s": 0.86, "ruido": 11, "croma": 5}, "sonho": {"c": 0.96, "s": 1.08, "brilho_suave": 0.32},
}
_tabelas: dict[str, np.ndarray] = {}
_vinhetas: dict[tuple, np.ndarray] = {}


def _tabela(nome: str, p: dict) -> np.ndarray:
    if nome not in _tabelas:
        v = np.arange(256, dtype=np.float32) / 255
        canais = [np.clip(((v * g - 0.5) * p.get("c", 1.0) + 0.5 + p.get("b", 0.0)) * 255, 0, 255) for g in reversed(p.get("g", (1, 1, 1)))]
        _tabelas[nome] = np.stack(canais, axis=1).astype(np.uint8)[:, None, :]
    return _tabelas[nome]


def vinheta(q: np.ndarray, forca: float) -> np.ndarray:
    h, w = q.shape[:2]
    chave = (w // 8, h // 8)
    if chave not in _vinhetas:
        x, y = np.linspace(-1, 1, chave[0])[None, :], np.linspace(-1, 1, chave[1])[:, None]
        _vinhetas[chave] = np.clip((np.sqrt(x ** 2 + y ** 2) - 0.55) / 0.85, 0, 1).astype(np.float32)
    m = cv2.resize(_vinhetas[chave], (w, h), interpolation=cv2.INTER_LINEAR)
    return (q * (1 - m * forca)[..., None]).astype(np.uint8)


def saturar(q: np.ndarray, s: float) -> np.ndarray:
    cinza = cv2.cvtColor(cv2.cvtColor(q, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
    return cinza if s <= 0 else cv2.addWeighted(q, s, cinza, 1 - s, 0)


def aplicar(q: np.ndarray, nome: str | None, forca: float = 100) -> np.ndarray:
    p = PARAMETROS.get(nome or "")
    if not p or forca <= 0 or q.size == 0:
        return q
    r = cv2.LUT(q, _tabela(nome, p))
    if p.get("s", 1.0) != 1.0:
        r = saturar(r, p["s"])
    if p.get("sepia"):
        m = np.array([[.131, .534, .272], [.168, .686, .349], [.189, .769, .393]], np.float32)
        r = cv2.addWeighted(r, 1 - p["sepia"], cv2.transform(r, m), p["sepia"], 0)
    if p.get("v"):
        r = vinheta(r, p["v"])
    if p.get("croma"):
        b, g, v = cv2.split(r)
        d = max(1, round(p["croma"] * q.shape[1] / 1080))
        r = cv2.merge([np.roll(b, d, axis=1), g, np.roll(v, -d, axis=1)])
    if p.get("brilho_suave"):
        pequeno = cv2.resize(r, (max(2, q.shape[1] // 8), max(2, q.shape[0] // 8)), interpolation=cv2.INTER_AREA)
        suave = cv2.resize(cv2.GaussianBlur(pequeno, (0, 0), 3), (q.shape[1], q.shape[0]))
        tela = 255 - cv2.multiply(255 - r, 255 - suave, scale=1 / 255)
        r = cv2.addWeighted(r, 1 - p["brilho_suave"], tela, p["brilho_suave"], 0)
    if p.get("ruido"):
        ruido = np.random.default_rng(int(q[0, 0, 0]) + q.shape[0]).normal(0, p["ruido"], q.shape[:2]).astype(np.float32)
        r = np.clip(r.astype(np.float32) + ruido[..., None], 0, 255).astype(np.uint8)
    return r if forca >= 100 else cv2.addWeighted(q, 1 - forca / 100, r, forca / 100, 0)


def ajustar(q: np.ndarray, a: dict | None) -> np.ndarray:
    """Brilho, contraste, saturação, temperatura e desfoque escolhidos à mão."""
    if not a or q.size == 0:
        return q
    if a.get("desfoque"):
        fator = max(1, int(a["desfoque"] / 6))
        p = cv2.resize(q, (max(2, q.shape[1] // fator), max(2, q.shape[0] // fator)), interpolation=cv2.INTER_AREA)
        q = cv2.resize(cv2.GaussianBlur(p, (0, 0), max(.5, a["desfoque"] / fator)), (q.shape[1], q.shape[0]))
    b, c, t = a.get("brilho", 0) / 100, 1 + a.get("contraste", 0) / 100, a.get("temperatura", 0) / 100
    if b or c != 1 or t:
        v = np.arange(256, dtype=np.float32) / 255
        tab = [np.clip(((v * g - .5) * c + .5 + b) * 255, 0, 255) for g in (1 - t * .15, 1.0, 1 + t * .15)]
        q = cv2.LUT(q, np.stack(tab, axis=1).astype(np.uint8)[:, None, :])
    if a.get("saturacao"):
        q = saturar(q, max(0, 1 + a["saturacao"] / 100))
    return q
