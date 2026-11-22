"""Ferramentas extras do estúdio.

- XML para Premiere Pro e DaVinci Resolve (com as legendas em .srt ao lado);
- tradução das legendas para outro idioma;
- tira de miniaturas para os clipes da timeline;
- congelar quadro;
- enquadrar no rosto e tela dividida para duas pessoas;
- batidas da música e prévia de um efeito de áudio.
"""
from __future__ import annotations

import io
import json
import math
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
import wave
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import cv2
import numpy as np

from . import audio_fx
from . import camera as cam
from . import compositor as comp
from . import efeitos
from .plataformas import sem_janela


# ------------------------------------------------------------ XML (Final Cut 7 / Premiere / DaVinci)

def _quadros(seg: float, fps: int) -> int:
    return int(round(seg * fps))


def _taxa(fps: int) -> str:
    return f"<rate><timebase>{fps}</timebase><ntsc>FALSE</ntsc></rate>"


def _parametro(pid: str, nome: str, valor: str, vmin: str = "", vmax: str = "") -> str:
    faixa = (f"<valuemin>{vmin}</valuemin><valuemax>{vmax}</valuemax>" if vmin != "" else "")
    return f"<parameter><parameterid>{pid}</parameterid><name>{nome}</name>{faixa}<value>{valor}</value></parameter>"


def _movimento(item: dict, w: int, h: int, W: int, H: int, zoom_global: float) -> str:
    """Escala, centro, rotação, recorte e opacidade do clipe no início dele."""
    v = lambda p: comp.valor(item, p, 0.0)
    cl, ct, cr, cb = (float(np.clip(v(k), 0, .95)) for k in ("cl", "ct", "cr", "cb"))
    fx0, fx1, fy0, fy1 = cl, max(cl + .01, 1 - cr), ct, max(ct + .01, 1 - cb)
    z = max(1.0, 1 + (v("zoom") - 1) * zoom_global * item.get("zoom_forca", 100) / 100)
    lx, ly = (fx1 - fx0) / z, (fy1 - fy0) / z
    zx = float(np.clip(fx0 + v("zx") * (fx1 - fx0), fx0 + lx / 2, fx1 - lx / 2))
    zy = float(np.clip(fy0 + v("zy") * (fy1 - fy0), fy0 + ly / 2, fy1 - ly / 2))
    sx0, sx1, sy0, sy1 = (zx - lx / 2) * w, (zx + lx / 2) * w, (zy - ly / 2) * h, (zy + ly / 2) * h
    esc = v("escala")
    bw, bh = v("w") * esc, v("h") * esc
    k = bw / max(1e-6, sx1 - sx0)
    cx = v("x") + (w / 2 - (sx0 + sx1) / 2) * k
    cy = v("y") + (h / 2 - (sy0 + sy1) / 2) * (bh / max(1e-6, sy1 - sy0))
    movimento = ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory>"
                 "<effecttype>motion</effecttype><mediatype>video</mediatype>"
                 + _parametro("scale", "Scale", f"{k * 100:.3f}", "0", "1000")
                 + _parametro("rotation", "Rotation", f"{v('rot'):.3f}", "-8640", "8640")
                 + f"<parameter><parameterid>center</parameterid><name>Center</name><value><horiz>{(cx - W / 2) / W:.5f}</horiz><vert>{(cy - H / 2) / H:.5f}</vert></value></parameter>"
                 + "</effect></filter>")
    recorte = ("<filter><effect><name>Crop</name><effectid>crop</effectid><effectcategory>motion</effectcategory>"
               "<effecttype>motion</effecttype><mediatype>video</mediatype>"
               + _parametro("left", "left", f"{sx0 / w * 100:.3f}", "0", "100") + _parametro("right", "right", f"{(w - sx1) / w * 100:.3f}", "0", "100")
               + _parametro("top", "top", f"{sy0 / h * 100:.3f}", "0", "100") + _parametro("bottom", "bottom", f"{(h - sy1) / h * 100:.3f}", "0", "100")
               + "</effect></filter>")
    opac = v("opac")
    opacidade = ("" if opac >= 99.9 else "<filter><effect><name>Opacity</name><effectid>opacity</effectid><effectcategory>motion</effectcategory>"
                 "<effecttype>motion</effecttype><mediatype>video</mediatype>" + _parametro("opacity", "opacity", f"{opac:.2f}", "0", "100") + "</effect></filter>")
    return movimento + recorte + opacidade


