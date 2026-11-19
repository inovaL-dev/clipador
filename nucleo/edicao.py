"""Transcreve e monta o vídeo vertical final."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2

from . import efeitos, estilos, filtros
from . import foco
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


def transcrever(modelo, video: Path, idioma: str) -> list[dict]:
    import numpy as np

    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True, **sem_janela(),
    ).stdout
    if len(pcm) < 32000:
        return []
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    trechos, _ = modelo.transcribe(
        audio, language=idioma, word_timestamps=True, vad_filter=True, beam_size=3,
        condition_on_previous_text=False,
    )
    return [
        {"p": p.word.strip(), "ini": round(p.start, 3), "fim": round(p.end, 3)}
        for t in trechos for p in (t.words or []) if p.word.strip()
    ]


def ouvir_trecho(modelo, pcm, idioma: str) -> str:
    """Escuta rápida da live, usada para perceber exclamações curtas."""
    import numpy as np

    audio = pcm.astype(np.float32) / 32768
    trechos, _ = modelo.transcribe(
        audio, language=idioma, beam_size=1, vad_filter=True, without_timestamps=True,
        condition_on_previous_text=False,
    )
    return " ".join(t.text.strip() for t in trechos)


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


def gerar_ass(grupos: list[dict], gancho: str, contexto: str, credito: str, duracao: float, layout: str,
              estilo: dict | None = None) -> str:
    est = estilos.normalizar(estilo)
    credito_pos = POSICAO_CREDITO.get(layout, POSICAO_CREDITO["dividido"])
    x_gancho, y_gancho = estilos.ponto(est, "gancho_x", "gancho_y", 1080, 1920, 540, POSICAO_GANCHO.get(layout, 800))
    x_legenda, y_legenda = estilos.ponto(est, "legenda_x", "legenda_y", 1080, 1920, 540, BASE_LEGENDA)
    saida = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        estilos.estilo_legenda(est, 66), estilos.estilo_gancho(est, 54),
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

    saida += estilos.eventos_legenda(grupos, duracao, est, x_legenda, y_legenda, 66, 18, _tempo_ass)
    return "\n".join(saida) + "\n"


def gerar_srt(grupos: list[dict]) -> str:
    blocos = []
    for n, g in enumerate((g for g in grupos if g["palavras"]), 1):
        texto = " ".join(p["p"] for p in g["palavras"])
        blocos.append(f"{n}\n{_tempo_srt(g['palavras'][0]['ini'])} --> {_tempo_srt(g['palavras'][-1]['fim'])}\n{texto}\n")
    return "\n".join(blocos)


def _filtro_video(plano: dict) -> str:
    layout = plano["layout"]
    if layout == "pip":
        c, j, p = plano["camera"], plano["jogo"], plano["pip"]
        return (
            "[0:v]split=2[c][j];"
            f"[j]crop={j['w']}:{j['h']}:{j['x']}:{j['y']},scale=1080:1920:flags=lanczos,setsar=1[jogo];"
            f"[c]crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale={p['w']}:{p['h']}:flags=lanczos,unsharp=5:5:0.55:5:5:0,setsar=1[cam];"
            f"[jogo][cam]overlay={p['x']}:{p['y']}"
        )
    if layout == "dividido":
        c, j = plano["camera"], plano["jogo"]
        return (
            "[0:v]split=2[c][j];"
            f"[c]crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale=1080:760:flags=lanczos,unsharp=5:5:0.55:5:5:0,setsar=1[cam];"
            f"[j]crop={j['w']}:{j['h']}:{j['x']}:{j['y']},scale=1080:1160:flags=lanczos,setsar=1[jogo];"
            "[cam][jogo]vstack=inputs=2,drawbox=x=0:y=757:w=1080:h=6:color=black:t=fill"
        )
    if layout == "tela_cheia":
        r = plano["recorte"]
        return f"[0:v]crop={r['w']}:{r['h']}:{r['x']}:{r['y']},scale=1080:1920:flags=lanczos,setsar=1"
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


def _quadros_short(origem, regioes: list[tuple], movimentos: list[efeitos.Movimento], total: int, cor: tuple[int, int, int], pip: dict | None = None, momento: float = 0.0, focos: list[dict] | None = None):
    for i, quadro in enumerate(origem):
        if pip:  # o jogo aproxima na tela inteira e a webcam continua por cima
            x, y, w, h = pip["x"], pip["y"], pip["w"], pip["h"]
            camera = efeitos.aplicar(quadro[y:y + h, x:x + w].copy(), movimentos[0].matriz(i, w, h))
            quadro = efeitos.aplicar(quadro, movimentos[1].matriz(i, 1080, 1920)).copy()
            quadro[y:y + h, x:x + w] = efeitos.clarear(camera, float(movimentos[0].clarao[i]))
        else:
            for (x, y, w, h), mov in zip(regioes, movimentos):
                parte = efeitos.aplicar(quadro[y:y + h, x:x + w], mov.matriz(i, w, h))
                quadro[y:y + h, x:x + w] = efeitos.clarear(parte, float(mov.clarao[i]))
        agora = i / efeitos.FPS
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
        cv2.rectangle(quadro, (0, 0), (int(1080 * (i + 1) / total), 9), cor, -1)
        yield quadro


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
    regioes = [(pip["x"], pip["y"], pip["w"], pip["h"]), (0, pip["y"] + pip["h"], 1080, 1920 - pip["y"] - pip["h"])] if pip else REGIOES_SHORT.get(layout, [(0, 0, 1080, 1920)])
    movimentos = _agenda_short(layout, total, duracao, momento, picos)
    for mov in movimentos:
        mov.z = 1 + (mov.z - 1) * est["zoom_forca"] / 100
    filtro = f"{_filtro_video(plano)},fps={efeitos.FPS},format=bgr24[v]"
    destino = pasta / "corte_novo.mp4"
    try:
        efeitos.gravar(
        destino, _quadros_short(efeitos.ler_quadros(fonte, filtro, 1080, 1920, total), regioes, movimentos, total, estilos.cor_bgr(est["cor"]), pip, momento, focos),
        total, 1080, 1920, gerar_ass(grupos, gancho, contexto, credito, duracao, layout, est), fonte,
        whoosh=[0.0, *[f["t"] for f in focos]], impacto=[momento], volume_efeitos=0.22, trilha=ajuste.get("trilha"), volume_fala=ajuste.get("volume", 100) / 100,
        filtro_extra=_cor_do_video(est, ajuste) + f"fade=t=out:st={max(0.0, duracao - 0.25):.2f}:d=0.25",
        )
    finally:
        for f in focos:
            if f["video"] is not None:
                f["video"].release()
            Path(f["arquivo"]).unlink(missing_ok=True)
    destino.replace(pasta / "corte.mp4")


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
        ass_texto = gerar_ass(grupos, gancho, contexto, credito, duracao, plano["layout"], estilo)
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
