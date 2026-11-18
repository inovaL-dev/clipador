"""Monta cada quadro do projeto. A prévia exata e a exportação passam por aqui, então mostram o mesmo resultado."""
from __future__ import annotations

import bisect
import math
import os
import subprocess
import tempfile
import time
import wave
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from . import filtros, texto, transicoes
from .plataformas import sem_janela

TAXA = 48000
PADRAO_T = {"x": 0.0, "y": 0.0, "w": 100.0, "h": 100.0, "escala": 1.0, "rot": 0.0, "opac": 100.0, "zoom": 1.0, "zx": 0.5, "zy": 0.5,
            "cl": 0.0, "ct": 0.0, "cr": 0.0, "cb": 0.0}
_quadros_soltos: OrderedDict = OrderedDict()


def suave(p: float) -> float:
    return p * p * (3 - 2 * p)


def valor(item: dict, prop: str, u: float) -> float:
    """Valor da propriedade neste instante, seguindo os keyframes."""
    base = (item.get("t") or {}).get(prop, PADRAO_T.get(prop, 0.0))
    chaves = (item.get("kf") or {}).get(prop)
    if not chaves:
        return float(base)
    if u <= chaves[0]["t"]:
        return float(chaves[0]["v"])
    for a, b in zip(chaves, chaves[1:]):
        if u < b["t"]:
            p = (u - a["t"]) / max(1e-6, b["t"] - a["t"])
            modo = a.get("e", "linear")
            p = 0.0 if modo == "degrau" else suave(p) if modo == "suave" else p
            return float(a["v"] + (b["v"] - a["v"]) * p)
    return float(chaves[-1]["v"])


def estilo_de(proj: dict, item: dict) -> dict:
    if item["tipo"] == "legenda":
        return {**texto.ESTILO_PADRAO, **proj["global"].get("legenda", {}), **(item.get("estilo") or {})}
    return {**texto.ESTILO_PADRAO, **(item.get("estilo") or {})}


class Midias:
    """Encontra os arquivos do projeto sem deixar sair das pastas do programa."""

    def __init__(self, saida: Path, dados: Path, biblioteca):
        self.saida, self.dados, self.biblioteca = Path(saida).resolve(), Path(dados).resolve(), biblioteca

    def caminho(self, midia: dict) -> Path:
        raiz, rel = midia.get("raiz"), str(midia.get("rel", ""))
        if raiz == "som":
            return self.biblioteca.caminho(rel)
        base = {"saida": self.saida, "dados": self.dados}.get(raiz)
        if base is None:
            raise ValueError("Arquivo inválido no projeto.")
        alvo = (base / rel).resolve()
        if base not in alvo.parents:
            raise ValueError("Arquivo inválido no projeto.")
        return alvo


class _Cabeca:
    def __init__(self, caminho: Path, indice: int, fps: int):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(caminho)],
                           capture_output=True, text=True, **sem_janela()).stdout.strip().split(",")
        self.w, self.h = int(r[0]), int(r[1])
        self.tam = self.w * self.h * 3
        self.pos, self.ult = indice - 1, None
        self.proc = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{indice / fps:.3f}", "-i", str(caminho), "-an", "-vf", f"fps={fps}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self.tam * 2, **sem_janela())

    def ir(self, indice: int) -> np.ndarray | None:
        while self.pos < indice:
            dados = self.proc.stdout.read(self.tam)
            if len(dados) < self.tam:
                self.pos = indice
                break
            self.pos += 1
            if self.pos >= indice:
                self.ult = np.frombuffer(dados, np.uint8).reshape(self.h, self.w, 3)
        return self.ult

    def fechar(self) -> None:
        self.proc.kill(); self.proc.wait(); self.proc.stdout.close()


