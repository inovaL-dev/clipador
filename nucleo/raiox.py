"""Desmonta um vídeo que deu certo em gancho, ritmo, cores e cortes."""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from . import estilos
from .plataformas import sem_janela

TIPOS_GANCHO = (("pergunta", "Pergunta", r"\?|^(como|por que|porque|qual|quem|quanto|você sabia|sabia que|e se)\b"),
                ("alerta", "Alerta", r"\b(nunca|pare|para de|cuidado|não faça|não use|erro|errado|perigo)\b"),
                ("segredo", "Segredo", r"\b(segredo|ninguém|descobri|truque|escondido|verdade|revelei|hack)\b"),
                ("resultado", "Resultado", r"\b(me fez|consegui|ganhei|viralizei|viralizar|bombou|fiz|cheguei|\d+ ?(mil|milh|k|m|dias?|semanas?|horas?|reais))\b"),
                ("numero", "Número", r"\d"))
CHAMADA = r"\b(comenta|comente|segue|siga|me segue|inscreva|inscreve|curte|curta|compartilha|link|salva|salve)\b"


def tipo_do_gancho(frase: str | None) -> tuple[str, str]:
    texto = (frase or "").strip().lower()
    for ident, nome, regra in TIPOS_GANCHO:
        if texto and re.search(regra, texto):
            return ident, nome
    return "afirmacao", "Afirmação direta"


def _audio(video: Path, ini: float = 0, dur: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{ini:.2f}", "-i", str(video), *(["-t", f"{dur:.2f}"] if dur else []), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    saida = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=180, **sem_janela()).stdout
    return np.frombuffer(saida, dtype=np.int16).astype(np.float32) / 32768


def _frases(audio: np.ndarray, modelo, idioma: str | None) -> list[str]:
    if modelo is None or audio.size < 8000 or float(np.sqrt((audio ** 2).mean())) < .006:
        return []
    trechos, _ = modelo.transcribe(audio, language=idioma or None, beam_size=1, condition_on_previous_text=False)
    return [t.text.strip() for t in trechos if t.text.strip() and t.no_speech_prob < .6]


def medir_cores(quadros: list[np.ndarray]) -> dict:
    pontos = np.vstack([cv2.resize(q, (40, 71), interpolation=cv2.INTER_AREA).reshape(-1, 3) for q in quadros]).astype(np.float32) / 255
    lab = cv2.cvtColor(pontos.reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3)
    criterio = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 18, .4)
    cv2.setRNGSeed(7)
    _, rotulos, _ = cv2.kmeans(lab, 6, None, criterio, 2, cv2.KMEANS_PP_CENTERS)
    rotulos = rotulos.flatten()
    grupos = []
    for k in range(6):
        membros = pontos[rotulos == k]
        if len(membros):
            b, g, r = (np.median(membros, axis=0) * 255).round().astype(int).tolist()
            grupos.append({"hex": f"#{r:02X}{g:02X}{b:02X}", "peso": round(len(membros) / len(pontos), 3), "rgb": (r, g, b)})
    grupos.sort(key=lambda c: -c["peso"])
    hsv = cv2.cvtColor(pontos.reshape(-1, 1, 3), cv2.COLOR_BGR2HSV).reshape(-1, 3)
    satur, brilho = float(hsv[:, 1].mean()), float(hsv[:, 2].mean())
    temperatura = float((pontos[:, 2] - pontos[:, 0]).mean())
    contraste = float(lab[:, 0].std() / 100)
    vivo = lambda c: (max(c["rgb"]) - min(c["rgb"])) / 255 * (max(c["rgb"]) / 255) * min(1, c["peso"] * 12)
    destaque = max(grupos, key=vivo)
    return {"paleta": [{"hex": c["hex"], "peso": c["peso"]} for c in grupos], "destaque": destaque["hex"], "saturacao": round(satur, 2), "brilho": round(brilho, 2),
            "temperatura": round(temperatura, 3), "contraste": round(contraste, 2), "filtro": filtro_parecido(satur, brilho, temperatura, contraste), "cor": cor_parecida(destaque["rgb"])}