def _velocidade(item: dict) -> str:
    vel = float(item.get("velocidade", 1) or 1)
    if abs(vel - 1) < 1e-3:
        return ""
    return ("<filter><effect><name>Time Remap</name><effectid>timeremap</effectid><effectcategory>motion</effectcategory>"
            "<effecttype>motion</effecttype><mediatype>video</mediatype>"
            + _parametro("variablespeed", "variablespeed", "0", "0", "1") + _parametro("speed", "speed", f"{vel * 100:.2f}", "-100000", "100000")
            + _parametro("reverse", "reverse", "FALSE") + "</effect></filter>")


def exportar_xml(proj: dict, midias, nome: str) -> tuple[bytes, str]:
    """Gera um .zip com o XML da timeline (vídeos, imagens e sons) e as legendas em .srt."""
    from .edicao import gerar_srt

    fps = int(proj.get("fps", 30))
    W, H = int(proj["largura"]), int(proj["altura"])
    total = comp.duracao_projeto(proj)
    zoom_global = proj["global"].get("zoom_forca", 100) / 100
    arquivos: dict[str, dict] = {}

    def arquivo(mid: str) -> dict | None:
        m = proj["midias"].get(mid)
        if not m:
            return None
        if mid not in arquivos:
            try:
                caminho = midias.caminho(m)
            except (ValueError, KeyError):
                return None
            if not caminho.exists():
                return None
            lar, alt = m.get("lar"), m.get("alt")
            dur = m.get("dur") or 0
            if m["tipo"] == "video" and not (lar and alt and dur):
                try:
                    lar, alt, dur = cam.dimensoes(caminho)
                except (IndexError, ValueError):
                    return None
            if m["tipo"] == "imagem" and not (lar and alt):
                im = cv2.imread(str(caminho))
                if im is None:
                    return None
                alt, lar = im.shape[:2]
            arquivos[mid] = {"id": f"arquivo-{len(arquivos) + 1}", "caminho": caminho, "lar": int(lar or W), "alt": int(alt or H),
                             "dur": float(dur or 3600), "tipo": m["tipo"], "nome": m.get("nome") or caminho.stem, "usado": False}
        return arquivos[mid]

    def bloco_arquivo(a: dict) -> str:
        if a["usado"]:
            return f'<file id="{a["id"]}"/>'
        a["usado"] = True
        dur_q = _quadros(a["dur"], fps)
        video = "" if a["tipo"] == "audio" else f"<video><samplecharacteristics><width>{a['lar']}</width><height>{a['alt']}</height></samplecharacteristics></video>"
        audio = "" if a["tipo"] == "imagem" else "<audio><samplecharacteristics><depth>16</depth><samplerate>48000</samplerate></samplecharacteristics><channelcount>2</channelcount></audio>"
        return (f'<file id="{a["id"]}"><name>{escape(a["caminho"].name)}</name><pathurl>{escape(a["caminho"].resolve().as_uri())}</pathurl>'
                f"{_taxa(fps)}<duration>{dur_q}</duration><media>{video}{audio}</media></file>")

    clipe_n = 0

    def clipe(item: dict, a: dict, video: bool) -> str:
        nonlocal clipe_n
        clipe_n += 1
        ini, fim = _quadros(item["ini"], fps), _quadros(item["ini"] + item["dur"], fps)
        vel = float(item.get("velocidade", 1) or 1)
        entrada = _quadros(item.get("entrada", 0.0), fps)
        saida = entrada + max(1, _quadros(item["dur"] * vel, fps))
        if a["tipo"] == "imagem":
            entrada, saida = 0, fim - ini
        extra = (_movimento(item, a["lar"], a["alt"], W, H, zoom_global) if video and item["tipo"] in ("video", "imagem") else "") + _velocidade(item)
        if not video:
            ganho = (item.get("volume", 100) or 0) / 100
            if item.get("mudo"):
                ganho = 0
            if abs(ganho - 1) > 1e-3:
                db = 20 * math.log10(max(ganho, 1e-4))
                extra += ("<filter><effect><name>Audio Levels</name><effectid>audiolevels</effectid><effectcategory>audiolevels</effectcategory>"
                          "<effecttype>audiolevels</effecttype><mediatype>audio</mediatype>" + _parametro("level", "Level", f"{max(-96.0, db):.2f}", "-96", "12") + "</effect></filter>")
        nome = escape(str(item.get("nome") or a["nome"]))[:80]
        return (f'<clipitem id="clipe-{clipe_n}"><name>{nome}</name><enabled>TRUE</enabled><duration>{_quadros(a["dur"], fps)}</duration>{_taxa(fps)}'
                f"<start>{ini}</start><end>{fim}</end><in>{entrada}</in><out>{saida}</out>{bloco_arquivo(a)}{extra}</clipitem>")

    trilhas_v, trilhas_a = [], []
    for faixa in proj["faixas"]:  # a primeira faixa do projeto é a de baixo, igual à V1 do Premiere
        if faixa["tipo"] == "video":
            clipes, sons = [], []
            for item in sorted(faixa["itens"], key=lambda i: i["ini"]):
                if item["tipo"] not in ("video", "imagem"):
                    continue
                a = arquivo(item.get("midia", ""))
                if not a:
                    continue
                clipes.append(clipe(item, a, True))
                if item["tipo"] == "video" and not item.get("mudo") and not faixa.get("muda"):
                    sons.append(clipe(item, a, False))
            if clipes:
                trilhas_v.append(f"<track>{''.join(clipes)}<enabled>{'FALSE' if faixa.get('oculta') else 'TRUE'}</enabled></track>")
            if sons:
                trilhas_a.append(f"<track>{''.join(sons)}</track>")
        elif faixa["tipo"] == "audio":
            sons = [clipe(item, a, False) for item in sorted(faixa["itens"], key=lambda i: i["ini"]) if (a := arquivo(item.get("midia", "")))]
            if sons:
                trilhas_a.append(f"<track>{''.join(sons)}<enabled>{'FALSE' if faixa.get('muda') else 'TRUE'}</enabled></track>")
    if not trilhas_v:
        raise ValueError("O projeto não tem vídeos para levar ao outro editor.")
    marcadores = "".join(f"<marker><name>Marcador {n + 1}</name><in>{_quadros(t, fps)}</in><out>-1</out></marker>" for n, t in enumerate(sorted(proj.get("marcadores") or [])))
    titulo = escape(nome)[:80] or "Clipador"
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4"><sequence id="sequencia-1">'
           f"<uuid>{uuid.uuid4()}</uuid><name>{titulo}</name><duration>{_quadros(total, fps)}</duration>{_taxa(fps)}"
           f"<timecode>{_taxa(fps)}<string>00:00:00:00</string><frame>0</frame><displayformat>NDF</displayformat></timecode>{marcadores}"
           f"<media><video><format><samplecharacteristics>{_taxa(fps)}<width>{W}</width><height>{H}</height><pixelaspectratio>square</pixelaspectratio>"
           f"<fielddominance>none</fielddominance></samplecharacteristics></format>{''.join(trilhas_v)}</video>"
           f"<audio><numOutputChannels>2</numOutputChannels>{''.join(trilhas_a)}</audio></media></sequence></xmeml>")
    grupos = [{"ini": i["ini"], "fim": i["ini"] + i["dur"], "palavras": [{"p": p["p"], "ini": i["ini"] + p["ini"], "fim": i["ini"] + p["fim"]} for p in (i.get("palavras") or [{"p": i.get("texto", ""), "ini": 0, "fim": i["dur"]}])]}
              for f in proj["faixas"] if f["tipo"] == "legenda" and not f.get("oculta") for i in sorted(f["itens"], key=lambda x: x["ini"]) if i.get("texto", "").strip()]
    textos = [{"ini": i["ini"], "fim": i["ini"] + i["dur"], "palavras": [{"p": i.get("texto", "").replace("\n", " "), "ini": i["ini"], "fim": i["ini"] + i["dur"]}]}
              for f in proj["faixas"] if f["tipo"] == "texto" for i in sorted(f["itens"], key=lambda x: x["ini"]) if i.get("texto", "").strip()]
    base = re.sub(r"[^\w -]", "", nome).strip()[:60] or "projeto"
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{base}.xml", xml)
        if grupos:
            z.writestr(f"{base} - legendas.srt", gerar_srt(grupos))
        if textos:
            z.writestr(f"{base} - textos.srt", gerar_srt(textos))
        z.writestr("LEIA-ME.txt", "No Premiere Pro: Arquivo > Importar > escolha o .xml.\r\nNo DaVinci Resolve: Arquivo > Importar > Timeline > escolha o .xml.\r\n"
                   "As legendas vão no arquivo .srt: arraste para a timeline depois de importar.\r\n"
                   "Os vídeos continuam nas pastas do Clipador; não mova esses arquivos antes de importar.\r\n")
    return saida.getvalue(), f"{base}.zip"