class Leitor:
    def __init__(self, caminho: Path, fps: int):
        self.caminho, self.fps, self.cabecas = caminho, fps, []

    def quadro(self, t: float) -> np.ndarray | None:
        alvo = max(0, round(t * self.fps))
        cabeca = next((c for c in self.cabecas if c.pos == alvo), None) or next((c for c in self.cabecas if c.pos < alvo <= c.pos + 75), None)
        if cabeca is None:
            if len(self.cabecas) >= 3:
                self.cabecas.pop(0).fechar()
            cabeca = _Cabeca(self.caminho, alvo, self.fps)
            self.cabecas.append(cabeca)
        return cabeca.ir(alvo)

    def fechar(self) -> None:
        for c in self.cabecas:
            c.fechar()
        self.cabecas = []


def quadro_solto(caminho: Path, t: float, fps: int) -> np.ndarray | None:
    """Um único quadro, para a prévia. Guarda os últimos para arrastar elementos sem esperar."""
    chave = (str(caminho), round(t * fps))
    if chave in _quadros_soltos:
        _quadros_soltos.move_to_end(chave)
        return _quadros_soltos[chave]
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(caminho), "-an", "-frames:v", "1", "-vf", "scale='min(1920,iw)':-2", "-f", "image2pipe", "-c:v", "bmp", "-"],
                       capture_output=True, **sem_janela())
    q = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR) if r.stdout else None
    _quadros_soltos[chave] = q
    if len(_quadros_soltos) > 30:
        _quadros_soltos.popitem(last=False)
    return q


def forma_rgba(item: dict, w: int, h: int, s: float) -> np.ndarray:
    im = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    borda = round(item.get("borda", 0) * s)
    caixa = (borda / 2, borda / 2, w - 1 - borda / 2, h - 1 - borda / 2)
    fundo = texto.cor(item.get("cor", "#FFC933"), item.get("cor_opac", 100) * 2.55)
    linha = texto.cor(item.get("borda_cor", "#FFFFFF")) if borda else None
    if item.get("forma") == "circulo":
        d.ellipse(caixa, fill=fundo, outline=linha, width=borda)
    else:
        d.rounded_rectangle(caixa, radius=min(item.get("raio", 0) * s, min(w, h) / 2), fill=fundo, outline=linha, width=borda)
    return np.array(im)