def filtro_parecido(satur: float, brilho: float, temperatura: float, contraste: float) -> str:
    if satur < .1:
        return "noir"
    if brilho < .36 and contraste > .2:
        return "dramatico" if satur < .4 else "gamer"
    if temperatura > .1:
        return "por_do_sol" if satur > .45 else "quente"
    if temperatura < -.07:
        return "frio"
    return "vibrante" if satur > .45 else "nenhum"


def cor_parecida(rgb: tuple[int, int, int]) -> str:
    matiz = lambda c: float(cv2.cvtColor(np.uint8([[c[::-1]]]), cv2.COLOR_BGR2HSV)[0, 0, 0]) * 2
    alvo = matiz(rgb)
    opcoes = {k: tuple(bytes.fromhex(v)) for k, v in estilos.CORES.items() if k != "branco"}
    return min(opcoes, key=lambda k: min(abs(matiz(opcoes[k]) - alvo), 360 - abs(matiz(opcoes[k]) - alvo)))


def achar_faixa(quadros: list[np.ndarray]) -> dict | None:
    """Procura a tarja de título que fica fixa no alto do vídeo."""
    achados = []
    for q in quadros:
        h, w = q.shape[:2]
        hsv = cv2.cvtColor(q[:int(h * .3)], cv2.COLOR_BGR2HSV)
        claro = ((hsv[..., 2] > 195) & (hsv[..., 1] < 70)).astype(np.uint8)
        linhas = claro.mean(axis=1) > .22
        y = 0
        while y < len(linhas):
            if not linhas[y]:
                y += 1; continue
            fim = y
            while fim < len(linhas) and linhas[fim]:
                fim += 1
            if .012 * h <= fim - y <= .08 * h:
                achados.append((y + fim) / 2 / h); break
            y = fim
    if len(achados) < len(quadros) * .4:
        return None
    return {"y": round(float(np.median(achados)), 3)}


def desmontar(video: Path, medidas: dict, quadros: list[np.ndarray], modelo=None, idioma: str | None = None) -> dict:
    dur = float(medidas.get("duracao") or 0)
    marcas = medidas.get("marcas") or []
    inicio = _audio(video, 0, 9)
    frases = _frases(inicio, modelo, idioma)
    frase = frases[0] if frases else None
    tipo, nome = tipo_do_gancho(frase)
    final = _frases(_audio(video, max(0, dur - 9), 9), modelo, idioma) if dur > 12 else []
    sentencas = [s.strip() for f in final for s in re.split(r"(?<=[.!?])\s+", f) if s.strip()]
    chamada = next((s for s in reversed(sentencas) if re.search(CHAMADA, s.lower())), None)
    todo = _audio(video)
    forca = None
    if todo.size > 16000 * 6:
        comeco, geral = float(np.sqrt((todo[:48000] ** 2).mean())), float(np.sqrt((todo ** 2).mean()))
        forca = round(20 * float(np.log10(max(comeco, 1e-4) / max(geral, 1e-4))), 1)
    terco = max(1.0, dur / 3)
    partes = [sum(terco * k <= m["t"] < terco * (k + 1) for m in marcas) for k in range(3)]
    return {"gancho": {"fala": frase, "tipo": tipo, "tipo_nome": nome, "primeira_troca": marcas[0]["t"] if marcas else None, "forca_som": forca, "palavras_s": round(len(" ".join(frases).split()) / 9, 1) if frases else None},
            "ritmo": {"cena_s": medidas.get("cena_s"), "cortes_min": medidas.get("cortes_min"), "partes": partes, "sfx_cortes": medidas.get("sfx_cortes"), "zooms_min": medidas.get("zooms_min")},
            "cores": medir_cores(quadros), "cortes": {"duracao": round(min(dur, 120), 1), "marcas": marcas, "tipos": dict(Counter(m["tipo"] for m in marcas))}, "faixa": achar_faixa(quadros), "chamada": chamada}
