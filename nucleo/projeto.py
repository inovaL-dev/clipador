"""Formato do projeto editável e conversão da edição automática da IA em elementos separados."""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from . import camera as cam
from . import edicao, efeitos, estilos
from . import foco as foco_tela
from . import longo as lg
from .compositor import duracao_projeto, valor

FORMATO = 1
ASS = 0.68  # os tamanhos da edição automática medem a altura da linha; aqui medem a letra
PROPS = ("x", "y", "w", "h", "escala", "rot", "opac", "zoom", "zx", "zy", "cl", "ct", "cr", "cb")


def novo_id(prefixo: str = "e") -> str:
    return f"{prefixo}{uuid.uuid4().hex[:9]}"


def _faixa(tipo: str, nome: str) -> dict:
    return {"id": novo_id("f"), "tipo": tipo, "nome": nome, "oculta": False, "muda": False, "travada": False, "itens": []}


def _rdp(t: np.ndarray, v: np.ndarray, eps: float) -> list[int]:
    """Guarda só os pontos que mudam a curva, para os keyframes da IA serem fáceis de editar."""
    fica = np.zeros(len(t), bool); fica[[0, -1]] = True
    pilha = [(0, len(t) - 1)]
    while pilha:
        a, b = pilha.pop()
        if b <= a + 1:
            continue
        reta = v[a] + (v[b] - v[a]) * (t[a + 1:b] - t[a]) / max(1e-9, t[b] - t[a])
        d = np.abs(v[a + 1:b] - reta)
        k = int(d.argmax())
        if d[k] > eps:
            k += a + 1; fica[k] = True; pilha += [(a, k), (k, b)]
    return list(np.flatnonzero(fica))


def _chaves(mov, ini: float = 0.0) -> dict:
    kf = {}
    for prop, serie, eps in (("zoom", np.maximum(1.0, mov.z), .004), ("zx", mov.cx, .004), ("zy", mov.cy, .004)):
        if float(serie.max() - serie.min()) > eps:
            kf[prop] = [{"t": round(float(mov.t[i]) + ini, 3), "v": round(float(serie[i]), 4), "e": "linear"} for i in _rdp(mov.t, serie.astype(np.float64), eps)]
    return kf


def _base(mov) -> dict:
    return {"zoom": round(max(1.0, float(mov.z[0])), 4), "zx": round(float(mov.cx[0]), 4), "zy": round(float(mov.cy[0]), 4)}


def _item_video(midia: str, ini: float, dur: float, entrada: float, nome: str, t: dict, kf: dict | None = None, **extra) -> dict:
    return {"id": novo_id(), "tipo": "video", "nome": nome, "midia": midia, "ini": round(ini, 3), "dur": round(dur, 3), "entrada": round(entrada, 3), "velocidade": 1.0,
            "volume": 100, "t": {"escala": 1.0, "rot": 0.0, "opac": 100.0, "zoom": 1.0, "zx": .5, "zy": .5, "cl": 0.0, "ct": 0.0, "cr": 0.0, "cb": 0.0, **t}, "kf": kf or {}, **extra}


def _item_texto(tipo: str, ini: float, dur: float, txt: str, x: float, y: float, estilo: dict, nome: str = "Texto", **extra) -> dict:
    estilo = {**estilo, "tamanho": round(estilo.get("tamanho", 66) * ASS)}
    return {"id": novo_id(), "tipo": tipo, "nome": nome, "ini": round(ini, 3), "dur": round(dur, 3), "texto": txt, "estilo": estilo,
            "t": {"x": x, "y": y, "escala": 1.0, "rot": 0.0, "opac": 100.0}, "kf": {}, **extra}


def _efeito(ini: float, dur: float, tipo: str, nome: str, forca: float = 1.0, **extra) -> dict:
    return {"id": novo_id(), "tipo": "efeito", "nome": nome, "efeito": tipo, "ini": round(ini, 3), "dur": round(dur, 3), "forca": forca, **extra}


def _som(midias: dict, som: str, nome: str, ini: float, volume: float, biblioteca, cena: str | None = None) -> dict:
    mid = f"som:{som}"
    arq = biblioteca.caminho(som)
    midias.setdefault(mid, {"id": mid, "tipo": "audio", "raiz": "som", "rel": som, "nome": nome, "dur": round(arq.stat().st_size / 192000, 3)})
    return {"id": novo_id(), "tipo": "audio", "categoria": "efeito", "nome": nome, "midia": mid, "ini": round(ini, 3), "dur": midias[mid]["dur"], "entrada": 0.0, "volume": round(volume * 100), "cena": cena}