class Compositor:
    def __init__(self, proj: dict, midias: Midias, escala: float = 1.0, solto: bool = False):
        self.p, self.m, self.s, self.solto = proj, midias, escala, solto
        self.W, self.H = int(round(proj["largura"] * escala / 2) * 2), int(round(proj["altura"] * escala / 2) * 2)
        self.fps = int(proj.get("fps", 30))
        self.leitores: dict[str, Leitor] = {}
        self.imagens: dict[str, np.ndarray] = {}
        self.faixas = []
        for f in proj["faixas"]:
            if not f.get("oculta") and f["tipo"] != "audio":
                itens = sorted(f["itens"], key=lambda i: i["ini"])
                self.faixas.append((f, itens, [i["ini"] for i in itens]))
        g = proj["global"]
        self.zoom_forca = g.get("zoom_forca", 100) / 100

    def fechar(self) -> None:
        for l in self.leitores.values():
            l.fechar()

    def _pixels(self, item: dict, u: float) -> np.ndarray | None:
        mid = self.p["midias"].get(item.get("midia"))
        if not mid:
            return None
        try:
            caminho = self.m.caminho(mid)
        except (ValueError, KeyError):
            return None
        if mid["tipo"] == "imagem":
            if item["midia"] not in self.imagens:
                im = cv2.imread(str(caminho), cv2.IMREAD_UNCHANGED)
                if im is not None and im.ndim == 2:
                    im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
                self.imagens[item["midia"]] = im
            return self.imagens[item["midia"]]
        if not caminho.exists():
            return None
        t = item.get("entrada", 0.0) + u * item.get("velocidade", 1.0)
        if self.solto:
            return quadro_solto(caminho, t, self.fps)
        leitor = self.leitores.setdefault(item["midia"], Leitor(caminho, self.fps))
        return leitor.quadro(t)

    def _colar(self, buf: np.ndarray, src: np.ndarray, m: np.ndarray, opac: float, ajuste=None) -> None:
        """Coloca a imagem no quadro usando a matriz da origem para o destino."""
        h, w = src.shape[:2]
        cantos = (m @ np.array([[0, 0, 1], [w, 0, 1], [0, h, 1], [w, h, 1]], np.float64).T).T
        x0, y0 = np.floor(cantos.min(axis=0)).astype(int)
        x1, y1 = np.ceil(cantos.max(axis=0)).astype(int)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.W, x1), min(self.H, y1)
        if x1 <= x0 or y1 <= y0 or opac <= 0:
            return
        l = m.copy()
        l[0, 2] -= x0; l[1, 2] -= y0
        tam = (x1 - x0, y1 - y0)
        reduz = abs(m[0, 0]) + abs(m[0, 1]) < 0.75
        modo = cv2.INTER_AREA if reduz and abs(m[0, 1]) < 1e-6 else cv2.INTER_LINEAR if reduz else cv2.INTER_CUBIC
        if reduz and abs(m[0, 1]) < 1e-6:
            modo = cv2.INTER_LINEAR
            fator = int(1 / max(abs(m[0, 0]), 1e-3))
            if fator >= 2:
                src = cv2.resize(src, (max(1, w // fator), max(1, h // fator)), interpolation=cv2.INTER_AREA)
                l = l @ np.array([[w / src.shape[1], 0, 0], [0, h / src.shape[0], 0], [0, 0, 1]], np.float64)
        temalfa = src.shape[2] == 4
        cor = src[..., :3] if temalfa else src
        saida = cv2.warpAffine(cor, l, tam, flags=modo, borderMode=cv2.BORDER_REPLICATE)
        reto = abs(m[0, 1]) < 1e-6 and abs(m[1, 0]) < 1e-6
        if ajuste:
            saida = ajuste(saida)
        roi = buf[y0:y1, x0:x1]
        if temalfa or not reto:
            base = src[..., 3] if temalfa else np.full(src.shape[:2], 255, np.uint8)
            a = cv2.warpAffine(base, l, tam, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0).astype(np.float32) / 255 * (opac / 100)
            roi[:] = (saida * a[..., None] + roi * (1 - a[..., None])).astype(np.uint8)
        elif opac >= 99.9:
            roi[:] = saida
        else:
            roi[:] = cv2.addWeighted(saida, opac / 100, roi, 1 - opac / 100, 0)

    def _matriz(self, sx0: float, sy0: float, sx1: float, sy1: float, cx: float, cy: float, bw: float, bh: float, rot: float) -> np.ndarray:
        a = math.radians(rot)
        c, s = math.cos(a), math.sin(a)
        ux, uy = bw / max(1e-6, sx1 - sx0), bh / max(1e-6, sy1 - sy0)
        m = np.array([[c * ux, -s * uy, 0.0], [s * ux, c * uy, 0.0]], np.float64)
        mx, my = (sx0 + sx1) / 2, (sy0 + sy1) / 2
        m[0, 2] = cx - m[0, 0] * mx - m[0, 1] * my
        m[1, 2] = cy - m[1, 0] * mx - m[1, 1] * my
        return m

    def _visual(self, buf: np.ndarray, item: dict, u: float, opac_x: float = 1.0, dx: float = 0.0, dy: float = 0.0, escala_x: float = 1.0) -> None:
        v = lambda p: valor(item, p, u)
        s = self.s
        cx, cy = (v("x") + dx) * s, (v("y") + dy) * s
        esc = v("escala") * escala_x
        bw, bh = v("w") * esc * s, v("h") * esc * s
        opac, rot = v("opac") * opac_x, v("rot")
        if item["tipo"] == "forma":
            w, h = max(1, round(v("w") * s)), max(1, round(v("h") * s))
            spr = forma_rgba(item, w, h, s)[..., [2, 1, 0, 3]]
            self._colar(buf, spr, self._matriz(0, 0, w, h, cx, cy, bw, bh, rot), opac)
            return
        src = self._pixels(item, u)
        if src is None:
            return
        h, w = src.shape[:2]
        cl, ct, cr, cb = (np.clip(v(c), 0, .95) for c in ("cl", "ct", "cr", "cb"))
        fx0, fx1, fy0, fy1 = cl, max(cl + .01, 1 - cr), ct, max(ct + .01, 1 - cb)
        z = max(1.0, 1 + (v("zoom") - 1) * self.zoom_forca * item.get("zoom_forca", 100) / 100)
        lx, ly = (fx1 - fx0) / z, (fy1 - fy0) / z
        zx = float(np.clip(fx0 + v("zx") * (fx1 - fx0), fx0 + lx / 2, fx1 - lx / 2))
        zy = float(np.clip(fy0 + v("zy") * (fy1 - fy0), fy0 + ly / 2, fy1 - ly / 2))
        sx0, sx1, sy0, sy1 = (zx - lx / 2) * w, (zx + lx / 2) * w, (zy - ly / 2) * h, (zy + ly / 2) * h
        px0, py0, px1, py1 = max(0, int(sx0) - 2), max(0, int(sy0) - 2), min(w, int(sx1) + 3), min(h, int(sy1) + 3)
        parte = src[py0:py1, px0:px1]
        m = self._matriz(sx0 - px0, sy0 - py0, sx1 - px0, sy1 - py0, cx, cy, bw, bh, rot)
        # A área fora do recorte não pode aparecer: corta a origem no limite exato.
        fx, fy = max(0, round(sx0 - px0)), max(0, round(sy0 - py0))
        parte = parte[fy:fy + max(1, round(sy1 - sy0)), fx:fx + max(1, round(sx1 - sx0))]
        m = m @ np.array([[1, 0, fx], [0, 1, fy], [0, 0, 1]], np.float64)
        fil = item.get("filtro") or self.p["global"].get("filtro") or {}
        aj = item.get("ajustes")

        def ajuste(q: np.ndarray) -> np.ndarray:
            return filtros.ajustar(filtros.aplicar(q, fil.get("nome"), fil.get("forca", 100)), aj)

        self._colar(buf, parte, m, opac, ajuste if fil.get("nome") or aj else None)

    def _anterior(self, itens: list, item: dict) -> dict | None:
        ant = [i for i in itens if i is not item and abs(i["ini"] + i["dur"] - item["ini"]) < 0.08 and i["tipo"] in ("video", "imagem")]
        return ant[-1] if ant else None

    def _regiao(self, item: dict, u: float) -> tuple[int, int, int, int]:
        cx, cy, esc = valor(item, "x", u) * self.s, valor(item, "y", u) * self.s, valor(item, "escala", u) * self.s
        w, h = valor(item, "w", u) * esc / 2, valor(item, "h", u) * esc / 2
        x0, y0, x1, y1 = max(0, int(cx - w)), max(0, int(cy - h)), min(self.W, int(np.ceil(cx + w))), min(self.H, int(np.ceil(cy + h)))
        return (x0, y0, x1, y1) if x1 - x0 >= 8 and y1 - y0 >= 8 else (0, 0, self.W, self.H)

    def _com_transicao(self, buf: np.ndarray, itens: list, item: dict, u: float, t: float) -> None:
        tr = item.get("transicao") or {}
        tipo, dur = tr.get("tipo", "corte"), float(tr.get("dur", 0.4))
        if tipo == "corte" or u >= dur or item["tipo"] not in ("video", "imagem"):
            self._visual(buf, item, u)
            return
        p = suave(max(0.0, u / max(.01, dur)))
        a = self._anterior(itens, item)
        if tipo in transicoes.TIPOS:  # metade na cena que sai, metade na cena que entra
            meio = max(.01, dur / 2)
            x0, y0, x1, y1 = self._regiao(item, u)  # cada parte da tela faz a transição no seu próprio quadro
            if u < meio and a:
                self._visual(buf, a, t - a["ini"]); forca, lado = suave(u / meio), -1
            else:
                self._visual(buf, item, u); forca, lado = suave(max(0.0, 1 - (u - meio) / meio)), 1
            buf[y0:y1, x0:x1] = transicoes.aplicar(buf[y0:y1, x0:x1].copy(), tipo, forca, lado, round(t * self.fps))
            return
        desenhar_a = lambda **k: self._visual(buf, a, t - a["ini"], **k) if a else None
        if tipo == "dissolver":
            desenhar_a(); self._visual(buf, item, u, opac_x=p)
        elif tipo in ("preto", "branco"):
            cor = 0 if tipo == "preto" else 255
            if p < .5:
                desenhar_a(); forca = p * 2
            else:
                self._visual(buf, item, u); forca = (1 - p) * 2
            buf[:] = cv2.addWeighted(buf, 1 - forca, np.full_like(buf, cor), forca, 0)
        elif tipo == "zoom":
            desenhar_a(); self._visual(buf, item, u, opac_x=p, escala_x=1.35 - .35 * p)
        else:
            W, H = self.p["largura"], self.p["altura"]
            dx, dy = {"esquerda": (W, 0), "direita": (-W, 0), "cima": (0, H), "baixo": (0, -H)}.get(tipo, (0, 0))
            desenhar_a(dx=-dx * p, dy=-dy * p); self._visual(buf, item, u, dx=dx * (1 - p), dy=dy * (1 - p))

    def _texto(self, buf: np.ndarray, item: dict, u: float) -> None:
        est = estilo_de(self.p, item)
        anim = texto.animar(est, u, item["dur"])
        conteudo, ativa = item.get("texto", ""), None
        palavras = item.get("palavras") or []
        if palavras:
            for n, p in enumerate(palavras):
                if u >= p["ini"]:
                    ativa = n
            ativa = 0 if ativa is None else ativa
            if est["palavra_a_palavra"]:
                conteudo, ativa = palavras[ativa]["p"], 0
        if anim["mostrar"] < 1:
            conteudo = conteudo[:max(0, round(len(conteudo) * anim["mostrar"]))]
        if not conteudo.strip():
            return
        spr = texto.desenhar(conteudo, est, self.s, ativa)
        h, w = spr.shape[:2]
        mov = texto.efeito_movimento(est, u)
        ancora = {"topo": h / 2, "base": -h / 2}.get(est["ancora"], 0.0)
        spr = texto.efeito_pixels(spr, est, u, self.s)
        h, w = spr.shape[:2]
        if item["tipo"] == "legenda":
            x, y, esc, rot, opac = est.get("x", self.p["largura"] / 2), est.get("y", self.p["altura"] * .86), 1.0, 0.0, 100.0
        else:
            x, y, esc, rot, opac = valor(item, "x", u), valor(item, "y", u), valor(item, "escala", u), valor(item, "rot", u), valor(item, "opac", u)
        cx, cy = (x + anim["dx"] + mov["dx"]) * self.s, (y + anim["dy"] + mov["dy"]) * self.s + ancora
        e = esc * anim["escala"] * mov["escala"]
        m = self._matriz(0, 0, w, h, cx, cy, w * e, h * e, rot + mov["rot"])
        rgba = spr[..., [2, 1, 0, 3]]
        self._colar(buf, rgba, m, opac * anim["alfa"] * mov["alfa"] * est["opacidade"] / 100)

    def _efeito(self, buf: np.ndarray, item: dict, u: float, n: int) -> None:
        tipo, f = item.get("efeito"), float(item.get("forca", 1.0))
        a = item.get("area")
        x0, y0, x1, y1 = (0, 0, self.W, self.H) if not a else (int(a[0] * self.s), int(a[1] * self.s), int((a[0] + a[2]) * self.s), int((a[1] + a[3]) * self.s))
        roi = buf[y0:y1, x0:x1]
        if tipo == "clarao":
            k = f * math.exp(-u * 13)
            if k > .01:
                roi[:] = cv2.addWeighted(roi, 1 - k, np.full_like(roi, 255), k, 0)
        elif tipo == "tremor":
            k = f * math.exp(-u * 8) * self.s
            if k > .3:
                m = np.array([[1, 0, k * math.sin(n * 2.4)], [0, 1, k * math.cos(n * 3.1)]], np.float64)
                roi[:] = cv2.warpAffine(roi, m, (roi.shape[1], roi.shape[0]), borderMode=cv2.BORDER_REPLICATE)
        elif tipo == "vinheta":
            k = suave(min(1.0, u / .2, (item["dur"] - u) / .3)) * f
            if k > .02:
                roi[:] = filtros.vinheta(roi, .42 * k)
        elif tipo == "escurecer":
            k = f * min(1.0, u / max(.01, item["dur"]))
            roi[:] = cv2.addWeighted(roi, 1 - k, np.zeros_like(roi), k, 0)
        elif tipo == "clarear":
            k = f * (1 - min(1.0, u / max(.01, item["dur"])))
            roi[:] = cv2.addWeighted(roi, 1 - k, np.zeros_like(roi), k, 0)
        elif tipo == "progresso":
            total = max(.01, self.p.get("duracao", item["dur"]))
            cv2.rectangle(buf, (0, 0), (int(self.W * (item["ini"] + u) / total), max(2, round(9 * self.s))), texto.cor(item.get("cor", "#FFC933"))[2::-1], -1)
        elif tipo == "filtro":
            roi[:] = filtros.aplicar(roi, item.get("filtro"), f * 100)
        elif tipo == "desfoque":
            roi[:] = filtros.ajustar(roi, {"desfoque": f * 20})
        else:
            saida = transicoes.efeito_continuo(roi, tipo, min(1.0, f), u, n)
            if saida is not None:
                roi[:] = saida

    def quadro(self, t: float) -> np.ndarray:
        buf = np.zeros((self.H, self.W, 3), np.uint8)
        n = round(t * self.fps)
        for faixa, itens, inicios in self.faixas:
            k = bisect.bisect_right(inicios, t)
            ativos = [i for i in itens[max(0, k - 6):k] if i["ini"] <= t < i["ini"] + i["dur"]]
            for item in ativos:
                u = t - item["ini"]
                if item["tipo"] in ("video", "imagem", "forma"):
                    self._com_transicao(buf, itens, item, u, t)
                elif item["tipo"] in ("texto", "legenda"):
                    self._texto(buf, item, u)
                elif item["tipo"] == "efeito":
                    self._efeito(buf, item, u, n)
        return buf


# ------------------------------------------------------------ áudio

def duracao_projeto(proj: dict) -> float:
    return max((i["ini"] + i["dur"] for f in proj["faixas"] for i in f["itens"]), default=0.0)


def _ler_audio(caminho: Path, ini: float, dur: float, vel: float) -> np.ndarray:
    filtros_a = []
    resto = vel
    while resto > 2.0:
        filtros_a.append("atempo=2"); resto /= 2
    while resto < .5:
        filtros_a.append("atempo=0.5"); resto *= 2
    if abs(resto - 1) > 1e-3:
        filtros_a.append(f"atempo={resto:.4f}")
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{ini:.3f}", "-t", f"{dur * vel:.3f}", "-i", str(caminho), "-vn", "-ac", "2", "-ar", str(TAXA)]
    r = subprocess.run(cmd + (["-af", ",".join(filtros_a)] if filtros_a else []) + ["-f", "f32le", "-"], capture_output=True, **sem_janela())
    return np.frombuffer(r.stdout[:len(r.stdout) // 8 * 8], np.float32).reshape(-1, 2)


def mixar(proj: dict, midias: Midias, pasta: Path, total: float, cancelado=lambda: False) -> tuple[Path, Path]:
    """Separa a voz dos efeitos e da música, para normalizar só a fala."""
    n = int(total * TAXA) + 1
    fala, outros = (np.memmap(pasta / nome, dtype=np.float32, mode="w+", shape=(n, 2)) for nome in ("fala.raw", "outros.raw"))
    g = proj["global"]
    for faixa in proj["faixas"]:
        if faixa.get("muda"):
            continue
        for item in faixa["itens"]:
            if cancelado():
                raise InterruptedError
            if item["tipo"] not in ("video", "audio") or item.get("mudo") or item.get("midia") not in proj["midias"]:
                continue
            mid = proj["midias"][item["midia"]]
            try:
                caminho = midias.caminho(mid)
                if not caminho.exists():
                    continue
                dados = _ler_audio(caminho, item.get("entrada", 0.0), item["dur"], item.get("velocidade", 1.0))
            except (ValueError, KeyError):
                continue
            if not len(dados):
                continue
            categoria = item.get("categoria", "voz" if item["tipo"] == "video" else "efeito")
            ganho = item.get("volume", 100) / 100 * {"voz": g.get("volume_fala", 100), "musica": g.get("volume_musica", 100), "efeito": g.get("volume_efeitos", 100)}.get(categoria, 100) / 100
            env = np.ones(len(dados), np.float32)
            for tam, lado in ((item.get("fade_in", 0), 0), (item.get("fade_out", 0), 1)):
                q = min(len(env), int(tam * TAXA))
                if q:
                    r = np.linspace(0, 1, q, dtype=np.float32)
                    if lado:
                        env[-q:] *= r[::-1]
                    else:
                        env[:q] *= r
            ini = int(item["ini"] * TAXA)
            q = min(len(dados), n - ini)
            if q > 0:
                (fala if categoria == "voz" else outros)[ini:ini + q] += dados[:q] * (env[:q] * ganho)[..., None]
    arquivos = []
    for nome, dados in (("fala", fala), ("outros", outros)):
        dados.flush()
        arq = pasta / f"{nome}.wav"
        with wave.open(str(arq), "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(TAXA)
            for i in range(0, n, TAXA * 10):
                w.writeframes((np.clip(dados[i:i + TAXA * 10], -1, 1) * 32767).astype(np.int16).tobytes())
        arquivos.append(arq)
    return arquivos[0], arquivos[1]


def exportar(proj: dict, midias: Midias, destino: Path, altura: int, progresso, cancelado=lambda: False) -> None:
    """Gera o arquivo final, quadro a quadro, sem capturar a tela."""
    total = duracao_projeto(proj)
    if total <= 0:
        raise ValueError("O projeto está vazio.")
    proj = {**proj, "duracao": total}
    menor = min(proj["largura"], proj["altura"])
    comp = Compositor(proj, midias, altura / menor)
    fps = comp.fps
    quadros = max(1, round(total * fps))
    with tempfile.TemporaryDirectory(prefix="clipador_exp_", dir=Path(destino).parent) as tmp:
        tmp = Path(tmp)
        progresso(0, "Mixando o áudio")
        fala, outros = mixar(proj, midias, tmp, total, cancelado)
        saida = tmp / "saida.mp4"
        grande = min(comp.W, comp.H) > 1200
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{comp.W}x{comp.H}", "-r", str(fps), "-i", "pipe:0", "-i", str(fala), "-i", str(outros),
               "-filter_complex", "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[f];[f][2:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]",
               "-map", "0:v", "-map", "[a]", "-t", f"{quadros / fps:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-maxrate", "60M" if grande else "24M", "-bufsize", "90M" if grande else "48M",
               "-pix_fmt", "yuv420p", "-profile:v", "high", "-g", str(fps * 2), "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", str(saida)]
        erro = open(tmp / "erro.txt", "wb")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=erro, **sem_janela())
        inicio = time.time()
        try:
            for n in range(quadros):
                if cancelado():
                    proc.kill()
                    raise InterruptedError
                proc.stdin.write(comp.quadro(n / fps).data)
                if n % 10 == 0:
                    passou = time.time() - inicio
                    resta = passou / max(1, n) * (quadros - n)
                    progresso(n / quadros, f"Gerando o vídeo, faltam cerca de {max(1, round(resta / 60))} min" if n > 30 else "Gerando o vídeo")
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError((tmp / "erro.txt").read_text(encoding="utf-8", errors="replace").strip()[-300:] or "O FFmpeg parou.")
        finally:
            comp.fechar()
            if proc.poll() is None:
                proc.kill()
            erro.close()
        progresso(1, "Finalizando")
        os.replace(saida, destino)