# ------------------------------------------------------------ tradução das legendas

IDIOMAS = {"en": "Inglês", "es": "Espanhol", "pt": "Português", "fr": "Francês", "it": "Italiano", "de": "Alemão", "ja": "Japonês",
           "ko": "Coreano", "zh-CN": "Chinês", "ru": "Russo", "ar": "Árabe", "hi": "Hindi", "tr": "Turco"}


def _traduzir_bloco(texto: str, destino: str) -> str:
    consulta = urllib.parse.urlencode({"client": "gtx", "sl": "auto", "tl": destino, "dt": "t", "q": texto})
    pedido = urllib.request.Request(f"https://translate.googleapis.com/translate_a/single?{consulta}", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(pedido, timeout=20) as r:
            dados = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        raise ValueError("Não consegui falar com o tradutor. Confira a internet e tente de novo.") from e
    return "".join(parte[0] for parte in (dados[0] or []) if parte and parte[0])


def traduzir_textos(textos: list[str], destino: str) -> list[str]:
    """Traduz em lotes, uma linha por legenda; se o lote voltar torto, traduz uma a uma."""
    if destino not in IDIOMAS:
        raise ValueError("Escolha um idioma da lista.")
    saida: list[str] = []
    lote: list[str] = []

    def enviar() -> None:
        if not lote:
            return
        partes = _traduzir_bloco("\n".join(lote), destino).split("\n")
        if len(partes) != len(lote):
            partes = [_traduzir_bloco(t, destino) for t in lote]
        saida.extend(p.strip() for p in partes)
        lote.clear()

    tamanho = 0
    for t in textos:
        t = re.sub(r"\s+", " ", t).strip() or "…"
        if tamanho + len(t) > 3500:
            enviar(); tamanho = 0
        lote.append(t); tamanho += len(t) + 1
    enviar()
    return saida


def traduzir_legendas(proj: dict, destino: str) -> dict:
    """Cria uma faixa nova com as legendas traduzidas e esconde a original."""
    faixa = next((f for f in proj["faixas"] if f["tipo"] == "legenda" and not f.get("oculta") and f["itens"]), None) \
        or next((f for f in proj["faixas"] if f["tipo"] == "legenda" and f["itens"]), None)
    if not faixa:
        raise ValueError("Gere as legendas antes de traduzir.")
    itens = sorted(faixa["itens"], key=lambda i: i["ini"])
    traduzidos = traduzir_textos([i.get("texto", "") for i in itens], destino)
    novos = []
    for item, texto_novo in zip(itens, traduzidos):
        n = json.loads(json.dumps(item))
        n["id"] = "t" + uuid.uuid4().hex[:10]
        n["texto"] = texto_novo
        palavras = texto_novo.split()
        total = sum(len(p) + 1 for p in palavras) or 1
        pos, lista = 0.0, []
        for p in palavras:  # o tempo de cada palavra segue o tamanho dela
            d = n["dur"] * (len(p) + 1) / total
            lista.append({"p": p, "ini": round(pos, 3), "fim": round(pos + d, 3)})
            pos += d
        n["palavras"] = lista
        novos.append(n)
    sigla = destino.split("-")[0].upper()
    nova = {"id": "f" + uuid.uuid4().hex[:10], "tipo": "legenda", "nome": f"Legendas {sigla}", "oculta": False, "muda": False, "travada": False, "itens": novos, "idioma": destino}
    faixa["oculta"] = True
    proj["faixas"].insert(proj["faixas"].index(faixa) + 1, nova)
    return proj


# ------------------------------------------------------------ miniaturas da timeline

def tira(arq: Path, tmp: Path) -> dict:
    """Uma imagem com as miniaturas do vídeo lado a lado, usada para desenhar os clipes na timeline."""
    marca = uuid.uuid5(uuid.NAMESPACE_URL, f"{arq}:{arq.stat().st_mtime_ns}").hex[:20]
    meta = tmp / f"tira_{marca}.json"
    if meta.exists():
        return json.loads(meta.read_text(encoding="utf-8"))
    w, h, dur = cam.dimensoes(arq)
    dur = dur or 1.0
    alt = 60
    lar = int(max(34, min(120, round(alt * w / max(1, h)))))
    n = int(max(1, min(240, math.ceil(dur / 0.5))))
    passo = dur / n
    destino = tmp / f"tira_{marca}.jpg"
    cmd = ["ffmpeg", "-v", "error", "-y"] + (["-skip_frame", "nokey"] if dur > 150 else []) + ["-i", str(arq), "-an",
           "-vf", f"fps={1 / passo:.6f},scale={lar}:{alt}:force_original_aspect_ratio=increase,crop={lar}:{alt},tile={n}x1",
           "-frames:v", "1", "-q:v", "6", str(destino)]
    r = subprocess.run(cmd, capture_output=True, **sem_janela())
    if r.returncode != 0 or not destino.exists():
        raise ValueError("Não consegui criar as miniaturas deste vídeo.")
    dados = {"img": f"/api/estudio/tira.jpg?k={marca}", "n": n, "passo": round(passo, 4), "lar": lar, "alt": alt}
    meta.write_text(json.dumps(dados), encoding="utf-8")
    return dados


# ------------------------------------------------------------ congelar quadro

def congelar(arq: Path, t: float, pasta_midia: Path) -> dict:
    mid = f"u{uuid.uuid4().hex[:12]}"
    destino = pasta_midia / f"{mid}.jpg"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(arq), "-frames:v", "1", "-q:v", "2", str(destino)],
                       capture_output=True, **sem_janela())
    im = cv2.imread(str(destino)) if r.returncode == 0 else None
    if im is None:
        destino.unlink(missing_ok=True)
        raise ValueError("Não consegui pegar este quadro do vídeo.")
    return {"id": mid, "tipo": "imagem", "raiz": "dados", "rel": f"midia/{destino.name}", "nome": "Quadro congelado", "lar": im.shape[1], "alt": im.shape[0]}


