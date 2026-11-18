"""Capas em camadas: a IA monta, e cada texto, imagem e forma continua editável."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

from . import estilos
from . import longo as lg
from .compositor import Compositor
from .contexto import quebrar_linhas
from .projeto import novo_id


def _imagem(rel: str, nome: str, papel: str, x, y, w, h, **extra) -> dict:
    return {"id": novo_id("k"), "tipo": "imagem", "nome": nome, "papel": papel, "midia": {"raiz": "saida", "rel": rel}, "x": x, "y": y, "w": w, "h": h, "rot": 0, "opac": 100, "escala": 1, **extra}


def _texto(txt: str, nome: str, papel: str, x, y, estilo: dict) -> dict:
    return {"id": novo_id("k"), "tipo": "texto", "nome": nome, "papel": papel, "texto": txt, "x": x, "y": y, "rot": 0, "opac": 100, "escala": 1, "estilo": estilo}


def _titulo(texto: str, cor: str, tamanho: int, largura: int, x: float, y: float) -> dict:
    return _texto(texto, "Título", "titulo", x, y, {"fonte": "Anton", "tamanho": tamanho, "cor": cor, "maiusculas": True, "alinhamento": "esquerda", "ancora": "centro", "largura": largura, "entrelinha": 108,
                                                     "contorno": 9, "contorno_cor": "#000000", "sombra": True, "sombra_x": 6, "sombra_y": 7, "sombra_blur": 4, "sombra_opac": 80})


def criar_longo(item: dict, motor) -> dict:
    pasta = motor.longos.pasta / item["id"]
    rel = f"_longos/{item['id']}"
    est = estilos.normalizar(item.get("estilo"), motor.config["estilo"])
    cor = "#" + estilos.CORES[est["cor"]]
    camadas = []
    usados = [motor.cortes.get(p.get("corte")) for p in item.get("partes") or [] if p["tipo"] == "trecho"]
    trechos = lg.criar_trechos([m for m in usados if m], motor.saida)
    if trechos:
        t = max(trechos, key=lambda x: x["forca"])
        quadro = lg._quadro_de(t["fonte"], t["momento"])
        L, A = lg.L, lg.A
        foco = lg.alvo_webcam(t["plano"]) or {}
        moldura = foco.get("moldura")
        fundo = quadro
        (pasta / "midia_projeto").mkdir(exist_ok=True)
        if moldura:
            x, y, w, h = moldura
            esq, dir_ = x, 1 - (x + w)
            lado = max(esq, dir_)
            if lado >= .3:
                x0, largura = 0 if esq >= dir_ else int((x + w) * L), int(lado * L)
                alt = min(A, int(largura * 9 / 16))
                fundo = quadro[(A - alt) // 2:(A + alt) // 2, x0:x0 + largura]
        cv2.imwrite(str(pasta / "midia_projeto" / "capa_fundo.jpg"), fundo, [cv2.IMWRITE_JPEG_QUALITY, 95])
        camadas.append(_imagem(f"{rel}/midia_projeto/capa_fundo.jpg", "Fundo", "fundo", 640, 360, 1280, 720, ajustes={"brilho": -14, "saturacao": 12}))
        if moldura:
            x, y, w, h = moldura
            rosto = quadro[int(y * A):int((y + h) * A), int(x * L):int((x + w) * L)]
            if rosto.size:
                cv2.imwrite(str(pasta / "midia_projeto" / "capa_rosto.jpg"), rosto, [cv2.IMWRITE_JPEG_QUALITY, 95])
                alt = 600; lar = min(620, int(alt * rosto.shape[1] / max(1, rosto.shape[0])))
                camadas.append(_imagem(f"{rel}/midia_projeto/capa_rosto.jpg", "Streamer", "rosto", 1280 - lar / 2 - 46, 720 - alt / 2 - 50, lar, alt, borda=10, borda_cor=cor))
    elif (pasta / "capa.jpg").exists():
        shutil.copy(pasta / "capa.jpg", pasta / "capa_original.jpg")
        camadas.append(_imagem(f"{rel}/capa_original.jpg", "Capa original", "fundo", 640, 360, 1280, 720))
    palavras = (item.get("titulo") or "").split("...")[0].upper().split()[:6]
    quebra = quebrar_linhas(palavras, 11)
    txt = " ".join(palavras) if quebra is None else " ".join(palavras[:quebra]) + "\n" + " ".join(palavras[quebra:])
    if txt and trechos:
        camadas.append(_titulo(txt, cor, 100, 720, 400, 540))
    if item.get("canal") and trechos:
        camadas.append(_texto(item["canal"].upper(), "Canal", "canal", 200, 62, {"fonte": "Poppins-Bold", "tamanho": 30, "contorno": 5, "largura": 500, "alinhamento": "esquerda"}))
    return {"formato": 1, "largura": 1280, "altura": 720, "fundo": "#0F1B20", "camadas": camadas}


def criar_corte(meta: dict, motor) -> dict:
    rel = meta["id"]
    est = estilos.normalizar(meta.get("estilo"), motor.config["estilo"])
    camadas = [_imagem(f"{rel}/quadro.jpg", "Fundo", "fundo", 640, 360, 1280, 720, ajustes={"brilho": -10, "saturacao": 12})] if (motor.saida / rel / "quadro.jpg").exists() else []
    camadas.append(_titulo(" ".join((meta.get("gancho") or "").upper().split()[:7]), "#" + estilos.CORES[est["cor"]], 92, 1120, 640, 540))
    camadas.append(_texto((meta.get("canal") or "").upper(), "Canal", "canal", 200, 62, {"fonte": "Poppins-Bold", "tamanho": 30, "contorno": 5, "largura": 500, "alinhamento": "esquerda"}))
    return {"formato": 1, "largura": 1280, "altura": 720, "fundo": "#0F1B20", "camadas": camadas}


def renderizar(capa: dict, midias, escala: float = 1.0) -> np.ndarray:
    """A capa passa pelo mesmo motor do vídeo."""
    proj = {"largura": capa["largura"], "altura": capa["altura"], "fps": 30, "midias": {}, "global": {}, "faixas": []}
    itens = [{"id": "fundo", "tipo": "forma", "ini": 0, "dur": 1, "forma": "retangulo", "cor": capa.get("fundo", "#000000"), "t": {"x": capa["largura"] / 2, "y": capa["altura"] / 2, "w": capa["largura"], "h": capa["altura"]}}]
    for c in capa["camadas"]:
        if c.get("oculta"):
            continue
        t = {k: c.get(k, d) for k, d in (("x", 0), ("y", 0), ("w", 100), ("h", 100), ("rot", 0), ("opac", 100), ("escala", 1), ("cl", 0), ("ct", 0), ("cr", 0), ("cb", 0))}
        if c["tipo"] == "imagem":
            mid = c["id"]
            proj["midias"][mid] = {"id": mid, "tipo": "imagem", **c["midia"]}
            esc = t["escala"]
            if c.get("sombra"):
                itens.append({"id": mid + "s", "tipo": "forma", "ini": 0, "dur": 1, "forma": "retangulo", "cor": "#000000", "cor_opac": 45, "raio": c.get("raio", 0), "t": {**t, "x": t["x"] + 10, "y": t["y"] + 12}})
            if c.get("borda"):
                b = c["borda"] * 2 / max(esc, .01)
                itens.append({"id": mid + "b", "tipo": "forma", "ini": 0, "dur": 1, "forma": "retangulo", "cor": c.get("borda_cor", "#FFFFFF"), "raio": c.get("raio", 0), "t": {**t, "w": t["w"] + b, "h": t["h"] + b}})
            itens.append({"id": mid, "tipo": "imagem", "ini": 0, "dur": 1, "midia": mid, "t": t, "ajustes": c.get("ajustes")})
        elif c["tipo"] == "texto":
            itens.append({"id": c["id"], "tipo": "texto", "ini": 0, "dur": 1, "texto": c.get("texto", ""), "estilo": c.get("estilo") or {}, "t": t})
        else:
            itens.append({**{k: c.get(k) for k in ("forma", "cor", "cor_opac", "borda", "borda_cor", "raio") if c.get(k) is not None}, "id": c["id"], "tipo": "forma", "ini": 0, "dur": 1, "t": t})
    proj["faixas"] = [{"tipo": "video", "itens": itens}]
    comp = Compositor(proj, midias, escala, solto=True)
    return comp.quadro(0.0)


class Modelos:
    def __init__(self, dados: Path):
        self.arquivo = dados / "modelos_capa.json"

    def listar(self) -> list[dict]:
        try:
            return json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def salvar(self, nome: str, capa: dict) -> list[dict]:
        nome = str(nome).strip()[:50]
        if not nome:
            raise ValueError("Dê um nome ao modelo.")
        lista = [m for m in self.listar() if m["nome"] != nome] + [{"id": novo_id("m"), "nome": nome, "capa": capa, "criado": time.time()}]
        self.arquivo.write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")
        return lista

    def apagar(self, ident: str) -> list[dict]:
        lista = [m for m in self.listar() if m["id"] != ident]
        self.arquivo.write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")
        return lista


def aplicar_modelo(modelo: dict, atual: dict) -> dict:
    """Usa o visual do modelo com o fundo, o rosto e os textos desta capa."""
    por_papel = {c.get("papel"): c for c in atual["camadas"] if c.get("papel")}
    novas = []
    for c in json.loads(json.dumps(modelo["camadas"])):
        c["id"] = novo_id("k")
        velho = por_papel.get(c.get("papel"))
        if velho and c["tipo"] == "imagem" and velho["tipo"] == "imagem":
            c["midia"] = velho["midia"]
        elif velho and c["tipo"] == "texto" and velho["tipo"] == "texto":
            c["texto"] = velho["texto"]
        novas.append(c)
    return {**modelo, "camadas": novas}
