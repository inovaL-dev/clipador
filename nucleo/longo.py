"""Transforma os melhores cortes em um vídeo horizontal com começo, meio e fim."""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from . import camera as cam
from . import edicao, efeitos, estilos, filtros, transicoes
from . import timeline as tl
from .contexto import FORTES, _encurtar, _nucleo, ajustar_a_frases, frases, quebrar_linhas
from .plataformas import sem_janela
from .publicacao import ASSUNTOS, JOGOS, _hashtag, _limpar
from .youtube import URL_ENVIO, ErroYouTube, _erro_da_resposta, _pedir

L, A = 1920, 1080
FPS = efeitos.FPS
MINIMO_CORTES = 3
DURACOES = (5, 8, 10, 15, 20, 30)
PAUSA_SESSAO = 4 * 3600
FATOR_AUTO = 0.9
INTERVALO_AUTO = 15
ESPERA_FIM_LIVE = 600
AMARELO = "&H33C9FF&"
TITULOS_REACAO = {
    "risada": "O chat não parou de rir", "choque": "Ninguém esperava por isso", "jogo": "A ação começa de verdade",
    "hype": "O chat foi à loucura", "clipe": "O momento que todo mundo pediu", "admirado": "Sem palavras",
    "streamer": "A reação que parou a live", "destaque": "O ponto alto", "manual": "Olha o que aconteceu",
}
TITULOS_ASSUNTO = {
    "O MAPA": "Explorando o mapa", "A POLÍCIA": "A polícia entra em cena", "OS CARROS": "Pé no acelerador",
    "OS TIROS": "A troca de tiros", "OS GRÁFICOS": "Os detalhes impressionam", "A HISTÓRIA": "A história avança",
    "OS PERSONAGENS": "Os personagens aparecem", "A JOGABILIDADE": "Testando tudo no controle",
}
RESERVAS = ["As coisas esquentam", "Mais uma surpresa", "Ninguém segura", "A situação complica", "Só piora", "A virada"]
TEXTO_CAPA = {
    "risada": "NÃO AGUENTOU", "choque": "NINGUÉM ESPERAVA", "jogo": "OLHA ISSO", "hype": "O CHAT EXPLODIU",
    "admirado": "SEM PALAVRAS", "streamer": "OLHA A REAÇÃO", "clipe": "CLIPA ISSO", "destaque": "O MELHOR MOMENTO",
}


def _relogio(s: float) -> str:
    s = int(s)
    h, m = s // 3600, s % 3600 // 60
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"