# ------------------------------------------------------------ enquadrar no rosto e tela dividida

def _rostos(arq: Path, t: float) -> tuple[list[tuple[float, float, float, float]], int, int]:
    q = comp.quadro_solto(arq, t, 30)
    if q is None:
        raise ValueError("Não consegui ler este momento do vídeo.")
    rostos = [r for r in cam.detectar_rostos(q, 0.5) if r[2] * r[3] > 0.0004]
    return sorted(rostos, key=lambda r: -r[2] * r[3]), q.shape[1], q.shape[0]


def _recorte(rosto, aspecto_px: float, w: int, h: int, folga: float = 3.4) -> dict:
    """Recorte com a proporção da caixa de destino, com o rosto um pouco acima do centro."""
    rx, ry, rw, rh = rosto
    ch = min(h, max(rh * h * folga, h * .25))
    cw = ch * aspecto_px
    if cw > w:
        cw, ch = w, w / aspecto_px
    cx = (rx + rw / 2) * w
    cy = (ry + rh / 2) * h + ch * .08
    x0 = float(np.clip(cx - cw / 2, 0, w - cw)); y0 = float(np.clip(cy - ch / 2, 0, h - ch))
    return {"cl": round(x0 / w, 4), "ct": round(y0 / h, 4), "cr": round(1 - (x0 + cw) / w, 4), "cb": round(1 - (y0 + ch) / h, 4)}