def estilo_legenda(est: dict, largura: int, altura: int) -> dict:
    """Traduz os modelos automáticos para opções que podem ser alteradas uma a uma."""
    vertical = altura > largura
    t = (66 if vertical else 56) * estilos.TAMANHOS[est["tamanho"]]
    destaque = "#" + estilos.CORES[est["cor"]]
    x, y = estilos.ponto(est, "legenda_x" if vertical else "legenda_hx", "legenda_y" if vertical else "legenda_hy", largura, altura, largura // 2, edicao.BASE_LEGENDA if vertical else 1030)
    base = {"fonte": "Poppins-Bold", "tamanho": round(t * ASS), "cor": "#FFFFFF", "cor_destaque": destaque, "maiusculas": True, "ancora": "base", "x": x, "y": y, "largura": round(largura * (.84 if vertical else .7)),
            "contorno": round(t * .106), "contorno_cor": "#000000", "sombra": True, "sombra_y": 3, "sombra_blur": 3, "destaque": "palavra", "entrada": "pop", "saida": "nenhuma", "tempo_anim": .09}
    return {**base, **{
        "destaque": {}, "caixa": {"destaque_caixa": True, "contorno": round(t * .09)},
        "palavra": {"tamanho": round(t * 1.25 * ASS), "maiusculas": False, "palavra_a_palavra": True, "destaque": "importantes", "contorno": round(t * .16)},
        "impacto": {"tamanho": round(t * 1.45 * ASS), "cor": destaque, "contorno": round(t * .19), "palavra_a_palavra": True, "destaque": "nenhum", "sombra_y": 6},
        "neon": {"cor": destaque, "cor_destaque": "#FFFFFF", "contorno": 0, "sombra_cor": destaque, "sombra_y": 0, "sombra_blur": 16, "sombra_opac": 100},
        "faixa": {"fundo": True, "fundo_cor": "#000000", "fundo_opac": 84, "fundo_pad": round(t * .2), "contorno": 0, "sombra": False},
        "classica": {"maiusculas": False, "destaque": "nenhum", "contorno": round(t * .05), "entrada": "fade", "saida": "fade", "sombra_y": 3},
    }[est["legenda"]]}


def estilo_titulo(est: dict, tamanho: float) -> dict:
    destaque = "#" + estilos.CORES[est["cor"]]
    base = {"fonte": "Poppins-Bold", "tamanho": round(tamanho), "ancora": "topo", "largura": 760, "maiusculas": True, "alinhamento": "centro", "fundo": True, "fundo_pad": round(tamanho * .3), "fundo_raio": 6, "fundo_opac": 100, "entrada": "pop", "saida": "fade", "tempo_anim": .2}
    return {**base, **{
        "faixa": {"cor": "#141414", "fundo_cor": destaque}, "nenhum": {"cor": "#141414", "fundo_cor": destaque}, "preto": {"cor": destaque, "fundo_cor": "#141414"},
        "alerta": {"cor": "#FFFFFF", "fundo_cor": "#FF2D46"}, "branco": {"cor": "#141414", "fundo_cor": "#FFFFFF"},
        "contorno": {"cor": destaque, "fundo": False, "contorno": round(tamanho * .18), "tamanho": round(tamanho * 1.16)},
        "neon": {"cor": "#FFFFFF", "fundo": False, "sombra": True, "sombra_cor": destaque, "sombra_y": 0, "sombra_blur": 14, "sombra_opac": 100, "tamanho": round(tamanho * 1.16)},
        **{k: v for k, v in modelos_titulo(destaque, tamanho).items()},
    }[est["gancho"]]}


def modelos_titulo(destaque: str, tamanho: float) -> dict:
    """Os mesmos modelos de título com outras fontes, para o editor."""
    t = lambda f: round(tamanho * f)
    return {
        "impacto": {"fonte": "Anton", "cor": "#FFFFFF", "fundo": False, "contorno": t(.14), "contorno_cor": "#000000", "sombra": True, "sombra_y": t(.05), "sombra_blur": 0, "sombra_opac": 90, "tamanho": t(1.3)},
        "quadrinho": {"fonte": "Bangers", "cor": destaque, "fundo": False, "contorno": t(.16), "contorno_cor": "#000000", "sombra": True, "sombra_x": t(.07), "sombra_y": t(.07), "sombra_blur": 0, "sombra_opac": 100, "tamanho": t(1.3), "entrada": "quique"},
        "manchete": {"fonte": "Bebas-Neue", "cor": "#FFFFFF", "fundo_cor": "#E5202E", "tamanho": t(1.35), "fundo_raio": 2},
        "gamer": {"fonte": "Russo-One", "cor": destaque, "fundo_cor": "#0B0F14", "borda": 3, "borda_cor": destaque, "tamanho": t(1.05)},
        "desenho": {"fonte": "Luckiest-Guy", "cor": "#FFFFFF", "fundo": False, "contorno": t(.15), "contorno_cor": destaque, "sombra": True, "sombra_y": t(.06), "sombra_blur": 0, "sombra_opac": 100, "tamanho": t(1.2), "entrada": "quique"},
        "minimal": {"fonte": "Montserrat-Black", "cor": "#FFFFFF", "fundo": False, "maiusculas": False, "sombra": True, "sombra_y": 3, "sombra_blur": 12, "sombra_opac": 70, "entrada": "subir"},
        "sombra3d": {"fonte": "Archivo-Black", "cor": "#FFFFFF", "fundo": False, "contorno": t(.06), "contorno_cor": "#000000", "sombra": True, "sombra_cor": destaque, "sombra_x": t(.1), "sombra_y": t(.1), "sombra_blur": 0, "sombra_opac": 100, "tamanho": t(1.1)},
        "marcador": {"fonte": "Permanent-Marker", "cor": "#141414", "fundo_cor": "#FFFFFF", "maiusculas": False, "tamanho": t(1.1), "fundo_raio": 4},
    }


def legendas_de(grupos: list[dict], desloca: float, limite: float, cena: str | None = None) -> list[dict]:
    itens = []
    for n, g in enumerate(grupos):
        palavras = g.get("palavras") or []
        if not palavras:
            continue
        ini = float(palavras[0]["ini"])
        prox = float(grupos[n + 1]["palavras"][0]["ini"]) if n + 1 < len(grupos) and grupos[n + 1].get("palavras") else limite
        fim = max(ini + .12, min(prox, float(palavras[-1]["fim"]) + .35, limite))
        itens.append({"id": novo_id(), "tipo": "legenda", "nome": "Legenda", "ini": round(ini + desloca, 3), "dur": round(fim - ini, 3), "texto": " ".join(p["p"] for p in palavras),
                      "palavras": [{"p": p["p"], "ini": round(float(p["ini"]) - ini, 3), "fim": round(float(p["fim"]) - ini, 3)} for p in palavras], "estilo": {}, "cena": cena})
    return itens


def _vazio(tipo: str, ident: str, titulo: str, largura: int, altura: int, est: dict) -> dict:
    fil = {"nome": est["filtro"], "forca": est["filtro_forca"]} if est.get("filtro", "nenhum") != "nenhum" else None
    return {"formato": FORMATO, "tipo": tipo, "id": ident, "titulo": titulo, "largura": largura, "altura": altura, "fps": 30, "midias": {}, "faixas": [], "cenas": [],
            "global": {"legenda": estilo_legenda(est, largura, altura), "filtro": fil, "volume_fala": 100, "volume_musica": 100, "volume_efeitos": 100, "zoom_forca": 100}, "criado": time.time()}


def _midia_video(proj: dict, rel: str, caminho: Path, nome: str) -> str:
    mid = "v" + str(abs(hash(rel)) % 10 ** 10) if False else "v" + uuid.uuid5(uuid.NAMESPACE_URL, rel).hex[:10]
    if mid not in proj["midias"]:
        w, h, d = cam.dimensoes(caminho)
        proj["midias"][mid] = {"id": mid, "tipo": "video", "raiz": "saida", "rel": rel, "nome": nome, "dur": d, "lar": w, "alt": h}
    return mid


def _cortar_lados(rect: dict, vw: int, vh: int) -> dict:
    return {"cl": rect["x"] / vw, "ct": rect["y"] / vh, "cr": 1 - (rect["x"] + rect["w"]) / vw, "cb": 1 - (rect["y"] + rect["h"]) / vh}


def importar_corte(meta: dict, motor) -> dict:
    """Short: cada parte da edição automática vira um elemento separado na timeline."""
    pasta = motor.saida / meta["id"]
    fonte = pasta / "fonte.mp4"
    vw, vh, medido = cam.dimensoes(fonte)
    total = float(meta.get("duracao_fonte") or medido or meta["duracao"])
    est = estilos.normalizar(meta.get("estilo"), motor.config["estilo"])
    p = _vazio("corte", meta["id"], meta.get("gancho") or "Short", 1080, 1920, est)
    motor.aprendizado.aplicar_em_projeto(p)
    ed = meta.get("edicao") or {}
    if ed.get("filtro"):
        p["global"]["filtro"] = {"nome": ed["filtro"], "forca": ed.get("intensidade", 100)} if ed["filtro"] != "nenhum" else None
    p["global"]["volume_fala"] = ed.get("volume", 100)
    mid = _midia_video(p, f"{meta['id']}/fonte.mp4", fonte, "Vídeo da live")
    plano = meta.get("plano") or {"layout": "inteiro"}
    layout = plano["layout"]
    picos = efeitos.batidas(fonte, duracao=total)
    momento = meta.get("momento_fonte")
    momento = float(momento) if momento is not None else (max(picos, key=lambda x: x[1])[0] if picos else total * .65)
    momento = min(max(.3, momento), max(.3, total - .5))
    movs = edicao._agenda_short(layout, max(1, round(total * 30)), total, momento, picos)
    cena = novo_id("c")
    p["cenas"] = [{"id": cena, "nome": "Cena 1"}]
    efx = _faixa("efeito", "Efeitos")
    if layout == "pip":
        jogo = _faixa("video", "Jogo"); camera = _faixa("video", "Câmera")
        v = plano["pip"]; cx, cy = v["x"] + v["w"] / 2, v["y"] + v["h"] / 2
        kf = _chaves(movs[0])
        a, b = max(0, momento - .05), min(total, momento + 1.9)
        kf["escala"] = [{"t": round(t_, 3), "v": val, "e": "suave"} for t_, val in ((a, 1.0), (a + .18, min(1.75, 1000 / v["w"])), (b - .22, min(1.75, 1000 / v["w"])), (b, 1.0))]
        kf["y"] = [{"t": round(t_, 3), "v": val, "e": "suave"} for t_, val in ((a, cy), (a + .18, 760), (b - .22, 760), (b, cy))]
        camera["itens"].append(_item_video(mid, 0, total, 0, "Câmera", {"x": cx, "y": cy, "w": v["w"], "h": v["h"], **_cortar_lados(plano["camera"], vw, vh), **_base(movs[0])}, kf, cena=cena))
        jogo["itens"].append(_item_video(mid, 0, total, 0, "Jogo", {"x": 540, "y": 960, "w": 1080, "h": 1920, **_cortar_lados(plano["jogo"], vw, vh), **_base(movs[1])}, _chaves(movs[1]), mudo=True, cena=cena))
        p["faixas"] += [jogo, camera]
        efx["itens"].append(_efeito(momento, min(1.2, total - momento), "clarao", "Clarão na reação", .35, cena=cena))
    elif layout == "dividido" and plano.get("camera"):
        jogo = _faixa("video", "Jogo"); camera = _faixa("video", "Câmera")
        camera["itens"].append(_item_video(mid, 0, total, 0, "Câmera", {"x": 540, "y": 378.5, "w": 1080, "h": 757, **_cortar_lados(plano["camera"], vw, vh), **_base(movs[0])}, _chaves(movs[0]), cena=cena))
        jogo["itens"].append(_item_video(mid, 0, total, 0, "Jogo", {"x": 540, "y": 1341.5, "w": 1080, "h": 1157, **_cortar_lados(plano["jogo"], vw, vh), **_base(movs[1])}, _chaves(movs[1]), mudo=True, cena=cena))
        p["faixas"] += [jogo, camera]
        efx["itens"].append(_efeito(momento, min(1.2, total - momento), "clarao", "Clarão na reação", .55, area=[0, 0, 1080, 757], cena=cena))
        efx["itens"].append(_efeito(momento, min(1.2, total - momento), "tremor", "Tremor na reação", 6.0, area=[0, 0, 1080, 757], cena=cena))
    else:
        principal = _faixa("video", "Vídeo")
        if layout == "tela_cheia" and plano.get("recorte"):
            principal["itens"].append(_item_video(mid, 0, total, 0, "Vídeo", {"x": 540, "y": 960, "w": 1080, "h": 1920, **_cortar_lados(plano["recorte"], vw, vh), **_base(movs[0])}, _chaves(movs[0]), cena=cena))
        else:
            fundo = _faixa("video", "Fundo")
            lado = (1 - (vh * 9 / 16) / vw) / 2 if vw / vh > 9 / 16 else 0
            fundo["itens"].append(_item_video(mid, 0, total, 0, "Fundo desfocado", {"x": 540, "y": 960, "w": 1080, "h": 1920, "cl": lado, "cr": lado}, mudo=True, cena=cena, ajustes={"desfoque": 40, "brilho": -20, "saturacao": 15}))
            p["faixas"].append(fundo)
            alt = 1080 * vh / vw
            principal["itens"].append(_item_video(mid, 0, total, 0, "Vídeo", {"x": 540, "y": 960, "w": 1080, "h": round(alt, 1), **_base(movs[0])}, _chaves(movs[0]), cena=cena))
        p["faixas"].append(principal)
        efx["itens"].append(_efeito(momento, min(1.2, total - momento), "clarao", "Clarão na reação", .45, cena=cena))
        efx["itens"].append(_efeito(momento, min(1.2, total - momento), "tremor", "Tremor na reação", 6.0, cena=cena))
    if meta.get("focos"):
        faixa_foco = _faixa("video", "Foco")
        px, py, pw, ph = foco_tela.painel(plano)
        for f in meta["focos"]:
            d = float(f["dur"])
            faixa_foco["itens"].append(_item_video(mid, f["t"], d, f["t"], f"Foco: {f['nome']}", {"x": px + pw / 2, "y": py + ph / 2, "w": pw, "h": ph, "cl": f["x"] / vw, "ct": f["y"] / vh, "cr": 1 - (f["x"] + f["w"]) / vw, "cb": 1 - (f["y"] + f["h"]) / vh},
                                                   {"escala": [{"t": 0.0, "v": .84, "e": "suave"}, {"t": .2, "v": 1.0, "e": "suave"}, {"t": round(d - .16, 3), "v": 1.0, "e": "suave"}, {"t": round(d, 3), "v": .84, "e": "suave"}],
                                                    "opac": [{"t": 0.0, "v": 0.0, "e": "linear"}, {"t": .12, "v": 100.0, "e": "linear"}, {"t": round(d - .1, 3), "v": 100.0, "e": "linear"}, {"t": round(d, 3), "v": 0.0, "e": "linear"}]}, mudo=True, cena=cena))
        p["faixas"].insert(len(p["faixas"]) - 1 if layout == "pip" else len(p["faixas"]), faixa_foco)
    efx["itens"].append(_efeito(0, total, "progresso", "Barra de progresso", cor="#" + estilos.CORES[est["cor"]]))
    efx["itens"].append(_efeito(max(0, total - .25), min(.25, total), "escurecer", "Escurecer no final"))
    textos = _faixa("texto", "Textos")
    if meta.get("credito"):
        cred = {"dividido": (40, 720)}.get(layout, (40, 150))
        if layout == "pip":
            textos["itens"].append(_item_texto("texto", 0, total, meta["credito"], 540, 1800, {"fonte": "Poppins-Bold", "tamanho": 50, "fundo": True, "fundo_cor": "#101010", "fundo_opac": 85, "fundo_raio": 40, "fundo_pad": 22, "largura": 960}, "Barra do canal"))
        else:
            textos["itens"].append(_item_texto("texto", 0, total, meta["credito"], cred[0] + 170, cred[1], {"fonte": "Poppins-Bold", "tamanho": 28, "opacidade": 80, "contorno": 3, "alinhamento": "esquerda", "largura": 340}, "Crédito"))
    if meta.get("gancho") and est["gancho"] != "nenhum":
        gx, gy = estilos.ponto(est, "gancho_x", "gancho_y", 1080, 1920, 540, edicao.POSICAO_GANCHO.get(layout, 800))
        textos["itens"].append(_item_texto("texto", 0, min(est["tempo_gancho"] + .5, total), meta["gancho"], gx, gy, estilo_titulo(est, 54), "Título", papel="gancho"))
        giro = estilos.TITULOS_EXTRA.get(est["gancho"], (0,) * 9)[8] or (-2 if est["gancho"] == "branco" else 0)
        textos["itens"][-1]["t"]["rot"] = float(giro)
    leg = _faixa("legenda", "Legendas")
    leg["itens"] = legendas_de(meta.get("grupos") or [], 0, total, cena)
    audio = _faixa("audio", "Efeitos sonoros")
    sons = ed.get("sons") if ed else [{"som": "whoosh_rapido", "t": 0.0, "volume": .3}, {"som": "boom_grave", "t": momento, "volume": .42}, *[{"som": "zoom_in", "t": f["t"], "volume": .36} for f in meta.get("focos") or []]]
    for s in sons or []:
        if motor.biblioteca.existe(s["som"]):
            audio["itens"].append(_som(p["midias"], s["som"], motor.biblioteca.nome(s["som"]), float(s["t"]), float(s["volume"]), motor.biblioteca, cena))
    p["faixas"] += [efx, textos, leg, audio]
    cortes = ed.get("cortes")
    if cortes and not (len(cortes) == 1 and cortes[0][0] <= .01 and cortes[0][1] >= total - .05):
        fora, pos = [], 0.0
        for a, b in cortes:
            if a > pos:
                fora.append((pos, a))
            pos = b
        if pos < total:
            fora.append((pos, total))
        remover_intervalos(p, fora)
    return p


def _plano_trecho(p: dict, parte: dict, trecho: dict, saida: float, cena: str, motor, est: dict, faixas: dict) -> None:
    dur, ini, fim = parte["dur"], parte["ini"], parte["fim"]
    fonte = trecho["fonte"]
    rel = fonte.relative_to(motor.saida).as_posix()
    mid = _midia_video(p, rel, fonte, trecho.get("gancho") or "Trecho da live")
    vw, vh, _ = cam.dimensoes(fonte)
    agenda = lg.agendar(dur, trecho["momento"] - ini, efeitos.batidas(fonte, ini, dur), trecho["plano"])
    mov = agenda["mov"]
    W, H = p["largura"], p["altura"]
    if vw / max(vh, 1) < 1.5:
        lado = max(0.0, (1 - (vw * 9 / 16) / vh) / 2)
        faixas["fundo"]["itens"].append(_item_video(mid, saida, dur, ini, "Fundo desfocado", {"x": W / 2, "y": H / 2, "w": W, "h": H, "ct": lado, "cb": lado}, mudo=True, cena=cena, ajustes={"desfoque": 36, "brilho": -22}))
        larg = H * vw / vh
        t = {"x": W / 2, "y": H / 2, "w": round(larg, 1), "h": H}
    else:
        alt = min(H, W * vh / vw)
        t = {"x": W / 2, "y": H / 2, "w": W, "h": round(alt, 1)}
    faixas["video"]["itens"].append(_item_video(mid, saida, dur, ini, trecho.get("gancho") or "Cena", {**t, **_base(mov)}, _chaves(mov), cena=cena,
                                                transicao={"tipo": parte["entrada"], "dur": .6} if parte.get("entrada") else None))
    for nome, a, b in agenda["cenas"]:
        if nome in ("webcam", "reacao") and agenda["foco"]:
            faixas["efx"]["itens"].append(_efeito(saida + max(0, a), b - max(0, a), "vinheta", "Foco na webcam", 1.0, cena=cena))
    faixas["efx"]["itens"].append(_efeito(saida + agenda["momento"], min(1.2, dur - agenda["momento"]), "clarao", "Clarão na reação", .7, cena=cena))
    faixas["efx"]["itens"].append(_efeito(saida + agenda["momento"], min(1.2, dur - agenda["momento"]), "tremor", "Tremor na reação", 10.0, cena=cena))
    faixas["leg"]["itens"] += legendas_de(lg._na_janela(parte.get("grupos") or trecho["grupos"], ini, fim), saida, dur, cena)
    tx = faixas["txt"]["itens"]
    cor_d = "#" + estilos.CORES[est["cor"]]
    if trecho["meta"].get("credito"):
        tx.append(_item_texto("texto", saida, dur, trecho["meta"]["credito"], 1740, 1038, {"tamanho": 24, "opacidade": 75, "contorno": 3, "alinhamento": "direita", "largura": 300}, "Crédito", cena=cena))
    if parte.get("etiqueta") and est["gancho"] != "nenhum":
        ex, ey = estilos.ponto(est, "gancho_hx", "gancho_hy", W, H, 70, 70)
        tx.append(_item_texto("texto", saida + .2, min(dur, 3.4) - .2, parte["etiqueta"], ex + 200, ey, {**estilo_titulo(est, 36), "largura": 620}, "Etiqueta", cena=cena, **({"papel": "capitulo"} if parte.get("capitulo") else {})))
    faixa_nome = {"tamanho": 42, "fundo": True, "fundo_cor": "#141414", "fundo_opac": 100, "fundo_pad": 18, "largura": 900, "entrada": "fade", "saida": "fade", "tempo_anim": .2}
    if parte.get("nome"):
        tx.append(_item_texto("texto", saida + .5, min(dur, 5) - .5, parte["nome"], 320, 930, faixa_nome, "Nome do canal", cena=cena))
    elif parte.get("chamada") and dur >= 12:
        tx.append(_item_texto("texto", saida + 5, 5.5, parte["chamada"], 520, 930, {**faixa_nome, "cor": "#141414", "fundo_cor": cor_d, "entrada": "pop"}, "Chamada", cena=cena))
    msgs = [m for m in (trecho["meta"].get("chat_marcante") or []) if 0 < len(m) <= 40][:3]
    if msgs:
        a = min(agenda["momento"] + .4, max(0.0, dur - 3)); b = min(dur - .2, a + 3.6)
        chat = {"tamanho": 34, "fundo": True, "fundo_cor": "#141414", "fundo_opac": 82, "fundo_pad": 14, "alinhamento": "direita", "largura": 760, "entrada": "pop", "saida": "fade"}
        tx.append(_item_texto("texto", saida + a, b - a, "O CHAT REAGIU", 1700, 88, {**chat, "tamanho": 28, "cor": cor_d}, "Chat", cena=cena))
        for n, m in enumerate(msgs):
            tx.append(_item_texto("texto", saida + a + .2 + n * .3, b - a - .2 - n * .3, m, 1600, 168 + n * 78, chat, "Mensagem do chat", cena=cena))
    biblioteca = motor.biblioteca
    for w in agenda["whoosh"]:
        faixas["som"]["itens"].append(_som(p["midias"], "whoosh_rapido", "Whoosh rápido", saida + w, .26, biblioteca, cena))
    for i in agenda["impacto"]:
        faixas["som"]["itens"].append(_som(p["midias"], "boom_grave", "Boom grave", saida + i, .3, biblioteca, cena))


def _plano_cartao(p: dict, parte: dict, saida: float, cena: str, motor, est: dict, faixas: dict, n: int) -> bool:
    c = parte.get("cartao")
    meta = motor.cortes.get(c["corte"]) if c else None
    trechos = lg.criar_trechos([meta], motor.saida) if meta else []
    if not trechos:
        return False
    W, H, dur = p["largura"], p["altura"], parte["dur"]
    fundo = cv2.GaussianBlur(lg._quadro_de(trechos[0]["fonte"], c["instante"]), (0, 0), 22)
    fundo = efeitos.escurecer(cv2.convertScaleAbs(fundo, alpha=.36, beta=4), efeitos.mascara_vinheta(W, H, .6), 1.0)
    pasta = motor.longos.pasta / p["id"] / "midia_projeto"; pasta.mkdir(exist_ok=True)
    cv2.imwrite(str(pasta / f"cartao_{n}.jpg"), fundo, [cv2.IMWRITE_JPEG_QUALITY, 94])
    mid = f"cartao{n}"
    p["midias"][mid] = {"id": mid, "tipo": "imagem", "raiz": "saida", "rel": f"_longos/{p['id']}/midia_projeto/cartao_{n}.jpg", "nome": f"Fundo do cartão {n}", "lar": W, "alt": H}
    faixas["video"]["itens"].append({"id": novo_id(), "tipo": "imagem", "nome": c["marca"] or "Cartão", "midia": mid, "ini": round(saida, 3), "dur": round(dur, 3), "cena": cena, "t": {"x": W / 2, "y": H / 2, "w": W, "h": H, "zoom": 1.0, "zx": .5, "zy": .5},
                                     "kf": {"zoom": [{"t": 0, "v": 1.0, "e": "linear"}, {"t": round(dur, 3), "v": 1.07, "e": "linear"}]}})
    y = 510 if c.get("apoio") else 540
    d = "#" + estilos.CORES[est["cor"]]
    tx = faixas["txt"]["itens"]
    if c.get("marca"):
        tx.append(_item_texto("texto", saida + .1, dur - .2, c["marca"].upper(), W / 2, y - 215, {"tamanho": 46, "cor": d, "espacamento": 6, "largura": 1500, "entrada": "fade", "saida": "fade", "tempo_anim": .18}, "Marca", cena=cena))
    tx.append(_item_texto("texto", saida + .2, dur - .3, c["titulo"].upper(), W / 2, y, {"tamanho": 124, "largura": 1580, "sombra": True, "sombra_y": 6, "entrada": "zoom", "saida": "fade", "tempo_anim": .3}, "Título da cena", cena=cena, papel="capitulo"))
    if c.get("apoio"):
        tx.append(_item_texto("texto", saida + .55, max(.2, dur - .65), c["apoio"], W / 2, 790, {"fonte": "Poppins-Regular", "tamanho": 52, "cor": "#E8D4D8", "largura": 1480, "entrada": "fade", "saida": "fade", "tempo_anim": .26}, "Texto de apoio", cena=cena))
    faixas["som"]["itens"].append(_som(p["midias"], "whoosh_rapido", "Whoosh rápido", saida, .3, motor.biblioteca, cena))
    return True


def importar_longo(item: dict, motor) -> dict:
    pasta = motor.longos.pasta / item["id"]
    base = pasta / "base.mp4" if (pasta / "base.mp4").exists() else pasta / "video.mp4"
    est = estilos.normalizar(item.get("estilo"), motor.config["estilo"])
    p = _vazio("longo", item["id"], item.get("titulo") or "Vídeo longo", 1920, 1080, est)
    p["global"]["legenda"] = estilo_legenda(est, 1920, 1080)
    faixas = {"fundo": _faixa("video", "Fundo"), "video": _faixa("video", "Vídeo"), "efx": _faixa("efeito", "Efeitos"), "txt": _faixa("texto", "Textos"), "leg": _faixa("legenda", "Legendas"), "som": _faixa("audio", "Efeitos sonoros")}
    rel = base.relative_to(motor.saida).as_posix()
    medido = cam.dimensoes(base)[2] or item.get("duracao") or 0
    partes = item.get("partes") or [{"tipo": "plano", "saida": 0.0, "dur": medido}]
    nomes = sorted(item.get("capitulos_base") or item.get("capitulos") or [], key=lambda c: c["t"])

    def titulo_em(t: float, n: int) -> str:
        atual = [c["titulo"] for c in nomes if c["t"] <= t + .3]
        return atual[-1] if atual else f"Cena {n}"

    for n, parte in enumerate(partes, 1):
        cena = novo_id("c")
        p["cenas"].append({"id": cena, "nome": titulo_em(parte["saida"], n)})
        feito = False
        if parte["tipo"] == "trecho":
            meta = motor.cortes.get(parte.get("corte"))
            trechos = lg.criar_trechos([meta], motor.saida) if meta else []
            if trechos and (trechos[0]["fonte"]).exists():
                _plano_trecho(p, parte, {**trechos[0], "grupos": parte.get("grupos") or trechos[0]["grupos"], "momento": parte.get("momento", 0) + parte["ini"]}, parte["saida"], cena, motor, est, faixas)
                feito = True
        elif parte["tipo"] == "cartao":
            feito = _plano_cartao(p, parte, parte["saida"], cena, motor, est, faixas, n)
        if not feito:  # o corte original foi apagado: a cena segue editável como um bloco de vídeo
            mid = _midia_video(p, rel, base, "Vídeo pronto")
            faixas["video"]["itens"].append(_item_video(mid, parte["saida"], parte["dur"], parte["saida"], p["cenas"][-1]["nome"], {"x": 960, "y": 540, "w": 1920, "h": 1080}, cena=cena))
    p["faixas"] = [f for f in faixas.values() if f["itens"] or f["tipo"] in ("video", "legenda", "texto", "audio")]
    ed = item.get("edicao") or {}
    if ed.get("filtro"):
        p["global"]["filtro"] = {"nome": ed["filtro"], "forca": ed.get("intensidade", 100)} if ed["filtro"] != "nenhum" else None
    for s in ed.get("sons") or []:
        if motor.biblioteca.existe(s["som"]):
            faixas["som"]["itens"].append(_som(p["midias"], s["som"], motor.biblioteca.nome(s["som"]), float(s["t"]), float(s["volume"]), motor.biblioteca))
    if ed.get("cortes"):
        fora, pos = [], 0.0
        for a, b in ed["cortes"]:
            if a > pos + .01:
                fora.append((pos, a))
            pos = b
        total = duracao_projeto(p)
        if pos < total - .01:
            fora.append((pos, total))
        remover_intervalos(p, fora)
    return p


# ------------------------------------------------------------ operações usadas também pelo assistente

def partir_item(item: dict, t: float) -> tuple[dict, dict]:
    """Divide o elemento no instante `t` da timeline, sem mudar o que aparece na tela."""
    u = t - item["ini"]
    a, b = copy.deepcopy(item), copy.deepcopy(item)
    b["id"] = novo_id()
    a["dur"], b["ini"], b["dur"] = round(u, 3), round(t, 3), round(item["dur"] - u, 3)
    if "entrada" in b:
        b["entrada"] = round(b.get("entrada", 0.0) + u * b.get("velocidade", 1.0), 3)
    b.pop("transicao", None)
    for prop, chaves in (item.get("kf") or {}).items():
        v = valor(item, prop, u)
        a["kf"][prop] = [k for k in chaves if k["t"] < u] + [{"t": round(u, 3), "v": round(v, 4), "e": "linear"}]
        b["kf"][prop] = [{"t": 0.0, "v": round(v, 4), "e": "linear"}] + [{**k, "t": round(k["t"] - u, 3)} for k in chaves if k["t"] > u]
    if item.get("palavras"):
        a["palavras"] = [w for w in item["palavras"] if w["ini"] < u]
        b["palavras"] = [{**w, "ini": round(max(0.0, w["ini"] - u), 3), "fim": round(w["fim"] - u, 3)} for w in item["palavras"] if w["ini"] >= u]
        a["texto"], b["texto"] = " ".join(w["p"] for w in a["palavras"]), " ".join(w["p"] for w in b["palavras"])
    return a, b


def remover_intervalos(proj: dict, intervalos: list[tuple[float, float]]) -> None:
    """Apaga trechos do tempo e aproxima o que vem depois."""
    for ini, fim in sorted(intervalos, reverse=True):
        d = fim - ini
        for faixa in proj["faixas"]:
            novos = []
            for item in faixa["itens"]:
                i0, i1 = item["ini"], item["ini"] + item["dur"]
                if i1 <= ini:
                    novos.append(item)
                elif i0 >= fim:
                    item["ini"] = round(i0 - d, 3); novos.append(item)
                elif faixa["tipo"] == "audio" and item.get("categoria") == "efeito":
                    if ini <= i0 < fim:
                        continue  # o efeito sonoro saiu junto com o trecho
                    novos.append(item)
                else:
                    resto = item
                    if i0 < ini:
                        antes, resto = partir_item(resto, ini)
                        novos.append(antes)
                    if i1 > fim:
                        _, depois = partir_item(resto, fim)
                        depois["ini"] = round(fim - d, 3)
                        novos.append(depois)
            faixa["itens"] = [i for i in novos if i["dur"] >= .04 and (i["tipo"] != "legenda" or i.get("texto", "").strip())]


def caminho(pasta: Path) -> Path:
    return pasta / "projeto.json"


def salvar(pasta: Path, proj: dict) -> None:
    proj["modificado"] = time.time()
    arq = caminho(pasta)
    temp = arq.with_suffix(".tmp")
    temp.write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
    if arq.exists():
        arq.replace(pasta / "projeto.anterior.json")
    temp.replace(arq)


def carregar(pasta: Path) -> dict | None:
    for nome in ("projeto.json", "projeto.anterior.json"):
        try:
            return json.loads((pasta / nome).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def validar(proj: dict) -> dict:
    if not isinstance(proj, dict) or proj.get("formato") != FORMATO or not isinstance(proj.get("faixas"), list) or not isinstance(proj.get("midias"), dict):
        raise ValueError("Projeto inválido.")
    for faixa in proj["faixas"]:
        if faixa.get("tipo") not in ("video", "texto", "legenda", "efeito", "audio") or not isinstance(faixa.get("itens"), list):
            raise ValueError("Projeto inválido.")
        for item in faixa["itens"]:
            if not isinstance(item.get("ini"), (int, float)) or not isinstance(item.get("dur"), (int, float)) or item["dur"] <= 0:
                raise ValueError("Um elemento do projeto está sem tempo válido.")
            for chaves in (item.get("kf") or {}).values():
                chaves.sort(key=lambda k: k["t"])
    return proj