def _tempo_ass(s: float) -> str:
    cs = max(0, round(s * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _texto(t: str) -> str:
    return re.sub(r"[{}\\]", "", t or "").strip()


# ------------------------------------------------------------ história

def _palavras(trecho: dict) -> list[dict]:
    return [p for g in trecho["grupos"] for p in g.get("palavras", [])]


def _tempo_real(meta: dict) -> float:
    return float(meta["pos_live"]) if meta.get("pos_live") is not None else float(meta["criado"])


def criar_trechos(cortes: list[dict], saida: Path) -> list[dict]:
    trechos = []
    for m in cortes:
        fonte = saida / m["id"] / "fonte.mp4"
        duracao = float(m.get("duracao_fonte") or m.get("duracao") or 0)
        if m.get("status") != "pronto" or m.get("montagem") or duracao < 6 or not fonte.exists():
            continue
        momento = m.get("momento_fonte")
        trechos.append({
            "id": m["id"], "fonte": fonte, "ini": 0.0, "fim": duracao, "forca": float(m.get("forca") or 0),
            "momento": float(momento) if momento is not None else duracao * 0.62, "grupos": m.get("grupos") or [],
            "t": _tempo_real(m), "gancho": m.get("gancho") or "", "reacao": m.get("reacao") or "destaque",
            "plano": m.get("plano") or {"layout": "inteiro"}, "meta": m,
        })
    return sorted(trechos, key=lambda x: x["t"])


def tirar_repeticoes(trechos: list[dict]) -> list[dict]:
    """Dois cortes próximos podem repetir a mesma fala: o seguinte começa depois dela."""
    saida: list[dict] = []
    for atual in trechos:
        novas = [_nucleo(p["p"]) for p in _palavras(atual)]
        descartar = False
        for anterior in saida[-3:]:
            antigas = [_nucleo(p["p"]) for p in _palavras(anterior)]
            if len(novas) >= 6 and antigas:
                conjunto = set(antigas)
                if sum(1 for n in novas if n in conjunto) / len(novas) >= 0.85:
                    descartar = True
                    break
            maior = 0
            for k in range(min(len(antigas), len(novas)), 4, -1):
                if antigas[-k:] == novas[:k]:
                    maior = k
                    break
            if maior:
                resto = _palavras(atual)[maior:]
                proxima = next((f["ini"] for f in frases(resto)), None)  # continua em uma frase inteira
                atual = {**atual, "ini": max(atual["ini"], float(proxima if proxima is not None else _palavras(atual)[maior - 1]["fim"]) - 0.05)}
        if not descartar and atual["fim"] - atual["ini"] >= 8:
            saida.append(atual)
    return saida


def selecionar(trechos: list[dict], alvo: float) -> list[dict]:
    """Fica com os momentos mais fortes até preencher o tempo e devolve na ordem em que aconteceram."""
    ordem = sorted(trechos, key=lambda x: x["forca"] + (15 if x["grupos"] else 0), reverse=True)
    escolhidos, soma = [], 0.0
    for t in ordem:
        if soma >= alvo:
            break
        escolhidos.append(t)
        soma += t["fim"] - t["ini"]
    return sorted(escolhidos, key=lambda x: x["t"])


def _assunto(trechos: list[dict]) -> tuple | None:
    fala = " ".join(p["p"] for t in trechos for p in _palavras(t))
    achados = [(len(re.findall(a[0], fala, re.I)), a) for a in ASSUNTOS]
    melhor = max(achados, key=lambda x: x[0], default=(0, None))
    return melhor[1] if melhor[0] >= 2 else None


def dividir_capitulos(trechos: list[dict]) -> list[list[dict]]:
    quantos = max(2, min(8, round(len(trechos) / 3)))
    if len(trechos) <= quantos:
        return [[t] for t in trechos]
    pausas = sorted(range(1, len(trechos)), key=lambda i: trechos[i]["t"] - trechos[i - 1]["t"], reverse=True)
    if trechos[pausas[0]]["t"] - trechos[pausas[0] - 1]["t"] >= 120:
        cortes = sorted(pausas[: quantos - 1])
    else:
        cortes = [round(i * len(trechos) / quantos) for i in range(1, quantos)]
    limites = [0, *cortes, len(trechos)]
    return [trechos[a:b] for a, b in zip(limites, limites[1:]) if b > a]


def _frase_contexto(grupo: list[dict]) -> str:
    principal = max(grupo, key=lambda x: x["forca"])
    return f"“{_encurtar(principal['gancho'], 64)}”" if principal["gancho"] else ""


def nomear_capitulos(grupos: list[list[dict]]) -> list[dict]:
    climax = max(range(len(grupos)), key=lambda i: max(t["forca"] for t in grupos[i]))
    usados, reservas, capitulos = set(), list(RESERVAS), []
    for i, grupo in enumerate(grupos):
        assunto = _assunto(grupo)
        principal = max(grupo, key=lambda x: x["forca"])
        opcoes = []
        if i == climax and len(grupos) >= 3:
            opcoes.append("O momento que parou a live")
        if i == 0:
            opcoes.append("Como tudo começou")
        if i == len(grupos) - 1 and len(grupos) >= 3:
            opcoes.append("O final da live")
        if assunto:
            opcoes.append(TITULOS_ASSUNTO[assunto[1]])
        opcoes.append(TITULOS_REACAO.get(principal["reacao"], RESERVAS[0]))
        titulo = next((o for o in opcoes if o not in usados), None)
        while titulo is None:
            candidato = reservas.pop(0) if reservas else f"Parte {i + 1}"
            titulo = candidato if candidato not in usados else None
        usados.add(titulo)
        capitulos.append({"titulo": titulo, "contexto": _frase_contexto(grupo), "trechos": grupo})
    return capitulos


def _jogo(trechos: list[dict]) -> tuple | None:
    base = " ".join(f"{t['meta'].get('titulo_live') or ''} {' '.join(p['p'] for p in _palavras(t))}" for t in trechos)
    return next((j for j in JOGOS if re.search(j[0], base, re.I)), None)


def criar_textos(trechos: list[dict], capitulos: list[dict], tempos: list[tuple[float, str]] | None = None) -> dict:
    meta = trechos[0]["meta"]
    canal = meta.get("canal") or "o streamer"
    s, jogo = canal.upper(), _jogo(trechos)
    principal = max(trechos, key=lambda x: x["forca"])
    if jogo:
        titulo = f"{s} JOGOU {jogo[1].upper()} E ISSO ACONTECEU..."
    elif meta.get("titulo_live"):
        titulo = f"{_encurtar(meta['titulo_live'], 62).upper()}: A LIVE COMPLETA DE {s}"
    else:
        titulo = f"OS MELHORES MOMENTOS DA LIVE DE {s}"
    if len(titulo) > 100:
        titulo = f"OS MELHORES MOMENTOS DE {s}"[:100]
    lugar = f" jogando {jogo[1]}" if jogo else ""
    linhas = [
        f"A história completa da live de {canal}{lugar}, com os momentos que mais fizeram o chat reagir. 🎮🔥", "",
        "💬 Qual foi o melhor momento? Conta aqui nos comentários!",
        "👍 Curta e inscreva-se para ver mais vídeos como este.", "",
    ]
    if tempos:
        linhas += ["⏱️ Capítulos", *[f"{_relogio(t)} {nome}" for t, nome in tempos], ""]
    credito = meta.get("credito") or canal
    linhas.append(f"🎥 Créditos: {credito}")
    if meta.get("link"):
        linhas.append(f"🔗 Live original: {meta['link']}")
    marcas = list(dict.fromkeys([*(jogo[3] if jogo else ["Gaming", "Live"]), _hashtag(canal), "MelhoresMomentos", "Cortes"]))
    linhas += ["", " ".join(f"#{m}" for m in marcas[:8] if m)]
    tags, total = [], 0
    for tag in [*marcas, canal, jogo[1] if jogo else "live", "melhores momentos", "live completa"]:
        if tag and tag not in tags and total + len(tag) + 1 <= 400:
            tags.append(tag)
            total += len(tag) + 1
    capa = TEXTO_CAPA.get(principal["reacao"], "OLHA ISSO")
    return {"titulo": _limpar(titulo)[:100], "descricao": _limpar("\n".join(linhas))[:4900], "tags": tags, "texto_capa": capa}


# ------------------------------------------------------------ enquadramento e movimento

def alvo_webcam(plano: dict) -> dict | None:
    """Janela de zoom que enche a tela só com a webcam."""
    if plano.get("layout") == "tela_cheia":
        r = plano.get("recorte") or {}
        cx = (r.get("x", 0) + r.get("w", 0) / 2) / L if r else 0.5
        return {"cx": min(0.8, max(0.2, cx)), "cy": 0.42, "z": 1.55, "moldura": None}
    moldura = plano.get("moldura")
    if plano.get("layout") not in ("dividido", "pip") or not moldura:
        return None
    x, y, w, h = moldura
    z = float(np.clip(0.98 / max(min(w, h), 0.05), 1.4, 3.6))
    rosto = plano.get("rosto")
    cx, cy = (rosto[0] + rosto[2] / 2, rosto[1] + rosto[3] / 2 - rosto[3] * 0.12) if rosto else (x + w / 2, y + h / 2)
    meia = 0.5 / z
    cx = float(np.clip(cx, x + meia, x + w - meia)) if w > 2 * meia else x + w / 2
    cy = float(np.clip(cy, y + meia, y + h - meia)) if h > 2 * meia else y + h / 2
    return {"cx": cx, "cy": cy, "z": z, "moldura": moldura}


def _centro_jogo(plano: dict) -> tuple[float, float]:
    moldura = plano.get("moldura")
    if not moldura:
        return 0.5, 0.46
    # O zoom parte do canto da webcam para ela continuar inteira na tela.
    return (0.0 if moldura[0] + moldura[2] / 2 < 0.5 else 1.0), (1.0 if moldura[1] + moldura[3] / 2 > 0.5 else 0.0)


def agendar(duracao: float, momento: float, picos: list[tuple[float, float]], plano: dict) -> dict:
    """Decide quando aproximar do jogo, quando focar a webcam e onde entram os impactos."""
    quadros = max(1, round(duracao * FPS))
    mov = efeitos.Movimento(quadros, 1.0, 1.05)
    foco = alvo_webcam(plano)
    jogo = _centro_jogo(plano)
    momento = float(np.clip(momento, 0.4, max(0.4, duracao - 0.6)))
    whoosh, cenas, ultimo_foco = [0.0], [], momento
    vez = 0
    for t, _ in picos:
        if abs(t - momento) < 4.5 or t < 1.2 or t > duracao - 2.2:
            continue
        focar = foco is not None and vez % 2 == 1 and abs(t - ultimo_foco) >= 12
        if focar:
            fim = min(duracao - 0.3, t + 2.5)
            mov.plano(t - 0.1, fim, foco["cx"], foco["cy"], foco["z"])
            mov.foco(t - 0.1, fim)
            ultimo_foco = t
            whoosh.append(max(0.0, t - 0.2))
            cenas.append(("webcam", t - 0.1, fim))
        else:
            fim = min(duracao - 0.3, t + 2.0)
            mov.plano(t - 0.1, fim, jogo[0], jogo[1], 1.24)
            cenas.append(("jogo", t - 0.1, fim))
        vez += 1

    fim = min(duracao - 0.2, momento + 3.6)
    ini = max(0.0, momento - 0.2)
    if foco:
        mov.plano(ini, fim, foco["cx"], foco["cy"], foco["z"], entrada=0.14)
        mov.foco(ini, fim)
        cenas.append(("reacao", ini, fim))
    else:
        mov.plano(ini, fim, jogo[0], jogo[1], 1.34, entrada=0.14)
        cenas.append(("reacao", ini, fim))
    mov.impacto(momento, 0.7, 10.0)
    whoosh.append(max(0.0, ini - 0.15))
    # Entrada e saída de cada cena com um clarão rápido.
    entrada = np.clip(1 - mov.t / 0.16, 0, 1) * 0.85
    saida = np.clip(1 - (duracao - mov.t) / 0.14, 0, 1) * 0.85
    mov.clarao = np.maximum(mov.clarao, np.maximum(entrada, saida).astype(np.float32))
    return {"mov": mov, "quadros": quadros, "whoosh": whoosh, "impacto": [momento], "foco": foco, "cenas": cenas, "momento": momento}


def _filtro_horizontal(fonte: Path) -> str:
    largura, altura, _ = cam.dimensoes(fonte)
    if largura / max(altura, 1) >= 1.5:
        base = f"[0:v]scale={L}:{A}:force_original_aspect_ratio=decrease:flags=lanczos,pad={L}:{A}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    else:
        base = (f"[0:v]split=2[a][b];[a]scale={L}:{A}:force_original_aspect_ratio=increase,crop={L}:{A},gblur=sigma=36,"
                f"eq=brightness=-0.22[f];[b]scale={L}:{A}:force_original_aspect_ratio=decrease[d];[f][d]overlay=(W-w)/2:(H-h)/2,setsar=1")
    return f"{base},fps={FPS},format=bgr24[v]"


QUADROS_TRANSICAO = 9


def _quadros_trecho(origem, agenda: dict, progresso, entrada: str = "", saida_cena: str = ""):
    mov = agenda["mov"]
    mascara = efeitos.mascara_vinheta(L, A)
    total, pico = agenda["quadros"], round(agenda["momento"] * FPS)
    for i, quadro in enumerate(origem):
        saida = efeitos.aplicar(quadro, mov.matriz(i, L, A))
        saida = efeitos.escurecer(saida, mascara, float(mov.vinheta[i]))
        saida = efeitos.clarear(saida, float(mov.clarao[i]))
        if 0 <= i - pico < 10:  # a imagem treme em cores na hora da reação
            saida = transicoes.separar_cores(saida, int(26 * (1 - (i - pico) / 10)))
        if entrada and i < QUADROS_TRANSICAO:
            saida = transicoes.aplicar(saida, entrada, 1 - i / QUADROS_TRANSICAO, 1, i)
        if saida_cena and i >= total - QUADROS_TRANSICAO:
            saida = transicoes.aplicar(saida, saida_cena, (i - (total - QUADROS_TRANSICAO) + 1) / QUADROS_TRANSICAO, -1, i)
        yield saida
        progresso()


# ------------------------------------------------------------ textos na tela

def _cabecalho(est: dict) -> list[str]:
    destaque = estilos.cor_ass(est["cor"])
    cor = f"&H00{destaque[2:-1]}"
    return [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {L}", f"PlayResY: {A}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        estilos.estilo_legenda(est, 56), estilos.estilo_gancho(est, 36, "Etiqueta", 7),
        "Style: Nome,Poppins,42,&H00FFFFFF,&H00FFFFFF,&H00141414,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,1,0,0,0,1",
        f"Style: Chamada,Poppins,40,&H00141414,&H00FFFFFF,{cor},&H00000000,-1,0,0,0,100,100,0,0,3,18,0,1,0,0,0,1",
        f"Style: ChatTopo,Poppins,28,{cor},&H00FFFFFF,&H30141414,&H00000000,-1,0,0,0,100,100,1,0,3,14,0,9,0,0,0,1",
        "Style: Chat,Poppins,34,&H00FFFFFF,&H00FFFFFF,&H30141414,&H00000000,-1,0,0,0,100,100,0,0,3,14,0,9,0,0,0,1",
        "Style: Credito,Poppins,24,&H40FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,3,0,0,0,1",
        f"Style: Marca,Poppins,46,{cor},&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,6,0,1,0,0,5,120,120,0,1",
        "Style: Titulo,Poppins,124,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,0,6,5,170,170,0,1",
        "Style: Apoio,Poppins,52,&H00D8D4E8,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,0,3,5,220,220,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]


def _evento(ini: float, fim: float, estilo: str, texto: str, camada: int = 1) -> str:
    return f"Dialogue: {camada},{_tempo_ass(ini)},{_tempo_ass(fim)},{estilo},,0,0,0,,{texto}"


def _na_janela(grupos: list[dict], ini: float, fim: float) -> list[dict]:
    saida = []
    for grupo in grupos:
        palavras = [{"p": p["p"], "ini": max(float(p["ini"]), ini) - ini, "fim": min(float(p["fim"]), fim) - ini}
                    for p in grupo.get("palavras", []) if float(p["fim"]) > ini and float(p["ini"]) < fim]
        if palavras:
            saida.append({"ini": palavras[0]["ini"], "fim": palavras[-1]["fim"], "palavras": palavras})
    return saida


def ass_trecho(grupos: list[dict], ini: float, fim: float, credito: str, agenda: dict, etiqueta: str = "", nome: str = "",
               est: dict | None = None, chat: list[str] | None = None, chamada: str = "") -> str:
    est = estilos.normalizar(est)
    duracao = fim - ini
    x_etiqueta, y_etiqueta = estilos.ponto(est, "gancho_hx", "gancho_hy", L, A, 70, 70)
    x_legenda, y_legenda = estilos.ponto(est, "legenda_hx", "legenda_hy", L, A, 960, 1030)
    linhas = [*_cabecalho(est), _evento(0, duracao, "Credito", f"{{\\pos(1880,1056)}}{_texto(credito)}", 0)]
    if etiqueta and est["gancho"] != "nenhum":
        linhas.append(_evento(0.2, min(duracao, 3.4), "Etiqueta", f"{{\\pos({x_etiqueta},{y_etiqueta})\\fad(0,220){estilos.efeito_gancho(est)}\\fscx88\\fscy88\\t(0,160,\\fscx100\\fscy100)}}{_texto(etiqueta).upper()}", 3))
    if nome:
        linhas.append(_evento(0.5, min(duracao, 5.0), "Nome", f"{{\\pos(70,960)\\fad(180,260)}}{_texto(nome)}", 3))
    elif chamada and duracao >= 12:
        linhas.append(_evento(5.0, 10.5, "Chamada", f"{{\\pos(70,960)\\fad(180,260)\\fscx90\\fscy90\\t(0,160,\\fscx100\\fscy100)}}{_texto(chamada)}", 3))
    mensagens = [_texto(m) for m in (chat or []) if 0 < len(_texto(m)) <= 40][:3]
    if mensagens:
        a = min(agenda["momento"] + 0.4, max(0.0, duracao - 3.0))
        b = min(duracao - 0.2, a + 3.6)
        linhas.append(_evento(a, b, "ChatTopo", "{\\pos(1850,70)\\fad(120,200)}O CHAT REAGIU", 3))
        for n, texto in enumerate(mensagens):
            inicio = a + 0.2 + n * 0.3
            linhas.append(_evento(inicio, b, "Chat", f"{{\\pos(1850,{150 + n * 78})\\fad(100,200)\\fscx86\\fscy86\\t(0,120,\\fscx100\\fscy100)}}{texto}", 3))
    linhas += estilos.eventos_legenda(_na_janela(grupos, ini, fim), duracao, est, x_legenda, y_legenda, 56, 34, _tempo_ass)
    return "\n".join(linhas) + "\n"


def ass_cartao(duracao: float, marca: str, titulo: str, apoio: str = "", est: dict | None = None) -> str:
    est = estilos.normalizar(est)
    titulo = _texto(titulo).upper()
    y_titulo = 510 if apoio else 540
    barra = "{\\p1}m 0 0 l 170 0 170 10 0 10{\\p0}"
    linhas = [
        *_cabecalho(est),
        _evento(0.1, duracao - 0.1, "Marca", f"{{\\an5\\pos(960,{y_titulo - 215})\\fad(180,180)}}{_texto(marca).upper()}"),
        _evento(0.15, duracao - 0.1, "Marca", f"{{\\an5\\pos(960,{y_titulo - 165})\\fad(180,180)\\fscx0\\t(0,320,\\fscx100)}}{barra}"),
        _evento(0.2, duracao - 0.1, "Titulo", f"{{\\an5\\pos(960,{y_titulo})\\fad(200,180)\\fscx92\\fscy92\\t(0,420,\\fscx100\\fscy100)}}{titulo}"),
    ]
    if apoio:
        linhas.append(_evento(0.55, duracao - 0.1, "Apoio", f"{{\\an5\\pos(960,790)\\fad(260,180)}}{_texto(apoio)}"))
    return "\n".join(linhas) + "\n"


# ------------------------------------------------------------ partes do vídeo

def _dentro(grupos: list[dict], ini: float, fim: float) -> list[dict]:
    saida = []
    for g in grupos:
        palavras = [{**p, "ini": max(ini, float(p["ini"])), "fim": min(fim, float(p["fim"]))}
                    for p in g.get("palavras", []) if float(p["fim"]) > ini and float(p["ini"]) < fim]
        if palavras:
            saida.append({"ini": float(palavras[0]["ini"]), "fim": float(palavras[-1]["fim"]), "palavras": palavras})
    return saida


def _quadro_de(fonte: Path, t: float) -> np.ndarray:
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.2f}", "-i", str(fonte), "-frames:v", "1", "-vf", f"scale={L}:{A}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, **sem_janela(),
    )
    tamanho = L * A * 3
    if len(r.stdout) < tamanho:
        return np.full((A, L, 3), 24, np.uint8)
    return np.frombuffer(r.stdout[:tamanho], np.uint8).reshape(A, L, 3).copy()


def render_trecho(t: dict, ini: float, fim: float, destino: Path, etiqueta: str, nome: str, progresso, est: dict | None = None,
                  chamada: str = "", entrada: str = "", saida: str = "") -> int:
    duracao = fim - ini
    picos = efeitos.batidas(t["fonte"], ini, duracao, espaco=3.5)
    agenda = agendar(duracao, t["momento"] - ini, picos, t["plano"])
    if entrada:
        agenda["mov"].clarao[:6] = 0
    if saida:
        agenda["mov"].clarao[-6:] = 0
        agenda["whoosh"].append(max(0.0, duracao - .32))
    origem = efeitos.ler_quadros(t["fonte"], _filtro_horizontal(t["fonte"]), L, A, agenda["quadros"], ini, baixa_prioridade=True)
    efeitos.gravar(
        destino, _quadros_trecho(origem, agenda, progresso, entrada, saida), agenda["quadros"], L, A,
        ass_trecho(t["grupos"], ini, fim, t["meta"].get("credito") or "", agenda, etiqueta, nome, est,
                   t["meta"].get("chat_marcante") or [], chamada), t["fonte"], ini,
        agenda["whoosh"], agenda["impacto"], 0.26, -15.0, baixa_prioridade=True,
        filtro_extra=filtros.cadeia(estilos.normalizar(est)["filtro"], estilos.normalizar(est)["filtro_forca"]),
    )
    return agenda["quadros"]


def render_cartao(t: dict, instante: float, destino: Path, duracao: float, marca: str, titulo: str, apoio: str, progresso,
                  est: dict | None = None) -> int:
    quadros = round(duracao * FPS)
    fundo = cv2.GaussianBlur(_quadro_de(t["fonte"], instante), (0, 0), 22)
    fundo = efeitos.escurecer(cv2.convertScaleAbs(fundo, alpha=0.36, beta=4), efeitos.mascara_vinheta(L, A, 0.6), 1.0)
    mov = efeitos.Movimento(quadros, 1.0, 1.07)

    def gerar():
        for i in range(quadros):
            saida = efeitos.aplicar(fundo, mov.matriz(i, L, A))
            restante = (quadros - i) / FPS
            if restante < 0.14:
                saida = efeitos.clarear(saida, float(1 - restante / 0.14) * 0.85)
            yield saida
            progresso()

    efeitos.gravar(destino, gerar(), quadros, L, A, ass_cartao(duracao, marca, titulo, apoio, est), None, 0.0, [0.0], [0.08], 0.3,
                   baixa_prioridade=True)
    return quadros


def juntar(partes: list[Path], destino: Path) -> None:
    lista = destino.with_suffix(".txt")
    lista.write_text("".join("file '" + p.resolve().as_posix().replace("'", "'\\''") + "'\n" for p in partes), encoding="utf-8")
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", "-movflags", "+faststart", str(destino)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", **sem_janela(),
    )
    lista.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "falha ao juntar o vídeo").strip()[-300:])