def enquadrar_rostos(proj: dict, midias, item_id: str, t: float, modo: str) -> dict:
    """`modo` "um": o clipe segue o rosto maior. "dois": tela dividida, uma pessoa em cima e outra embaixo.
    "fala": o recorte pula para quem está falando (podcast, conversa)."""
    faixa = item = None
    for f in proj["faixas"]:
        for i in f["itens"]:
            if i.get("id") == item_id:
                faixa, item = f, i
    if not item or item["tipo"] != "video":
        raise ValueError("Selecione um clipe de vídeo.")
    arq = midias.caminho(proj["midias"][item["midia"]])
    if modo == "fala":
        return _seguir_fala(proj, item, arq)
    u = float(np.clip(t - item["ini"], 0, item["dur"]))
    rostos, w, h = _rostos(arq, item.get("entrada", 0.0) + u * item.get("velocidade", 1.0))
    W, H = proj["largura"], proj["altura"]
    limpar = ("cl", "ct", "cr", "cb", "zoom", "zx", "zy", "x", "y", "w", "h", "escala")
    if modo == "um":
        if not rostos:
            raise ValueError("Não encontrei um rosto neste momento. Leve a agulha até um ponto em que a pessoa aparece.")
        for k in limpar:
            (item.get("kf") or {}).pop(k, None)
        item["t"].update(_recorte(rostos[0], W / H, w, h, 2.6), x=W / 2, y=H / 2, w=W, h=H, escala=1, zoom=1, zx=.5, zy=.5)
        return proj
    if len(rostos) < 2:
        raise ValueError("Encontrei só uma pessoa aqui. A tela dividida precisa de dois rostos no mesmo momento.")
    dupla = sorted(rostos[:2], key=lambda r: r[0])  # quem está à esquerda fica em cima, sem trocar de lugar
    copia = json.loads(json.dumps(item))
    copia["id"] = "e" + uuid.uuid4().hex[:10]
    copia["mudo"] = True
    copia.pop("transicao", None)
    for alvo, rosto, y in ((item, dupla[0], H / 4), (copia, dupla[1], H * 3 / 4)):
        for k in limpar:
            (alvo.get("kf") or {}).pop(k, None)
        alvo["t"].update(_recorte(rosto, W / (H / 2), w, h, 2.8), x=W / 2, y=y, w=W, h=H / 2, escala=1, zoom=1, zx=.5, zy=.5)
    nova = {"id": "f" + uuid.uuid4().hex[:10], "tipo": "video", "nome": "Segunda pessoa", "oculta": False, "muda": False, "travada": False, "itens": [copia]}
    proj["faixas"].insert(proj["faixas"].index(faixa) + 1, nova)
    return proj


