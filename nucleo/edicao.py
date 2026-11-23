"""Transcreve e monta o vídeo vertical final."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from . import camera as cam
from . import efeitos, estilos, filtros
from . import foco
from . import bastidores, fala
from . import tomadas as tm
from .contexto import quebrar_linhas
from .plataformas import sem_janela

RAIZ = Path(__file__).resolve().parent.parent
FONTE = RAIZ / "fontes" / "Poppins-Bold.ttf"
# A legenda fica fora do rosto e acima dos botões das redes sociais.
BASE_LEGENDA = 1650  # a última linha fica sempre aqui, abaixo da área principal do jogo
POSICAO_CREDITO = {"pip": "\\an2\\pos(540,1826)", "dividido": "\\an1\\pos(36,744)", "tela_cheia": "\\an7\\pos(40,150)", "inteiro": "\\an7\\pos(40,150)"}
POSICAO_GANCHO = {"pip": 420, "dividido": 800, "tela_cheia": 1090, "inteiro": 330}


def executar(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **sem_janela(), **kw)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "falha no FFmpeg").strip()[-400:])
    return r


def transcrever(modelo, video: Path, idioma: str, esperadas: str = "", correcoes: dict | None = None) -> list[dict]:
    """Fala com o tempo de cada palavra. `esperadas`: nomes e termos da live; `correcoes`: erros já corrigidos por você."""
    import numpy as np

    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-af", "highpass=f=70", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True, **sem_janela(),
    ).stdout
    if len(pcm) < 32000:
        return []
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    trechos, _ = modelo.transcribe(audio, word_timestamps=True, **fala.opcoes(modelo, idioma, esperadas))
    trechos = bastidores.acompanhar_fala(trechos)
    return fala.aplicar_correcoes(fala.limpar_trechos(trechos), correcoes or {})


def ouvir_trecho(modelo, pcm, idioma: str) -> str:
    """Escuta rápida da live, usada para perceber exclamações curtas."""
    import numpy as np

    audio = pcm.astype(np.float32) / 32768
    trechos, _ = modelo.transcribe(audio, without_timestamps=True, **fala.opcoes(modelo, idioma, rapido=True))
    return " ".join(t.text.strip() for t in trechos if not fala.INVENTADAS.search(t.text or ""))


def extrair_trecho(bruto: Path, ini: float, duracao: float, destino: Path) -> None:
    """Recorta com precisão de quadro.

    Procurar direto no arquivo da live cai entre dois quadros-chave: o áudio começa antes da
    imagem e o vídeo fica congelado no início. Por isso o trecho é decodificado desde o começo.
    """
    fim = ini + duracao
    executar(
        ["ffmpeg", "-v", "error", "-y", "-fflags", "+genpts", "-i", str(bruto),
         "-map", "0:v:0", "-map", "0:a:0?",
         "-vf", f"trim=start={ini:.3f}:end={fim:.3f},setpts=PTS-STARTPTS",
         "-af", f"atrim=start={ini:.3f}:end={fim:.3f},asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-maxrate", "45M", "-bufsize", "90M",  # cópia quase sem perda da live
         "-c:a", "aac", "-b:a", "256k", str(destino)]
    )


def _tempo_ass(s: float) -> str:
    cs = max(0, round(s * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _tempo_srt(s: float) -> str:
    ms = max(0, round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _limpo(t: str) -> str:
    return re.sub(r"[{}\\]", "", t).upper()


def _sem_chaves(t: str) -> str:
    return re.sub(r"[{}\\]", "", t)


def _marca_dagua(arroba: str, duracao: float, layout: str, hc: int) -> list[str]:
    """O seu @ pequeno, trocando de canto a cada 7 segundos (dificulta quem corta a marca para repostar)."""
    if layout == "dividido":
        lugares = [(1044, hc - 64, 3), (36, hc + 330, 7), (1044, 1540, 3), (36, 1250, 7)]
    else:
        lugares = [(1044, 260, 9), (36, 1250, 7), (1044, 1520, 3), (36, 430, 7)]
    saida, t, n = [], 0.0, 0
    while t < duracao - .05:
        x, y, a = lugares[n % len(lugares)]
        fim = min(duracao, t + 7.0)
        saida.append(f"Dialogue: 1,{_tempo_ass(t)},{_tempo_ass(fim)},Marca,,0,0,0,,{{\\an{a}\\pos({x},{y})\\fad(200,200)}}{arroba}")
        t, n = fim, n + 1
    return saida


SELO_Y = {"topo": 120, "rodape": 1760}
SELO_COR = {"vermelho": ("FF4B5C", "&HFFFFFF&"), "branco": ("FFFFFF", "&H141414&")}  # fundo do selo, cor da letra


def cores_selo(est: dict) -> tuple[str, str]:
    """Fundo e letra do selo. "destaque" usa a cor de destaque escolhida no estilo."""
    if est.get("fixo_cor") in SELO_COR:
        fundo, letra = SELO_COR[est["fixo_cor"]]
    else:
        fundo = estilos.CORES.get(est.get("cor"), "FFC933")
        letra = "&H141414&" if fundo not in ("FF4B5C",) else "&HFFFFFF&"
    return fundo, letra


def janela_selo(est: dict, duracao: float) -> tuple[float, float]:
    """Quando o selo aparece: o vídeo todo, junto com o título ou nos últimos 3 segundos."""
    tempo = est.get("fixo_tempo")
    if tempo == "titulo":
        return 0.0, min(duracao, float(est.get("tempo_gancho") or 5) + .5)
    if tempo == "final":
        return max(0.0, duracao - 3.0), duracao
    return 0.0, duracao


def y_selo(est: dict, layout: str, hc: int) -> int:
    lugar = est.get("fixo_lugar")
    if lugar == "divisao":
        return hc - 50 if layout == "dividido" else 1180  # sem encostar no título
    return SELO_Y.get(lugar, 120)


def _texto_fixo(est: dict, duracao: float, layout: str, hc: int) -> list[str]:
    """Selo da live em todos os cortes: "AO VIVO", o nome do streamer, o seu canal. Uma faixa colorida, em uma linha."""
    texto = _sem_chaves(str(est.get("texto_fixo") or "").strip())
    if not texto:
        return []
    fundo, letra = cores_selo(est)
    ini, fim = janela_selo(est, duracao)
    caixa = estilos.cor_ass(fundo)
    return [f"Dialogue: 2,{_tempo_ass(ini)},{_tempo_ass(fim)},Selo,,0,0,0,,"
            f"{{\\an5\\pos(540,{y_selo(est, layout, hc)})\\1c{letra}\\3c{caixa}\\fscx90\\fscy90\\t(0,160,\\fscx100\\fscy100)\\fad(120,{200 if fim < duracao else 0})}}{texto.upper()}"]


def _encerramento(arroba: str, ini: float, dur: float) -> list[str]:
    fim = ini + dur
    return [
        f"Dialogue: 4,{_tempo_ass(ini + .1)},{_tempo_ass(fim)},Fim,,0,0,0,,{{\\an2\\pos(540,930)\\fs44\\alpha&H30&\\fad(220,0)}}SIGA PARA MAIS",
        f"Dialogue: 4,{_tempo_ass(ini + .18)},{_tempo_ass(fim)},Fim,,0,0,0,,{{\\an8\\pos(540,950)\\fad(200,0)\\fscx70\\fscy70\\t(0,180,\\fscx106\\fscy106)\\t(180,260,\\fscx100\\fscy100)}}{arroba}",
    ]


def gerar_ass(grupos: list[dict], gancho: str, contexto: str, credito: str, duracao: float, layout: str,
              estilo: dict | None = None, altura_cam: int | None = None, tomadas: list[dict] | None = None, outro: float = 0.0) -> str:
    est = estilos.normalizar(estilo)
    credito_pos = POSICAO_CREDITO.get(layout, POSICAO_CREDITO["dividido"])
    gancho_padrao = POSICAO_GANCHO.get(layout, 800)
    if layout == "dividido" and altura_cam:
        credito_pos, gancho_padrao = f"\\an1\\pos(36,{int(altura_cam) - 16})", int(altura_cam) + 40
    if layout == "dividido" and est["legenda"] == "react":
        gancho_padrao = 1420  # a legenda curta fica logo abaixo da divisão; o título desce para o jogo
    x_gancho, y_gancho = estilos.ponto(est, "gancho_x", "gancho_y", 1080, 1920, 540, gancho_padrao)
    x_legenda, y_legenda = estilos.ponto(est, "legenda_x", "legenda_y", 1080, 1920, 540, BASE_LEGENDA)
    saida = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        estilos.estilo_legenda(est, 66), estilos.estilo_gancho(est, 54),
        "Style: Marca,Roboto Black,30,&H50FFFFFF,&H00FFFFFF,&H90000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,5,40,40,0,1",
        "Style: Fim,Roboto Black,90,&H00FFFFFF,&H00FFFFFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,5,60,60,0,1",
        "Style: Selo,Roboto Black,40,&H00141414,&H00FFFFFF,&H00FFC933,&H00000000,-1,0,0,0,100,100,1.5,0,3,14,0,5,60,60,0,1",
        "Style: Contexto,Poppins,32,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,8,90,90,0,1",
        "Style: Credito,Poppins,28,&H30FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,5,60,60,0,1" if layout != "pip"
        else "Style: Credito,Poppins,34,&H00FFFFFF,&H00FFFFFF,&H30101010,&H00000000,-1,0,0,0,100,100,0,0,3,20,0,2,60,60,0,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{_tempo_ass(0)},{_tempo_ass(duracao)},Credito,,0,0,0,,{{{credito_pos}}}{_sem_chaves(credito)}",
    ]

    if gancho and est["gancho"] != "nenhum":
        palavras = _limpo(gancho).split()
        corte = quebrar_linhas(palavras, 24)
        linhas = [" ".join(palavras)] if corte is None else [" ".join(palavras[:corte]), " ".join(palavras[corte:])]
        fim = min(est["tempo_gancho"] + 0.5, duracao)
        texto_gancho = "\\N".join(linhas)
        saida.append(
            f"Dialogue: 3,{_tempo_ass(0)},{_tempo_ass(fim)},Gancho,,0,0,0,,"
            f"{{\\an8\\pos({x_gancho},{y_gancho})\\fad(0,280){estilos.efeito_gancho(est)}\\fscx84\\fscy84\\t(0,140,\\fscx100\\fscy100)}}{texto_gancho}"
        )
        if contexto:
            y = y_gancho + len(linhas) * 76 + 44
            saida.append(
                f"Dialogue: 3,{_tempo_ass(0)},{_tempo_ass(fim)},Contexto,,0,0,0,,"
                f"{{\\an8\\pos({x_gancho},{y})\\fad(120,280)}}{_sem_chaves(contexto)}"
            )

    y_em = None
    if est["legenda"] == "react":
        hc = int(altura_cam or 760)
        if est.get("legenda_y") is not None or layout != "dividido":
            y_em = lambda t: (2, y_legenda)
        else:  # logo abaixo da divisão; quando o rosto ou o jogo ocupam a tela, um pouco abaixo do meio
            y_em = lambda t: (8, hc + 30) if tm.tipo_em(tomadas or [], t) == "dividido" else (8, tm.ROSTO_Y_LEGENDA)
    saida += estilos.eventos_legenda(grupos, duracao, est, x_legenda, y_legenda, 66, 18, _tempo_ass, y_em)
    saida += _texto_fixo(est, duracao, layout, int(altura_cam or 760))
    if est.get("arroba"):
        saida += _marca_dagua(est["arroba"], duracao, layout, int(altura_cam or 760))
        if outro > 0:
            saida += _encerramento(est["arroba"], duracao, outro)
    return "\n".join(saida) + "\n"


def gerar_srt(grupos: list[dict]) -> str:
    blocos = []
    for n, g in enumerate((g for g in grupos if g["palavras"]), 1):
        texto = " ".join(p["p"] for p in g["palavras"])
        blocos.append(f"{n}\n{_tempo_srt(g['palavras'][0]['ini'])} --> {_tempo_srt(g['palavras'][-1]['fim'])}\n{texto}\n")
    return "\n".join(blocos)


def _filtro_video(plano: dict, tomadas: list[dict] | None = None) -> str:
    layout = plano["layout"]
    if layout == "dividido" and tomadas and plano.get("rosto_cheio"):
        c, j, hc = plano["camera"], plano["jogo"], int(plano.get("altura_cam", 760))
        r, g = plano["rosto_cheio"], plano["jogo_cheio"]
        cadeia = (
            "[0:v]split=4[c][j][r][g];"
            f"[c]crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale=1080:{hc}:flags=lanczos,unsharp=5:5:0.55:5:5:0,setsar=1[cam];"
            f"[j]crop={j['w']}:{j['h']}:{j['x']}:{j['y']},scale=1080:{1920 - hc}:flags=lanczos,setsar=1[jogo];"
            f"[cam][jogo]vstack=inputs=2,drawbox=x=0:y={hc - 3}:w=1080:h=6:color=black:t=fill[div];"
            f"[r]crop={r['w']}:{r['h']}:{r['x']}:{r['y']},scale=1080:1920:flags=lanczos,unsharp=5:5:0.8:5:5:0,setsar=1[rosto];"
            f"[g]crop={g['w']}:{g['h']}:{g['x']}:{g['y']},scale=1080:1920:flags=lanczos,unsharp=5:5:0.4:5:5:0,setsar=1[jcheio];"
        )
        er, ej = tm.enable(tomadas, "rosto"), tm.enable(tomadas, "jogo")
        cadeia += f"[div][rosto]overlay=0:0:enable='{er or '0'}'[d2];[d2][jcheio]overlay=0:0:enable='{ej or '0'}'"
        return cadeia
    if layout == "pip":
        c, j, p = plano["camera"], plano["jogo"], plano["pip"]
        return (
            "[0:v]split=2[c][j];"
            f"[j]crop={j['w']}:{j['h']}:{j['x']}:{j['y']},scale=1080:1920:flags=lanczos,setsar=1[jogo];"
            f"[c]crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale={p['w']}:{p['h']}:flags=lanczos,unsharp=5:5:0.55:5:5:0,setsar=1[cam];"
            f"[jogo][cam]overlay={p['x']}:{p['y']}"
        )
    if layout == "dividido":
        c, j, hc = plano["camera"], plano["jogo"], int(plano.get("altura_cam", 760))
        return (
            "[0:v]split=2[c][j];"
            f"[c]crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale=1080:{hc}:flags=lanczos,unsharp=5:5:0.55:5:5:0,setsar=1[cam];"
            f"[j]crop={j['w']}:{j['h']}:{j['x']}:{j['y']},scale=1080:{1920 - hc}:flags=lanczos,setsar=1[jogo];"
            f"[cam][jogo]vstack=inputs=2,drawbox=x=0:y={hc - 3}:w=1080:h=6:color=black:t=fill"
        )
    if layout == "tela_cheia":
        r = plano["recorte"]
        trechos = plano.get("trechos") or []
        x = cam.expressao_x(trechos, r["x"]) if len(trechos) > 1 else trechos[0]["x"] if trechos else r["x"]  # segue quem está falando
        recorte = f"crop={r['w']}:{r['h']}:{x}:{r['y']},scale=1080:1920:flags=lanczos,setsar=1"
        inteiro = cam.expressao_inteiro(trechos)
        if not inteiro:
            return f"[0:v]{recorte}"
        # vídeo editado: plano aberto aparece inteiro, com fundo desfocado; close continua recortado no rosto
        return (
            f"[0:v]split=3[r][a][b];[r]{recorte}[vr];"
            "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            "gblur=sigma=40,eq=brightness=-0.2:saturation=1.15[fundo];"
            "[b]scale=1080:1920:force_original_aspect_ratio=decrease[frente];"
            "[fundo][frente]overlay=(W-w)/2:(H-h)/2,setsar=1[vi];"
            f"[vr][vi]overlay=0:0:enable='{inteiro}'"
        )
    return (
        "[0:v]split=2[a][b];"
        "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "gblur=sigma=40,eq=brightness=-0.2:saturation=1.15[fundo];"
        "[b]scale=1080:1920:force_original_aspect_ratio=decrease[frente];"
        "[fundo][frente]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )


REGIOES_SHORT = {"dividido": [(0, 0, 1080, 757), (0, 763, 1080, 1157)]}


def _cor_do_video(est: dict, ajuste: dict) -> str:
    nome = ajuste.get("filtro") or est["filtro"]
    forca = ajuste.get("intensidade", 100) if ajuste.get("filtro") else est["filtro_forca"]
    cadeia = filtros.cadeia(nome, forca)
    return f"{cadeia}," if cadeia else ""


def _agenda_short(layout: str, quadros: int, duracao: float, momento: float, picos: list[tuple[float, float]]) -> list[efeitos.Movimento]:
    """Zoom na reação e pequenos avanços nos picos, sem tirar o rosto nem o jogo de quadro."""
    if layout in ("dividido", "pip"):
        camera = efeitos.Movimento(quadros, 1.0, 1.04, (0.5, 0.46))
        jogo = efeitos.Movimento(quadros, 1.0, 1.06)
        for n, (t, _) in enumerate(picos):
            if abs(t - momento) < 3.2:
                continue
            (camera if n % 2 else jogo).plano(t - 0.08, t + 1.5, 0.5, 0.46 if n % 2 else 0.5, 1.13)
        camera.plano(momento - 0.12, min(duracao, momento + 2.8), 0.5, 0.44, 1.3, entrada=0.14)
        jogo.plano(momento - 0.12, min(duracao, momento + 2.8), 0.5, 0.5, 1.14, entrada=0.14)
        camera.impacto(momento, 0.55, 6.0)
        return [camera, jogo]
    tudo = efeitos.Movimento(quadros, 1.0, 1.06, (0.5, 0.42 if layout == "tela_cheia" else 0.5))
    for t, _ in picos:
        if abs(t - momento) >= 3.2:
            tudo.plano(t - 0.08, t + 1.5, 0.5, 0.45, 1.1)
    tudo.plano(momento - 0.12, min(duracao, momento + 2.8), 0.5, 0.44, 1.24, entrada=0.14)
    tudo.impacto(momento, 0.45, 6.0)
    return [tudo]


def _reacao_grande(quadro: np.ndarray, pip: dict, p: float) -> None:
    """Na hora da reação, a webcam cresce no meio da tela."""
    x, y, w, h = pip["x"], pip["y"], pip["w"], pip["h"]
    cam = quadro[y:y + h, x:x + w].copy()
    quadro[y:y + h, x:x + w] = cv2.flip(quadro[y + h:y + 2 * h, x:x + w], 0)  # a webcam sai do topo em vez de aparecer duas vezes
    fundo = cv2.resize(cv2.GaussianBlur(cv2.resize(quadro, (270, 480), interpolation=cv2.INTER_AREA), (0, 0), 5), (1080, 1920))
    quadro[:] = cv2.addWeighted(quadro, 1 - p, cv2.convertScaleAbs(fundo, alpha=.45), p, 0)
    e = 1 + (min(1.0, 1000 / w) - 1) * p
    nw, nh = int(w * e) // 2 * 2, int(h * e) // 2 * 2
    grande = cv2.resize(cam, (nw, nh), interpolation=cv2.INTER_CUBIC)
    cy = int(y + h / 2 + (760 - y - h / 2) * p)
    y0, x0 = max(0, cy - nh // 2), (1080 - nw) // 2
    quadro[y0:y0 + nh, x0:x0 + nw] = grande[:quadro.shape[0] - y0]


def _preparar_focos(video: Path, focos: list[dict], plano: dict, pasta: Path) -> list[dict]:
    """Recorta em alta qualidade cada ponto da tela que o streamer citou."""
    px, py, pw, ph = foco.painel(plano)
    prontos = []
    for n, f in enumerate(focos):
        destino = pasta / f"foco_{n}.mp4"
        try:
            executar(["ffmpeg", "-v", "error", "-y", "-ss", f"{f['t']:.3f}", "-i", str(video), "-t", f"{f['dur'] + .2:.3f}", "-an",
                      "-vf", f"crop={f['w']}:{f['h']}:{f['x']}:{f['y']},scale={pw // 2 * 2}:{ph // 2 * 2}:flags=lanczos,unsharp=5:5:0.7:5:5:0,fps={efeitos.FPS}",
                      "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", str(destino)])
        except RuntimeError:
            destino.unlink(missing_ok=True)  # o vídeo continua normal, só sem esta aproximação
            continue
        prontos.append({**f, "arquivo": destino, "painel": (px, py, pw, ph), "video": None, "ultimo": None})
    return prontos


def _colar_foco(quadro: np.ndarray, f: dict, t: float) -> None:
    if f["video"] is None:
        f["video"] = cv2.VideoCapture(str(f["arquivo"]))
    ok, img = f["video"].read()
    img = img if ok else f["ultimo"]
    if img is None:
        return
    f["ultimo"] = img
    px, py, pw, ph = f["painel"]
    p = max(0.0, min(1.0, (t - f["t"]) / .2, (f["t"] + f["dur"] - t) / .16))
    e = .84 + .16 * (1 - (1 - p) ** 3)
    nw, nh = int(pw * e) // 2 * 2, int(ph * e) // 2 * 2
    peq = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    cv2.rectangle(peq, (0, 0), (nw - 1, nh - 1), (68, 181, 242), 8)
    x, y = px + (pw - nw) // 2, py + (ph - nh) // 2
    area = quadro[y:y + nh, x:x + nw]
    quadro[y:y + nh, x:x + nw] = cv2.addWeighted(peq, min(1.0, p * 1.8), area, 1 - min(1.0, p * 1.8), 0)


def _quadros_short(origem, regioes: list[tuple], movimentos: list[efeitos.Movimento], total: int, cor: tuple[int, int, int], pip: dict | None = None, momento: float = 0.0, focos: list[dict] | None = None,
                   tomadas: list[dict] | None = None):
    for i, quadro in enumerate(origem):
        agora = i / efeitos.FPS
        tomada = next((e for e in tomadas or [] if e["ini"] <= agora < e["fim"]), None)
        if tomada:  # rosto ou jogo na tela toda: aproxima devagar, com um tranco quando o rosto reage
            p = (agora - tomada["ini"]) / max(.1, tomada["fim"] - tomada["ini"])
            z = (1.0 + .06 * p) if tomada["tipo"] == "jogo" else (1.04 + .05 * p)
            tremor = float(movimentos[0].tremor[i]) if tomada["tipo"] == "rosto" else 0.0
            dx, dy = (tremor * np.sin(i * 2.4), tremor * np.cos(i * 3.1)) if tremor > .3 else (0.0, 0.0)
            cy = 880 if tomada["tipo"] == "rosto" else 960
            m = np.array([[z, 0, 540 - z * 540 + dx], [0, z, cy - z * cy + dy]], dtype=np.float64)
            quadro = efeitos.aplicar(quadro, m)
            if cor:
                cv2.rectangle(quadro, (0, 0), (int(1080 * (i + 1) / total), 9), cor, -1)
            yield quadro
            continue
        if pip:  # o jogo aproxima na tela inteira e a webcam continua por cima
            x, y, w, h = pip["x"], pip["y"], pip["w"], pip["h"]
            camera = efeitos.aplicar(quadro[y:y + h, x:x + w].copy(), movimentos[0].matriz(i, w, h))
            quadro = efeitos.aplicar(quadro, movimentos[1].matriz(i, 1080, 1920)).copy()
            quadro[y:y + h, x:x + w] = efeitos.clarear(camera, float(movimentos[0].clarao[i]))
        else:
            for (x, y, w, h), mov in zip(regioes, movimentos):
                parte = efeitos.aplicar(quadro[y:y + h, x:x + w], mov.matriz(i, w, h))
                quadro[y:y + h, x:x + w] = efeitos.clarear(parte, float(mov.clarao[i]))
        for f in focos or []:
            if f["t"] <= agora < f["t"] + f["dur"]:
                webcam = quadro[pip["y"]:pip["y"] + pip["h"], pip["x"]:pip["x"] + pip["w"]].copy() if pip else None
                _colar_foco(quadro, f, agora)
                if pip:
                    quadro[pip["y"]:pip["y"] + pip["h"], pip["x"]:pip["x"] + pip["w"]] = webcam
        if pip:
            t = i / efeitos.FPS - momento
            if -.05 <= t <= 1.9:
                _reacao_grande(quadro, pip, min(1.0, (t + .05) / .18, (1.9 - t) / .22))
        if cor:  # barra de progresso no topo, só se ligada em Estilo do vídeo
            cv2.rectangle(quadro, (0, 0), (int(1080 * (i + 1) / total), 9), cor, -1)
        yield quadro


def _rebobinar(quadros, fim_previa: float):
    """Fim da prévia do auge: a imagem treme, perde a cor e clareia, como fita voltando; depois um clarão e a história começa."""
    for i, q in enumerate(quadros):
        t = i / efeitos.FPS
        falta = fim_previa - t
        if 0 <= falta < .35:
            p = 1 - falta / .35
            cinza = cv2.cvtColor(cv2.cvtColor(q, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
            q = cv2.addWeighted(q, 1 - .7 * p, cinza, .7 * p, 0)
            desloca = int(18 * p) * (1 if i % 2 else -1)
            q = np.roll(q, desloca, axis=1)
            linhas = q[::6].astype(np.int16) + int(60 * p)
            q[::6] = np.clip(linhas, 0, 255).astype(np.uint8)
            q = efeitos.clarear(q, .35 * p)
        elif 0 <= t - fim_previa < .16:
            q = efeitos.clarear(q, .75 * (1 - (t - fim_previa) / .16))
        yield q


def _com_encerramento(quadros, extra: int):
    """Depois do último quadro, o fim do vídeo desfocado e escuro, aproximando devagar, para o seu @ aparecer."""
    ultimo = None
    for q in quadros:
        ultimo = q
        yield q
    if ultimo is None or extra <= 0:
        return
    base = ultimo.copy()
    base[:12] = base[12:13]  # tira a barra de progresso, se houver
    fundo = cv2.resize(cv2.GaussianBlur(cv2.resize(base, (270, 480), interpolation=cv2.INTER_AREA), (0, 0), 3.5), (1080, 1920), interpolation=cv2.INTER_CUBIC)
    for k in range(extra):
        p = k / max(1, extra - 1)
        escuro = min(1.0, k / 8)
        z = 1.0 + .07 * p
        m = np.array([[z, 0, 540 - z * 540], [0, z, 960 - z * 960]], dtype=np.float64)
        atual = efeitos.aplicar(fundo, m)
        nitido = efeitos.aplicar(base, m) if escuro < 1 else atual
        mistura = cv2.addWeighted(nitido, 1 - escuro, atual, escuro, 0)
        yield cv2.convertScaleAbs(mistura, alpha=1 - .55 * escuro)


def _renderizar_com_movimento(fonte: Path, pasta: Path, plano: dict, grupos: list[dict], gancho: str, contexto: str,
                              credito: str, duracao: float, momento: float | None, estilo: dict | None,
                              ajuste: dict | None = None, focos: list[dict] | None = None) -> None:
    est = estilos.normalizar(estilo)
    ajuste = ajuste or {}
    focos = _preparar_focos(fonte, focos, plano, pasta) if focos else []
    total = max(1, round(duracao * efeitos.FPS))
    picos = efeitos.batidas(fonte, duracao=duracao, espaco=est["ritmo"])
    if momento is None:
        momento = max(picos, key=lambda p: p[1])[0] if picos else duracao * 0.65
    momento = min(max(0.3, momento), max(0.3, duracao - 0.5))
    layout = plano["layout"]
    pip = plano.get("pip") if layout == "pip" else None
    hc = int(plano.get("altura_cam", 760))
    regioes = [(pip["x"], pip["y"], pip["w"], pip["h"]), (0, pip["y"] + pip["h"], 1080, 1920 - pip["y"] - pip["h"])] if pip else [(0, 0, 1080, hc - 3), (0, hc + 3, 1080, 1917 - hc)] if layout == "dividido" else REGIOES_SHORT.get(layout, [(0, 0, 1080, 1920)])
    movimentos = _agenda_short(layout, total, duracao, momento, picos)
    for mov in movimentos:
        mov.z = 1 + (mov.z - 1) * est["zoom_forca"] / 100
    previa = float(ajuste.get("previa") or 0) if ajuste else 0.0  # fim da prévia do auge, no começo do vídeo
    tomadas = planejar_tomadas(plano, grupos, duracao, momento, picos, fonte, est, previa)
    if tomadas:
        plano = {**plano, **_recortes_cheios(plano, fonte)}
    outro = duracao_encerramento(duracao, est) if not ajuste.get("trilha") else 0.0
    extra = round(outro * efeitos.FPS)
    filtro = f"{_filtro_video(plano, tomadas)},fps={efeitos.FPS},format=bgr24[v]"
    destino = pasta / "corte_novo.mp4"
    fim_total = duracao + extra / efeitos.FPS
    if bastidores.ligado():
        bastidores.contar(trilhas=_trilhas_bastidores(grupos, gancho, est, duracao, momento, picos, tomadas, focos, extra / efeitos.FPS, layout, previa))
    try:
        quadros = _quadros_short(efeitos.ler_quadros(fonte, filtro, 1080, 1920, total), regioes, movimentos, total, estilos.cor_bgr(est["cor"]) if est.get("barra_progresso") else None, pip, momento, focos, tomadas)
        if previa:
            quadros = _rebobinar(quadros, previa)
        efeitos.gravar(
        destino, bastidores.acompanhar_quadros(_com_encerramento(quadros, extra), total + extra),
        total + extra, 1080, 1920, gerar_ass(grupos, gancho, contexto, credito, duracao, layout, est, plano.get("altura_cam"), tomadas, extra / efeitos.FPS), fonte,
        whoosh=[0.0, *[f["t"] for f in focos], *([duracao] if extra else []), *[e["ini"] for e in tomadas if e["tipo"] == "jogo"]], impacto=[momento], volume_efeitos=0.22, trilha=ajuste.get("trilha"), volume_fala=ajuste.get("volume", 100) / 100,
        filtro_extra=_cor_do_video(est, ajuste) + f"fade=t=out:st={max(0.0, fim_total - 0.25):.2f}:d=0.25",
        )
    finally:
        for f in focos:
            if f["video"] is not None:
                f["video"].release()
            Path(f["arquivo"]).unlink(missing_ok=True)
    destino.replace(pasta / "corte.mp4")


def _trilhas_bastidores(grupos, gancho, est, duracao, momento, picos, tomadas, focos, outro, layout, previa: float = 0.0) -> dict:
    """O que vai em cada faixa da timeline, para a tela que mostra a edição acontecendo."""
    if est["legenda"] == "react":
        pedacos = estilos.picar(grupos)
    elif est["legenda"] in ("palavra", "impacto") or (estilos.modelo_editor(est) or {}).get("palavra_a_palavra"):
        pedacos = [{"palavras": [p]} for g in grupos for p in g.get("palavras") or []]
    else:
        pedacos = grupos
    legendas = [{"ini": round(float(g["palavras"][0]["ini"]), 2), "fim": round(float(g["palavras"][-1]["fim"]) + .25, 2), "texto": " ".join(p["p"] for p in g["palavras"])}
                for g in pedacos if g.get("palavras")]
    fortes = sorted(picos, key=lambda p: -p[1])[:8]
    return {
        "duracao": round(duracao, 2), "layout": layout, "momento": round(momento, 2), "outro": round(outro, 2),
        "titulo": {"texto": gancho, "fim": est["tempo_gancho"]} if gancho and est["gancho"] != "nenhum" else None,
        "legendas": legendas, "zooms": sorted(round(t, 2) for t, _ in fortes),
        "cameras": [{"ini": e["ini"], "fim": e["fim"], "tipo": e["tipo"]} for e in tomadas],
        "focos": [{"t": round(f["t"], 2), "dur": round(f["dur"], 2)} for f in focos],
        "sons": [{"t": 0.0, "nome": "Whoosh de abertura"}, {"t": round(momento, 2), "nome": "Impacto na reação"},
                 *[{"t": round(e["ini"], 2), "nome": "Whoosh da troca de câmera"} for e in tomadas if e["tipo"] == "jogo"]],
        "legenda_modelo": est["legenda"], "cor": "#" + estilos.CORES[est["cor"]], "previa": round(previa, 2),
    }


def planejar_tomadas(plano: dict, grupos: list[dict], duracao: float, momento: float | None, picos: list, fonte: Path, est: dict, previa: float = 0.0) -> list[dict]:
    if plano.get("layout") != "dividido" or not est.get("camera_dinamica", True) or not plano.get("moldura") or not plano.get("jogo"):
        return []
    if previa:  # a prévia do auge é a reação: rosto de perto; a câmera dinâmica volta depois da fita rebobinar
        return [{"ini": 0.0, "fim": round(previa - .02, 3), "tipo": "rosto"}, *tm.planejar(grupos, duracao, momento, picos, inicio=previa + 1.0)]
    return tm.planejar(grupos, duracao, momento, picos)


def _recortes_cheios(plano: dict, fonte: Path) -> dict:
    largura, altura, _ = cam.dimensoes(fonte)
    return {"rosto_cheio": tm.enquadrar_rosto(plano, largura, altura), "jogo_cheio": tm.enquadrar_jogo(plano, largura, altura)}


def duracao_encerramento(duracao: float, est: dict) -> float:
    """Final com o seu @: 2,2 s, sem passar de 59,5 s (Shorts com mais de 1 minuto podem ser bloqueados)."""
    if not (est.get("arroba") and est.get("encerramento", True)):
        return 0.0
    sobra = min(2.2, 59.5 - duracao) if duracao < 59.5 else 0.0
    return round(sobra, 2) if sobra >= 1.2 else 0.0


def renderizar(fonte: Path, pasta: Path, plano: dict, grupos: list[dict], gancho: str, contexto: str,
               credito: str, duracao: float, momento: float | None = None, estilo: dict | None = None,
               ajuste: dict | None = None, focos: list[dict] | None = None) -> None:
    try:
        _renderizar_com_movimento(fonte, pasta, plano, grupos, gancho, contexto, credito, duracao, momento, estilo, ajuste, focos)
    except Exception:
        (pasta / "corte_novo.mp4").unlink(missing_ok=True)
        if ajuste:  # a versão simples perderia os sons e o filtro escolhidos na timeline
            raise
        _renderizar_simples(fonte, pasta, plano, grupos, gancho, contexto, credito, duracao, estilo)
    _finalizar_corte(pasta, grupos, duracao)


def _renderizar_simples(fonte: Path, pasta: Path, plano: dict, grupos: list[dict], gancho: str, contexto: str,
                        credito: str, duracao: float, estilo: dict | None = None) -> None:
    fim = max(0.0, duracao - 0.25)
    with tempfile.TemporaryDirectory(prefix="clipador_") as tmp:
        tmp = Path(tmp)
        ass_texto = gerar_ass(grupos, gancho, contexto, credito, duracao, plano["layout"], estilo, plano.get("altura_cam"))
        (tmp / "legenda.ass").write_text(ass_texto, encoding="utf-8")
        estilos.copiar_fontes(ass_texto, tmp / "fontes")
        filtro = (
            f"{_filtro_video(plano)},fps=30,fade=t=out:st={fim:.2f}:d=0.25,"
            "ass=legenda.ass:fontsdir=fontes,format=yuv420p[v]"
        )
        executar(
            ["ffmpeg", "-v", "error", "-y", "-i", str(fonte.resolve()), "-filter_complex", filtro,
             "-map", "[v]", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
             "-maxrate", "20M", "-bufsize", "40M", "-profile:v", "high", "-af",
             f"loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,afade=t=in:d=0.08,afade=t=out:st={fim:.2f}:d=0.25",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "saida.mp4"],
            cwd=tmp,
        )
        shutil.move(str(tmp / "saida.mp4"), pasta / "corte.mp4")


def _finalizar_corte(pasta: Path, grupos: list[dict], duracao: float) -> None:
    executar(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{min(2.0, duracao / 2):.2f}", "-i", str(pasta / "corte.mp4"),
         "-frames:v", "1", "-q:v", "2", str(pasta / "capa.jpg")]
    )
    (pasta / "legenda.srt").write_text(gerar_srt(grupos), encoding="utf-8")