def gerar_capa(t: dict, texto: str, canal: str, destino: Path, est: dict | None = None) -> None:
    est = estilos.normalizar(est)
    quadro = _quadro_de(t["fonte"], t["momento"])
    foco = alvo_webcam(t["plano"])
    fundo = cv2.resize(cv2.convertScaleAbs(quadro, alpha=0.72, beta=0), (1280, 720), interpolation=cv2.INTER_AREA)
    moldura = (foco or {}).get("moldura")
    if moldura:
        x, y, w, h = moldura
        rosto = quadro[int(y * A):int((y + h) * A), int(x * L):int((x + w) * L)]
        # O fundo usa só a parte do jogo, para o rosto não aparecer duas vezes.
        esquerda, direita = x, 1 - (x + w)
        lado = max(esquerda, direita)
        if lado >= 0.3:
            x0 = 0 if esquerda >= direita else int((x + w) * L)
            largura = int(lado * L)
            altura = min(A, int(largura * 9 / 16))
            jogo = quadro[(A - altura) // 2:(A + altura) // 2, x0:x0 + largura]
            fundo = cv2.resize(cv2.convertScaleAbs(jogo, alpha=0.72, beta=0), (1280, 720), interpolation=cv2.INTER_CUBIC)
        alt = 600
        lar = min(620, int(alt * rosto.shape[1] / max(rosto.shape[0], 1)))
        rosto = cv2.resize(rosto, (lar, alt), interpolation=cv2.INTER_CUBIC)
        rosto = cv2.copyMakeBorder(rosto, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=estilos.cor_bgr(est["cor"]))
        px, py = 1280 - rosto.shape[1] - 36, 720 - rosto.shape[0] - 40
        fundo[py:py + rosto.shape[0], px:px + rosto.shape[1]] = rosto
    palavras = _texto(texto).upper().split()
    quebra = quebrar_linhas(palavras, 11)
    linhas = [" ".join(palavras)] if quebra is None else [" ".join(palavras[:quebra]), " ".join(palavras[quebra:])]
    quebrada = "\\N".join(linhas)
    ass = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1280", "PlayResY: 720", "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Capa,Poppins,104,&H00{estilos.cor_ass(est['cor'])[2:-1]},&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,10,5,1,0,0,0,1",
        "Style: Canal,Poppins,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,6,2,7,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 1,0:00:00.00,0:00:10.00,Capa,,0,0,0,,{{\\pos(44,650)}}{quebrada}",
        f"Dialogue: 1,0:00:00.00,0:00:10.00,Canal,,0,0,0,,{{\\pos(48,36)}}{_texto(canal).upper()}",
    ]) + "\n"
    with tempfile.TemporaryDirectory(prefix="clipador_") as tmp:
        tmp = Path(tmp)
        cv2.imwrite(str(tmp / "fundo.png"), fundo)
        (tmp / "capa.ass").write_text(ass, encoding="utf-8")
        estilos.copiar_fontes(ass, tmp / "fontes")
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", "fundo.png", "-vf", "ass=capa.ass:fontsdir=fontes", "-frames:v", "1", "-q:v", "3", "capa.jpg"],
            cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace", **sem_janela(),
        )
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-300:])
        shutil.move(str(tmp / "capa.jpg"), destino)