def _seguir_fala(proj: dict, item: dict, arq: Path) -> dict:
    from .locutor import seguir_quem_fala

    vel = float(item.get("velocidade", 1) or 1)
    fala = seguir_quem_fala(arq, float(item.get("entrada", 0.0)), item["dur"] * vel)
    if not fala:
        raise ValueError("Encontrei só uma pessoa neste clipe. Use Seguir o rosto.")
    w_px, h_px, _ = cam.dimensoes(arq)
    aspecto = comp.valor(item, "w", 0) / max(1.0, comp.valor(item, "h", 0))
    largura = min(1.0, h_px * aspecto / w_px)
    cl, cr = [], []
    for a, b, quem in fala["trechos"]:
        x = float(np.clip(fala["pessoas"][quem]["cx"] - largura / 2, 0, 1 - largura))
        t = round(a / vel, 3)
        cl.append({"t": t, "v": round(x, 4), "e": "degrau"})
        cr.append({"t": t, "v": round(1 - x - largura, 4), "e": "degrau"})
    kf = item.setdefault("kf", {})
    for k in ("cl", "cr", "ct", "cb"):
        kf.pop(k, None)
    item["t"].update(ct=0.0, cb=0.0, cl=cl[0]["v"], cr=cr[0]["v"])
    if len(cl) > 1:
        kf["cl"], kf["cr"] = cl, cr
    return proj


# ------------------------------------------------------------ batidas e prévia de efeito de áudio

def batidas(arq: Path, entrada: float, dur: float, vel: float = 1.0) -> dict:
    pcm = efeitos.ler_pcm(arq, max(0.0, entrada), max(1.0, dur * vel))
    tempos, bpm = audio_fx.batidas(pcm)
    return {"batidas": [round(t / max(.1, vel), 3) for t in tempos if t / max(.1, vel) <= dur], "bpm": bpm}


def ouvir_efeito(arq: Path, entrada: float, dur: float, vel: float, efeito: str | None) -> bytes:
    dados = comp._ler_audio(arq, max(0.0, entrada), max(.5, min(10.0, dur)), max(.25, min(4.0, vel)), efeito)
    pcm = (np.clip(dados, -1, 1) * 32767).astype(np.int16)
    saida = io.BytesIO()
    with wave.open(saida, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(comp.TAXA)
        w.writeframes(pcm.tobytes())
    return saida.getvalue()
