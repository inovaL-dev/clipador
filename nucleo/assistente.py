"""Sugestões de edição. Nada muda no projeto até o usuário aplicar."""
from __future__ import annotations

import cv2

from . import camera as cam
from . import texto
from .compositor import Compositor, duracao_projeto, estilo_de, quadro_solto, valor
from .projeto import novo_id, remover_intervalos


def _palavras(proj: dict) -> list[tuple[float, float]]:
    tempos = []
    for f in proj["faixas"]:
        if f["tipo"] == "legenda":
            for i in f["itens"]:
                ps = i.get("palavras") or [{"ini": 0, "fim": i["dur"]}]
                tempos += [(i["ini"] + p["ini"], i["ini"] + p["fim"]) for p in ps]
    return sorted(tempos)


def _sug(tipo: str, titulo: str, detalhe: str, t: float, acao: dict) -> dict:
    return {"id": novo_id("s"), "tipo": tipo, "titulo": titulo, "detalhe": detalhe, "t": round(t, 2), "acao": acao}


def _relogio(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def zooms(proj: dict, midias) -> list[dict]:
    saida = []
    analisados = 0
    for f in proj["faixas"]:
        if f["tipo"] != "video":
            continue
        for item in f["itens"]:
            chaves = (item.get("kf") or {}).get("zoom") or []
            picos = [k for n, k in enumerate(chaves) if k["v"] > 1.12 and (n == 0 or chaves[n - 1]["v"] < k["v"])]
            for k in picos[:6]:
                if analisados >= 36 or item["tipo"] != "video":
                    break
                analisados += 1
                u = min(item["dur"] - .05, k["t"] + .1)
                t_global = item["ini"] + u
                fim = next((c["t"] for c in chaves if c["t"] > k["t"] and c["v"] <= 1.1), item["dur"])
                z = valor(item, "zoom", u)
                if z > 2.4:
                    saida.append(_sug("zoom", "Zoom muito forte", f"Em {_relogio(t_global)}, o zoom chega a {z:.1f}x e a imagem perde qualidade.", t_global, {"tipo": "zoom_limite", "item": item["id"], "maximo": 1.8}))
                mid = proj["midias"].get(item.get("midia"))
                q = quadro_solto(midias.caminho(mid), item.get("entrada", 0) + u * item.get("velocidade", 1), proj.get("fps", 30)) if mid else None
                if q is None:
                    continue
                cl, ct, cr, cb = (valor(item, c, u) for c in ("cl", "ct", "cr", "cb"))
                h, w = q.shape[:2]
                parte = q[int(ct * h):max(int(ct * h) + 2, int((1 - cb) * h)), int(cl * w):max(int(cl * w) + 2, int((1 - cr) * w))]
                rostos = cam.detectar_rostos(parte)
                if not rostos:
                    continue
                x, y, rw, rh = max(rostos, key=lambda r: r[2] * r[3])
                rx, ry = x + rw / 2, y + rh / 2
                zx, zy = valor(item, "zx", u), valor(item, "zy", u)
                if abs(rx - zx) > .36 / z or abs(ry - zy) > .36 / z:
                    saida.append(_sug("zoom", "Zoom fora do rosto", f"Em {_relogio(t_global)}, o zoom está cortando o rosto. Centralizar nele.", t_global,
                                      {"tipo": "zoom_foco", "item": item["id"], "t0": k["t"], "t1": fim, "zx": round(rx, 4), "zy": round(ry, 4)}))
    return saida


def legendas_sobre_rostos(proj: dict, midias) -> list[dict]:
    leg = [i for f in proj["faixas"] if f["tipo"] == "legenda" and not f.get("oculta") for i in f["itens"]]
    if not leg:
        return []
    so_video = {**proj, "faixas": [f for f in proj["faixas"] if f["tipo"] == "video"]}
    comp = Compositor(so_video, midias, .5, solto=True)
    W, H = proj["largura"], proj["altura"]
    passo = max(1, len(leg) // 30)
    rostos_vistos, conflitos = [], []
    for item in leg[::passo]:
        q = comp.quadro(item["ini"] + item["dur"] / 2)
        rostos = [(x * W, y * H, w * W, h * H) for x, y, w, h in cam.detectar_rostos(q) if w * h > .002]
        rostos_vistos += rostos
        est = estilo_de(proj, item)
        spr = texto.desenhar(item["texto"], est, 1.0)
        th, tw = spr.shape[:2]
        x0 = est.get("x", W / 2) - tw / 2
        y0 = est.get("y", H * .86) - (th if est["ancora"] == "base" else 0 if est["ancora"] == "topo" else th / 2)
        if any(x0 < rx + rw and x0 + tw > rx and y0 < ry + rh and y0 + th > ry for rx, ry, rw, rh in rostos):
            conflitos.append(item)
    if not conflitos:
        return []
    alturas = [H * .86, H * .93, H * .7, H * .55, H * .2]
    livre = next((y for y in alturas if not any(y - 120 < ry + rh and y + 20 > ry for _, ry, _, rh in rostos_vistos)), alturas[1])
    return [_sug("legenda", "Legendas cobrindo rostos", f"{len(conflitos)} legendas passam por cima de um rosto. Mover todas para um lugar livre.", conflitos[0]["ini"], {"tipo": "legenda_y", "y": round(livre)})]


def pausas(proj: dict, minimo: float = 1.0) -> list[dict]:
    tempos = _palavras(proj)
    saida = []
    for (_, a), (b, _) in zip(tempos, tempos[1:]):
        if b - a >= minimo:
            saida.append(_sug("pausa", f"Pausa de {b - a:.1f} s", f"Em {_relogio(a)}, ninguém fala por {b - a:.1f} segundos. Cortar o silêncio.", a, {"tipo": "cortar", "ini": round(a + .18, 3), "fim": round(b - .12, 3)}))
    return saida[:40]


def ritmo(proj: dict) -> list[dict]:
    tempos = _palavras(proj)
    cortes = [[round(a + .12, 3), round(b - .08, 3)] for (_, a), (b, _) in zip(tempos, tempos[1:]) if b - a >= .45]
    ganho = sum(b - a for a, b in cortes)
    if ganho < 1:
        return []
    return [_sug("ritmo", "Deixar o ritmo mais rápido", f"Tira todas as pausas curtas da narração e reduz o vídeo em {ganho:.0f} segundos.", 0, {"tipo": "cortar_varios", "intervalos": cortes})]


def sincronia(proj: dict) -> list[dict]:
    inicios = [a for a, _ in _palavras(proj)]
    if not inicios:
        return []
    moves = {}
    for f in proj["faixas"]:
        if f["tipo"] in ("audio", "efeito"):
            for i in f["itens"]:
                if i.get("categoria", "efeito") != "efeito" or i.get("efeito") in ("progresso", "escurecer", "clarear"):
                    continue
                perto = min(inicios, key=lambda v: abs(v - i["ini"]))
                if .05 < abs(perto - i["ini"]) <= .35:
                    moves[i["id"]] = round(perto, 3)
    if not moves:
        return []
    return [_sug("sincronia", "Sincronizar efeitos com a fala", f"{len(moves)} efeitos estão um pouco fora do início das palavras. Alinhar com a fala.", 0, {"tipo": "mover", "itens": moves})]


def consistencia(proj: dict) -> list[dict]:
    legendas = [i for f in proj["faixas"] if f["tipo"] == "legenda" for i in f["itens"]]
    diferentes = [i["id"] for i in legendas if i.get("estilo")]
    if diferentes:
        return [_sug("estilo", "Padronizar as legendas", f"{len(diferentes)} legendas têm estilo próprio. Usar o estilo global em todas.", 0, {"tipo": "limpar_estilo", "itens": diferentes})]
    return []


def analisar(proj: dict, midias) -> list[dict]:
    return [*zooms(proj, midias), *legendas_sobre_rostos(proj, midias), *ritmo(proj), *pausas(proj), *sincronia(proj), *consistencia(proj)]


def aplicar(proj: dict, sugestoes: list[dict]) -> dict:
    por_id = {i["id"]: i for f in proj["faixas"] for i in f["itens"]}
    cortes = []
    for s in sugestoes:
        a = s["acao"]
        tipo = a["tipo"]
        if tipo == "zoom_limite" and a["item"] in por_id:
            item = por_id[a["item"]]
            for k in (item.get("kf") or {}).get("zoom", []):
                k["v"] = min(k["v"], a["maximo"])
            item["t"]["zoom"] = min(item["t"].get("zoom", 1), a["maximo"])
        elif tipo == "zoom_foco" and a["item"] in por_id:
            item = por_id[a["item"]]
            for prop, v in (("zx", a["zx"]), ("zy", a["zy"])):
                atuais = item.setdefault("kf", {}).get(prop) or []
                u0, u1 = a["t0"], a["t1"]
                antes, depois = valor(item, prop, max(0, u0 - .15)), valor(item, prop, min(item["dur"], u1 + .15))
                fica = [k for k in atuais if k["t"] < u0 - .15 or k["t"] > u1 + .15]
                novos = [{"t": max(0, u0 - .15), "v": antes, "e": "suave"}, {"t": u0, "v": v, "e": "linear"}, {"t": u1, "v": v, "e": "suave"}, {"t": min(item["dur"], u1 + .15), "v": depois, "e": "linear"}]
                item["kf"][prop] = sorted(fica + novos, key=lambda k: k["t"])
        elif tipo == "legenda_y":
            proj["global"]["legenda"]["y"] = a["y"]
            for f in proj["faixas"]:
                if f["tipo"] == "legenda":
                    for i in f["itens"]:
                        (i.get("estilo") or {}).pop("y", None)
        elif tipo == "cortar":
            cortes.append((a["ini"], a["fim"]))
        elif tipo == "cortar_varios":
            cortes += [tuple(x) for x in a["intervalos"]]
        elif tipo == "mover":
            for ident, t in a["itens"].items():
                if ident in por_id:
                    por_id[ident]["ini"] = t
        elif tipo == "limpar_estilo":
            for ident in a["itens"]:
                if ident in por_id:
                    por_id[ident]["estilo"] = {}
    if cortes:
        cortes.sort()
        juntos = [list(cortes[0])]
        for a, b in cortes[1:]:
            if a <= juntos[-1][1]:
                juntos[-1][1] = max(juntos[-1][1], b)
            else:
                juntos.append([a, b])
        remover_intervalos(proj, [(a, b) for a, b in juntos if b - a > .05 and a < duracao_projeto(proj)])
    return proj