# ------------------------------------------------------------ fila de vídeos longos

class Longos:
    def __init__(self, motor):
        self.motor = motor
        self.pasta = Path(motor.saida) / "_longos"
        self.pasta.mkdir(parents=True, exist_ok=True)
        self.itens: dict[str, dict] = {}
        self.fila: queue.Queue = queue.Queue()
        self.trava = threading.RLock()
        for arq in self.pasta.glob("*/longo.json"):
            item = motor._ler(arq, None)
            if not item or "id" not in item:
                continue
            if item.get("pedido") == "timeline" and (arq.parent / "video.mp4").exists():
                item.update(status="pronto", etapa="Pronto", progresso=100, pedido=None, aviso="A última edição foi interrompida. Abra a timeline e gere o vídeo de novo.")
            elif item["status"] not in ("pronto", "erro"):
                item.update(status="erro", erro="O programa foi fechado durante a edição. Crie o vídeo de novo.")
            if (item.get("envio") or {}).get("estado") == "enviando":
                item["envio"] = {"estado": "erro", "erro": "O envio foi interrompido."}
            self.itens[item["id"]] = item
        self.arq_auto = Path(motor.dados) / "longos_auto.json"
        self.auto = {"ativo": True, "minutos": 10, "desde": time.time(), "usados": [], "partes": {}, **motor._ler(self.arq_auto, {})}
        self._vigiado = 0.0
        motor._gravar(self.arq_auto, self.auto)
        threading.Thread(target=self._trabalhar, daemon=True).start()

    def configurar_auto(self, dados: dict) -> dict:
        minutos = int(dados.get("minutos", self.auto["minutos"]))
        if minutos not in DURACOES:
            raise ValueError("Escolha uma duração válida.")
        ativo = bool(dados.get("ativo", self.auto["ativo"]))
        if ativo and not self.auto["ativo"]:
            self.auto["desde"] = time.time()
        self.auto.update(ativo=ativo, minutos=minutos)
        self.motor._gravar(self.arq_auto, self.auto)
        return self.resumo_auto()

    def _novos(self, sessao: dict) -> list[dict]:
        usados = set(self.auto["usados"])
        return [m for i in sessao["ids"] if i not in usados and (m := self.motor.cortes.get(i)) and m["criado"] >= self.auto["desde"]]

    def _no_ar(self, canal_id: str) -> bool:
        canal = self.motor.canais.get(canal_id)
        return bool(canal and canal.status in ("gravando", "reconectando", "conectando"))

    def resumo_auto(self) -> dict:
        alvo = self.auto["minutos"] * 60 * FATOR_AUTO
        lives = []
        for s in self.sessoes():
            if not s["gravada"] and self._no_ar(s["canal_id"]):
                lives.append({"canal": s["canal"], "acumulado": round(sum(float(m.get("duracao") or 0) for m in self._novos(s))), "alvo": round(alvo),
                              "parte": int(self.auto["partes"].get(s["id"], 0)) + 1})
        return {"ativo": self.auto["ativo"], "minutos": self.auto["minutos"], "lives": lives}

    def _vigiar(self) -> None:
        """Durante a live, cria uma nova parte sempre que há cortes suficientes. Nada é postado."""
        agora = time.time()
        if agora - self._vigiado < INTERVALO_AUTO or not self.auto["ativo"]:
            return
        self._vigiado = agora
        with self.trava:
            if any(i["status"] not in ("pronto", "erro") for i in self.itens.values()):
                return
        alvo = self.auto["minutos"] * 60 * FATOR_AUTO
        for s in self.sessoes():
            if s["gravada"]:
                continue
            novos = self._novos(s)
            soma = sum(float(m.get("duracao") or 0) for m in novos)
            encerrou = not self._no_ar(s["canal_id"]) and agora - s["ate"] >= ESPERA_FIM_LIVE
            if len(novos) < MINIMO_CORTES or not (soma >= alvo or encerrou):
                continue
            parte = int(self.auto["partes"].get(s["id"], 0)) + 1
            ids = [m["id"] for m in novos]
            self.auto["usados"] = [*self.auto["usados"], *ids][-5000:]
            self.auto["partes"][s["id"]] = parte
            self.motor._gravar(self.arq_auto, self.auto)
            self.criar(s["id"], self.auto["minutos"], ids, parte)
            return

    def _salvar(self, item: dict) -> None:
        self.motor._gravar(self.pasta / item["id"] / "longo.json", item)

    def sessoes(self) -> list[dict]:
        grupos: dict[str, dict] = {}
        with self.motor.trava:
            cortes = sorted(self.motor.cortes.values(), key=lambda x: x["criado"])
        for m in cortes:
            if m.get("status") != "pronto" or m.get("montagem"):
                continue
            chave = m.get("pasta") or "sem-pasta"
            g = grupos.setdefault(chave, {"id": chave, "canal_id": m.get("canal_id") or "", "canal": m.get("canal"), "titulo": m.get("titulo_live") or "", "cortes": 0,
                                          "duracao": 0.0, "desde": m["criado"], "ate": m["criado"], "gravada": bool(m.get("gravada_id")), "ids": []})
            g["cortes"] += 1
            g["duracao"] += float(m.get("duracao") or 0)
            g["ate"] = m["criado"]
            g["ids"].append(m["id"])
        return sorted(grupos.values(), key=lambda g: g["ate"], reverse=True)

    def criar(self, sessao: str, minutos: int, ids: list[str] | None = None, parte: int = 0) -> dict:
        if int(minutos) not in DURACOES:
            raise ValueError("Escolha uma duração válida.")
        grupo = next((g for g in self.sessoes() if g["id"] == sessao), None)
        if not grupo:
            raise ValueError("Escolha uma live com cortes prontos.")
        if grupo["cortes"] < MINIMO_CORTES:
            raise ValueError(f"Esta live precisa de pelo menos {MINIMO_CORTES} cortes prontos.")
        with self.trava:
            base = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            item_id, n = base, 2
            while item_id in self.itens:
                item_id, n = f"{base}_{n}", n + 1
            item = {"id": item_id, "status": "fila", "etapa": "Na fila", "progresso": 0, "erro": None, "criado": time.time(),
                    "canal": grupo["canal"], "titulo": f"Vídeo longo de {grupo['canal']}", "descricao": "", "tags": [], "minutos": int(minutos),
                    "cortes_ids": ids or grupo["ids"], "duracao": 0, "capitulos": [], "envio": None, "versao": 0, "parte": parte,
                    "estilo": estilos.normalizar(self.motor.config.get("estilo"))}
            (self.pasta / item_id).mkdir(parents=True, exist_ok=True)
            self.itens[item_id] = item
        self._salvar(item)
        self.fila.put(item_id)
        self.motor.evento(grupo["canal"], "corte", "Vídeo longo entrou na fila de edição")
        return {"id": item_id}

    def editar(self, item_id: str, dados: dict) -> dict:
        item = self.itens[item_id]
        if "titulo" in dados:
            titulo = _limpar(str(dados["titulo"]))
            if not 1 <= len(titulo) <= 100:
                raise ValueError("O título precisa ter de 1 a 100 caracteres.")
            item["titulo"] = titulo
        if "descricao" in dados:
            item["descricao"] = _limpar(str(dados["descricao"]))[:4900]
        self._salvar(item)
        return item

    def excluir(self, item_id: str) -> None:
        with self.trava:
            item = self.itens[item_id]
            if item["status"] not in ("pronto", "erro"):
                raise ValueError("Aguarde o vídeo terminar de ser editado.")
            if (item.get("envio") or {}).get("estado") == "enviando":
                raise ValueError("Aguarde o envio terminar.")
            del self.itens[item_id]
        shutil.rmtree(self.pasta / item_id, ignore_errors=True)

    def enviar(self, item_id: str, quando: float | None) -> None:
        item = self.itens[item_id]
        postagem = self.motor.postagem
        if item["status"] != "pronto":
            raise ValueError("O vídeo ainda não está pronto.")
        if not postagem.conta.conectada:
            raise ValueError("Conecte o canal do YouTube na aba Postagem.")
        if not postagem.config.get("auditoria"):
            raise ValueError("Sem a auditoria aprovada, o YouTube deixa o vídeo preso como privado. Baixe o vídeo e poste no YouTube Studio.")
        if (item.get("envio") or {}).get("estado") == "enviando":
            raise ValueError("Este vídeo já está sendo enviado.")
        if quando and quando < time.time() + 900:
            raise ValueError("Escolha um horário com pelo menos 15 minutos de antecedência.")
        item["envio"] = {"estado": "enviando", "progresso": 0, "quando": quando}
        self._salvar(item)
        threading.Thread(target=self._enviar, args=(item, quando), daemon=True).start()

    def _enviar(self, item: dict, quando: float | None) -> None:
        conta = self.motor.postagem.conta
        pasta = self.pasta / item["id"]
        try:
            video = conta.enviar(pasta / "video.mp4", item["titulo"], item["descricao"], item["tags"], quando,
                                 lambda f: item["envio"].__setitem__("progresso", round(f * 100)))
            capa_ok = True
            try:
                url = URL_ENVIO.replace("/videos", "/thumbnails/set") + f"?videoId={video}&uploadType=media"
                codigo, _, corpo = _pedir("POST", url, {"Authorization": f"Bearer {conta.acesso()}", "Content-Type": "image/jpeg"},
                                          (pasta / "capa.jpg").read_bytes(), 120)
                if codigo not in (200, 201):
                    raise _erro_da_resposta(codigo, corpo)
            except (ErroYouTube, OSError):
                capa_ok = False  # canais sem verificação não podem trocar a miniatura
            item["envio"] = {"estado": "enviado", "video_id": video, "quando": quando, "capa": capa_ok}
            self.motor.evento(item["canal"], "pronto", "Vídeo longo enviado para o YouTube")
        except Exception as e:
            item["envio"] = {"estado": "erro", "erro": str(e)[:300]}
        self._salvar(item)

    def resumo(self) -> list[dict]:
        campos = ("id", "status", "etapa", "progresso", "erro", "criado", "canal", "titulo", "descricao", "minutos", "duracao",
                  "capitulos", "envio", "versao", "aviso", "parte")
        return [{k: i.get(k) for k in campos} for i in sorted(self.itens.values(), key=lambda x: x["criado"], reverse=True)]

    def _trabalhar(self) -> None:
        while not self.motor.fim.is_set():
            try:
                item_id = self.fila.get(timeout=1)
            except queue.Empty:
                try:
                    self._vigiar()
                except Exception as e:
                    self.motor.evento("Vídeos longos", "erro", f"A criação automática encontrou um problema: {str(e)[:120]}")
                continue
            item = self.itens.get(item_id)
            if not item:
                continue
            if item.get("pedido") == "timeline":
                try:
                    self._aplicar_timeline(item)
                    item.update(status="pronto", etapa="Pronto", progresso=100, aviso=None, versao=int(item.get("versao", 0)) + 1)
                    self.motor.evento(item["canal"], "pronto", f"Vídeo longo atualizado: {item['titulo']}")
                except Exception as e:
                    item.update(status="pronto", etapa="Pronto", progresso=100, aviso=f"A edição não foi aplicada: {str(e)[:220]}")
                    self.motor.evento(item["canal"], "erro", "A edição do vídeo longo não pôde ser aplicada")
                item.update(pedido=None, edicao_pendente=None)
                self._salvar(item)
                continue
            try:
                self._montar(item)
                item.update(status="pronto", etapa="Pronto", progresso=100, erro=None, versao=int(item.get("versao", 0)) + 1)
                self.motor.evento(item["canal"], "pronto", f"Vídeo longo pronto: {item['titulo']}")
            except Exception as e:
                item.update(status="erro", etapa="Com problema", erro=str(e)[:300])
                self.motor.evento(item["canal"], "erro", "O vídeo longo não pôde ser editado")
            self._salvar(item)

    def blocos(self, item: dict) -> list[dict]:
        """Legendas do vídeo longo no tempo do vídeo completo."""
        saida = []
        for parte in item.get("partes") or []:
            if parte["tipo"] != "trecho":
                continue
            for g in parte.get("grupos") or []:
                palavras = g.get("palavras") or []
                if palavras:
                    saida.append({"ini": round(max(parte["ini"], float(g["ini"])) - parte["ini"] + parte["saida"], 3),
                                  "fim": round(min(parte["fim"], float(g["fim"])) - parte["ini"] + parte["saida"], 3), "texto": " ".join(p["p"] for p in palavras)})
        return saida

    def aplicar_timeline(self, item_id: str, ed: dict, blocos: list[dict] | None) -> None:
        with self.trava:
            item = self.itens[item_id]
            if item["status"] != "pronto":
                raise ValueError("Aguarde este vídeo terminar de ser editado.")
            if (item.get("envio") or {}).get("estado") == "enviando":
                raise ValueError("Aguarde o envio terminar.")
            item.update(status="editando", etapa="Na fila de edição", progresso=0, pedido="timeline", edicao_pendente={"edicao": ed, "blocos": blocos})
        self._salvar(item)
        self.fila.put(item_id)

    def _trocar_legendas(self, item: dict, base: Path, blocos: list[dict], tmp: Path) -> None:
        """Refaz só as partes com legenda alterada e reaproveita o resto do vídeo."""
        est = estilos.normalizar(item.get("estilo"))
        partes = item["partes"]
        trocas: dict[int, list[dict]] = {}
        for n, parte in enumerate(partes):
            if parte["tipo"] != "trecho":
                continue
            fim_saida = parte["saida"] + parte["dur"]
            locais = [{"ini": round(b["ini"] - parte["saida"] + parte["ini"], 3), "fim": round(min(b["fim"], fim_saida) - parte["saida"] + parte["ini"], 3), "texto": b["texto"]}
                      for b in blocos if parte["saida"] <= b["ini"] < fim_saida]
            novos = tl.grupos_de_blocos(locais, parte.get("grupos") or [])
            if not tl.mesmas_legendas(novos, parte.get("grupos") or []):
                trocas[n] = novos
        if not trocas:
            return
        arquivos: dict[int, Path] = {}
        for n, novos in trocas.items():
            parte = partes[n]
            self._etapa(item, f"Refazendo a legenda da parte {n + 1} de {len(partes)}")
            meta = self.motor.cortes.get(parte["corte"])
            trechos = criar_trechos([meta], self.motor.saida) if meta else []
            if not trechos:
                raise ValueError("Um corte usado neste vídeo foi apagado, então a legenda dessa parte não pode mudar.")
            arquivos[n] = tmp / f"nova_{n:04d}.mp4"
            render_trecho({**trechos[0], "grupos": novos, "momento": parte["momento"] + parte["ini"]}, parte["ini"], parte["fim"], arquivos[n], parte.get("etiqueta") or "",
                          parte.get("nome") or "", lambda: None, est, parte.get("chamada") or "")
        novo = tmp / "base_nova.mp4"
        emendar_partes(base, [p["saida"] for p in partes], arquivos, novo)
        _substituir(novo, base)
        for n, novos in trocas.items():
            partes[n]["grupos"] = novos

    def _aplicar_timeline(self, item: dict) -> None:
        pasta = self.pasta / item["id"]
        pedido = item["edicao_pendente"]
        item.setdefault("capitulos_base", item.get("capitulos") or [])
        ed = pedido["edicao"]
        base = pasta / "base.mp4"
        if not base.exists():
            try:
                os.link(pasta / "video.mp4", base)
            except OSError:
                shutil.copy(pasta / "video.mp4", base)
        tmp = Path(tempfile.mkdtemp(prefix="timeline_", dir=pasta))
        try:
            if pedido.get("blocos") is not None and item.get("partes"):
                self._trocar_legendas(item, base, pedido["blocos"], tmp)
            self._etapa(item, "Gerando o vídeo editado")
            duracao_base = float(cam.dimensoes(base)[2] or item.get("duracao_base") or item["duracao"])
            total = tl.duracao_total(ed["cortes"])
            tl.criar_trilha(ed["sons"], ed["cortes"], total, self.motor.biblioteca, tmp / "sons.wav")
            destino = tmp / "video.mp4"
            renderizar_longo_editado(base, ed, tmp / "sons.wav", destino, total, duracao_base, lambda f: item.__setitem__("progresso", min(99, round(f * 100))))
            _substituir(destino, pasta / "video.mp4")
            capitulos = capitulos_editados(item.get("capitulos_base") or item.get("capitulos") or [], ed["cortes"], total)
            item.update(edicao=ed, duracao=round(total, 2), capitulos=capitulos, descricao=_descricao_com_capitulos(item.get("descricao") or "", capitulos))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _etapa(self, item: dict, etapa: str, status: str = "editando") -> None:
        item.update(status=status, etapa=etapa)
        self._salvar(item)

    def _montar(self, item: dict) -> None:
        pasta = self.pasta / item["id"]
        self._etapa(item, "Montando a história", "historia")
        cortes = [self.motor.cortes[i] for i in item["cortes_ids"] if i in self.motor.cortes]
        trechos = tirar_repeticoes(criar_trechos(cortes, self.motor.saida))
        if len(trechos) < MINIMO_CORTES:
            raise ValueError(f"Esta live precisa de pelo menos {MINIMO_CORTES} cortes diferentes.")
        alvo = item["minutos"] * 60
        escolhidos = selecionar(trechos, alvo * 0.9)
        capitulos = nomear_capitulos(dividir_capitulos(escolhidos))
        principal = max(escolhidos, key=lambda x: x["forca"])
        canal = item["canal"] or "Live"
        est = estilos.normalizar(item.get("estilo"))
        parte = int(item.get("parte") or 0)
        tmp = Path(tempfile.mkdtemp(prefix="longo_", dir=pasta))
        try:
            # Abertura: os melhores momentos em sequência, parando no auge para prender quem chegou agora.
            ganchos = sorted(sorted(escolhidos, key=lambda x: x["forca"])[-3:], key=lambda x: x["forca"])
            cenas_abertura = []
            for n, t in enumerate(ganchos):
                ultimo_gancho = n == len(ganchos) - 1
                a0, b0 = max(t["ini"], t["momento"] - (4.5 if ultimo_gancho else 3.0)), min(t["fim"], t["momento"] + (.9 if ultimo_gancho else 1.6))
                cenas_abertura.append((t, *ajustar_a_frases(_palavras(t), a0, b0, t["ini"], min(t["fim"], b0 + 2.2))))
            previsto = sum(c[2] - c[1] for c in cenas_abertura) + 4.5 + sum(t["fim"] - t["ini"] for t in escolhidos)
            total_quadros = max(1, round(previsto * FPS))
            feito = [0]

            def avancar() -> None:
                feito[0] += 1
                if feito[0] % 15 == 0:
                    item["progresso"] = min(97, round(feito[0] / total_quadros * 97))

            partes: list[Path] = []
            tempos: list[tuple[float, str]] = [(0.0, "Introdução")]
            agora = 0.0
            feitos, chamou_inscrever, chamou_comentar = 0, False, False

            def nova(nome: str) -> Path:
                partes.append(tmp / f"{len(partes):03d}_{nome}.mp4")
                return partes[-1]

            registro: list[dict] = []

            sequencia = {"n": 0, "entrada": ""}

            def proxima_transicao() -> str:
                sequencia["n"] += 1
                return ("chicote", "impulso", "glitch", "queda", "rgb", "giro")[sequencia["n"] % 6]

            def rt(t: dict, ini: float, fim: float, destino: Path, etiqueta: str, nome: str, prog, e: dict, chamada: str = "", capitulo: str = "", ultima: bool = False) -> int:
                sai = "" if ultima else proxima_transicao()
                quadros = render_trecho(t, ini, fim, destino, etiqueta, nome, prog, e, chamada, sequencia["entrada"], sai)
                registro.append({"tipo": "trecho", "saida": round(agora, 3), "dur": quadros / FPS, "corte": t["id"], "ini": ini, "fim": fim, "etiqueta": etiqueta, "nome": nome, "capitulo": capitulo, "entrada": sequencia["entrada"],
                                 "chamada": chamada, "momento": round(max(0.0, t["momento"] - ini), 2), "reacao": t["reacao"], "grupos": _dentro(t["grupos"], ini, fim)})
                sequencia["entrada"] = sai
                return quadros

            def rc(*args) -> int:
                quadros = render_cartao(*args)
                registro.append({"tipo": "cartao", "saida": round(agora, 3), "dur": quadros / FPS,
                                 "cartao": {"corte": args[0]["id"], "instante": args[1], "marca": args[4], "titulo": args[5], "apoio": args[6]}})
                return quadros

            self._etapa(item, "Editando a abertura")
            textos = criar_textos(escolhidos, capitulos)
            for n, (t, a0, b0) in enumerate(cenas_abertura):
                frase = ("Você não vai acreditar nisso", "Olha o que vem por aí", "Fica até o final")[n + 3 - len(cenas_abertura)]
                agora += rt(t, a0, b0, nova("abertura"), frase, "", avancar, est) / FPS
            for n, capitulo in enumerate(capitulos, 1):
                self._etapa(item, f"Editando a parte {n} de {len(capitulos)}")
                tempos.append((agora, capitulo["titulo"]))
                anterior = None
                for t in capitulo["trechos"]:
                    feitos += 1
                    etiqueta = (f"Parte {parte}: {capitulo['titulo']}" if parte and n == 1 else capitulo["titulo"]) if anterior is None else ""
                    if anterior is not None:
                        minutos = round((t["t"] - anterior["t"]) / 60)
                        etiqueta = f"{minutos} minutos depois" if minutos >= 2 else ""
                    assinatura = f"{canal} ao vivo" if n == 1 and anterior is None else ""
                    chamada = ""
                    if not chamou_inscrever and feitos / len(escolhidos) >= 0.3:
                        chamada, chamou_inscrever = "Se inscreve pra não perder a próxima parte", True
                    elif not chamou_comentar and feitos / len(escolhidos) >= 0.65:
                        chamada, chamou_comentar = "Comenta aí: o que você faria nessa hora?", True
                    agora += rt(t, t["ini"], t["fim"], nova("trecho"), etiqueta, assinatura, avancar, est, chamada, capitulo["titulo"] if anterior is None else "", t is escolhidos[-1]) / FPS
                    anterior = t
            self._etapa(item, "Finalizando o vídeo")
            ultimo = escolhidos[-1]
            agora += rc(ultimo, max(ultimo["ini"], ultimo["fim"] - 2), nova("final"), 4.5, "E aí?", "Qual foi o melhor momento?",
                        "Comenta aqui embaixo e se inscreve no canal", avancar, est) / FPS
            destino = pasta / "video_novo.mp4"
            juntar(partes, destino)
            destino.replace(pasta / "video.mp4")
            gerar_capa(principal, textos["texto_capa"], canal, pasta / "capa.jpg", est)
            final = criar_textos(escolhidos, capitulos, tempos)
            if parte:
                final["titulo"] = f"{final['titulo'][:86]} (PARTE {parte})"
            item.update(titulo=final["titulo"], descricao=final["descricao"], tags=final["tags"], duracao=round(agora, 2),
                        capitulos=[{"t": round(t, 2), "titulo": nome} for t, nome in tempos], partes=registro, duracao_base=round(agora, 2),
                        capitulos_base=[{"t": round(t, 2), "titulo": nome} for t, nome in tempos])
            if sum(t["fim"] - t["ini"] for t in escolhidos) < alvo * 0.7:
                item["aviso"] = f"Esta live tinha cortes para {_relogio(agora)}. Com mais cortes, o vídeo chega aos {item['minutos']} minutos."
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _substituir(novo: Path, destino: Path) -> None:
    """No Windows o arquivo fica preso enquanto alguém assiste: espera ele ser liberado."""
    for tentativa in range(40):
        try:
            novo.replace(destino)
            return
        except PermissionError:
            if tentativa == 39:
                raise
            time.sleep(0.5)


def _probe(base: Path, *args: str) -> list[str]:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", *args, "-of", "csv=p=0", str(base)], capture_output=True, text=True, **sem_janela())
    return [x.strip(", ") for x in r.stdout.split() if x.strip(", ")]


def emendar_partes(base: Path, inicios: list[float], novos: dict[int, Path], destino: Path) -> None:
    """Troca partes inteiras sem recodificar o resto, mantendo cada quadro no mesmo tempo."""
    chaves = np.array([float(x) for x in _probe(base, "-skip_frame", "nokey", "-show_entries", "frame=pts_time")])
    pacote = _probe(base, "-read_intervals", "%+#1", "-show_entries", "packet=pts_time,dts_time")
    if not len(chaves) or not pacote:
        raise RuntimeError("Não consegui localizar as partes do vídeo.")
    pts, dts = (float(x) for x in pacote[0].split(",")[:2])
    atraso = pts - dts  # o quadro-chave seguinte entra antes na ordem de gravação
    tempos = [float(chaves[np.abs(chaves - t).argmin()]) for t in inicios]
    nome = base.resolve().as_posix().replace("'", "'\\''")
    linhas, n = [], 0
    while n < len(tempos):
        if n in novos:
            caminho = novos[n].resolve().as_posix().replace("'", "'\\''")
            linhas.append(f"file '{caminho}'\n" + (f"duration {tempos[n + 1] - tempos[n]:.6f}\n" if n + 1 < len(tempos) else ""))
            n += 1
            continue
        fim = n
        while fim + 1 < len(tempos) and fim + 1 not in novos:
            fim += 1
        texto = f"file '{nome}'\ninpoint {tempos[n]:.6f}\n"
        if fim + 1 < len(tempos):
            texto += f"outpoint {tempos[fim + 1] - atraso:.6f}\nduration {tempos[fim + 1] - tempos[n]:.6f}\n"
        linhas.append(texto)
        n = fim + 1
    lista = destino.with_suffix(".txt")
    lista.write_text("".join(linhas), encoding="utf-8")
    edicao.executar(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lista), "-map", "0", "-c", "copy", "-movflags", "+faststart", str(destino)])


def capitulos_editados(capitulos: list[dict], cortes: list[list[float]], total: float) -> list[dict]:
    """O YouTube só aceita capítulos de pelo menos 10 segundos."""
    novos: list[dict] = []
    for c in capitulos:
        t = tl.proxima_saida(float(c["t"]), cortes)
        if total - t >= 10 and (not novos or t - novos[-1]["t"] >= 10):
            novos.append({"t": round(t, 2), "titulo": c["titulo"]})
    if novos:
        novos[0]["t"] = 0.0
    return novos


def _descricao_com_capitulos(descricao: str, capitulos: list[dict]) -> str:
    linhas = "\n".join(f"{_relogio(c['t'])} {c['titulo']}" for c in capitulos)
    return re.sub(r"(⏱️ Capítulos\n)(?:[^\n]+\n?)+", lambda m: m[1] + linhas + "\n", descricao, count=1)


def renderizar_longo_editado(base: Path, ed: dict, sons: Path, destino: Path, total: float, duracao_base: float, progresso) -> None:
    # Um único filtro de seleção não guarda quadros na memória, o que importa em vídeos de muitos minutos.
    trechos = "+".join(f"between(t,{a:.3f},{b - 0.001:.3f})" for a, b in ed["cortes"])
    cor = filtros.cadeia(ed.get("filtro"), ed.get("intensidade", 100))
    grafo = (f"[0:v]select='{trechos}',setpts=N/{FPS}/TB{',' + cor if cor else ''},format=yuv420p[v];"
             f"[0:a]aselect='{trechos}',asetpts=N/SR/TB,volume={ed.get('volume', 100) / 100:.3f}[fala];"
             "[fala][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
    cmd = ["ffmpeg", "-v", "error", "-y", "-progress", "pipe:1", "-nostats", "-i", str(base), "-i", str(sons), "-filter_complex", grafo, "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "12M", "-bufsize", "24M", "-g", str(FPS * 2), "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(destino)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", **sem_janela())
    for linha in proc.stdout:
        if linha.startswith("out_time_ms=") and linha[12:].strip().isdigit():
            progresso(int(linha[12:]) / 1_000_000 / max(total, 1))
    erro = proc.stderr.read()
    codigo = proc.wait()
    if codigo != 0:
        raise RuntimeError((erro or f"o FFmpeg parou com o código {codigo}").strip()[-300:])


def previa_estilo(est: dict, formato: str, corte: dict | None, saida: Path, destino: Path) -> None:
    """Desenha um quadro real com o estilo escolhido para mostrar no painel."""
    frases = "Olha isso aqui, foi insano demais".split()
    palavras = [{"p": p, "ini": 0.2 + i * 0.5, "fim": 0.65 + i * 0.5} for i, p in enumerate(frases)]
    grupos = [{"ini": palavras[0]["ini"], "fim": palavras[-1]["fim"], "palavras": palavras}]
    fundo = saida / corte["id"] / "quadro.jpg" if corte else None
    entrada = ["-loop", "1", "-t", "2.6", "-i", str(fundo.resolve())] if fundo and fundo.exists() else \
        ["-f", "lavfi", "-t", "2.6", "-i", "color=c=0x2b274d:s=1920x1080:r=30"]
    if formato == "h":
        base = f"[0:v]scale={L}:{A}:force_original_aspect_ratio=increase,crop={L}:{A},setsar=1"
        agenda = {"momento": 0.0}
        ass = ass_trecho(grupos, 0, 3, "kick.com/canal", agenda, "12 minutos depois", "", est)
        escala = "scale=720:-2"
    else:
        plano = (corte or {}).get("plano") if fundo and fundo.exists() else None
        base = edicao._filtro_video(plano or {"layout": "inteiro"})
        ass = edicao.gerar_ass(grupos, "O que o jogo será isso, hein??", "GTA 6 ao vivo", "kick.com/canal", 3, (plano or {}).get("layout", "inteiro"), est)
        escala = "scale=405:-2"
    cor = filtros.cadeia(est.get("filtro"), est.get("filtro_forca", 100))
    cor = f"{cor}," if cor else ""
    with tempfile.TemporaryDirectory(prefix="clipador_") as tmp:
        tmp = Path(tmp)
        (tmp / "previa.ass").write_text(ass, encoding="utf-8")
        estilos.copiar_fontes(ass, tmp / "fontes")
        edicao.executar(["ffmpeg", "-v", "error", "-y", *entrada, "-filter_complex", f"{base},fps=30,{cor}ass=previa.ass:fontsdir=fontes,{escala}[v]",
                         "-map", "[v]", "-ss", "1.45", "-frames:v", "1", "-q:v", "3", "previa.jpg"], cwd=tmp)
        shutil.move(str(tmp / "previa.jpg"), destino)


def posicoes_padrao(corte: dict | None) -> dict:
    layout = ((corte or {}).get("plano") or {}).get("layout", "inteiro")
    return {"legenda_x": 0.5, "legenda_y": round(edicao.BASE_LEGENDA / 1920, 4), "gancho_x": 0.5,
            "gancho_y": round(edicao.POSICAO_GANCHO.get(layout, 800) / 1920, 4), "legenda_hx": 0.5, "legenda_hy": round(1030 / A, 4),
            "gancho_hx": round(70 / L, 4), "gancho_hy": round(70 / A, 4)}
