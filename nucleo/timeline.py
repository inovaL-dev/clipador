"""Regras da timeline: trechos mantidos, legendas, sons e montagem do vídeo editado."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

from . import filtros
from .biblioteca import SR, gravar_wav, ler_wav
from .contexto import retextar
from .plataformas import sem_janela

DURACAO_MINIMA = 0.2
MAXIMO_SONS = 400
MAXIMO_BLOCOS = 4000


def _numero(valor, minimo: float, maximo: float, nome: str) -> float:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ValueError(f"{nome} inválido.") from None
    if not np.isfinite(numero):
        raise ValueError(f"{nome} inválido.")
    return min(maximo, max(minimo, numero))


def validar_cortes(cortes, duracao: float) -> list[list[float]]:
    if not isinstance(cortes, list) or not cortes:
        raise ValueError("O vídeo precisa ter pelo menos um trecho.")
    limpos = []
    for par in cortes[:500]:
        if not isinstance(par, (list, tuple)) or len(par) != 2:
            raise ValueError("Trecho inválido.")
        a, b = _numero(par[0], 0, duracao, "Trecho"), _numero(par[1], 0, duracao, "Trecho")
        if b - a >= DURACAO_MINIMA:
            limpos.append([round(a, 3), round(b, 3)])
    limpos.sort()
    if not limpos:
        raise ValueError("O vídeo precisa ter pelo menos um trecho.")
    juntos = [limpos[0]]
    for a, b in limpos[1:]:
        if a <= juntos[-1][1] + 0.001:
            juntos[-1][1] = max(juntos[-1][1], b)
        else:
            juntos.append([a, b])
    return juntos


def duracao_total(cortes: list[list[float]]) -> float:
    return sum(b - a for a, b in cortes)


def saida_de(t: float, cortes: list[list[float]]) -> float | None:
    """Converte o tempo do vídeo original para o tempo do vídeo editado."""
    corrido = 0.0
    for a, b in cortes:
        if a <= t < b:
            return corrido + t - a
        corrido += b - a
    return None


def proxima_saida(t: float, cortes: list[list[float]]) -> float:
    corrido = 0.0
    for a, b in cortes:
        if t < b:
            return corrido + max(0.0, t - a)
        corrido += b - a
    return corrido


def mapear_grupos(grupos: list[dict], cortes: list[list[float]]) -> list[dict]:
    saida = []
    for grupo in grupos:
        palavras = []
        for p in grupo.get("palavras", []):
            meio = (float(p["ini"]) + float(p["fim"])) / 2
            alvo = saida_de(meio, cortes)
            if alvo is None:
                continue
            metade = max(0.02, (float(p["fim"]) - float(p["ini"])) / 2)
            palavras.append({"p": p["p"], "ini": round(max(0.0, alvo - metade), 3), "fim": round(alvo + metade, 3)})
        if palavras:
            saida.append({"ini": palavras[0]["ini"], "fim": palavras[-1]["fim"], "palavras": palavras})
    return saida


def validar_sons(sons, duracao: float, biblioteca) -> list[dict]:
    limpos = []
    for s in (sons or [])[:MAXIMO_SONS]:
        if not isinstance(s, dict) or not biblioteca.existe(str(s.get("som"))):
            raise ValueError("Um dos sons não existe mais na biblioteca.")
        limpos.append({"som": str(s["som"]), "t": round(_numero(s.get("t"), 0, duracao, "Tempo do som"), 3),
                       "volume": round(_numero(s.get("volume", 0.5), 0, 1.5, "Volume do som"), 3)})
    return sorted(limpos, key=lambda s: s["t"])


def validar_blocos(blocos, duracao: float) -> list[dict]:
    limpos = []
    for b in (blocos or [])[:MAXIMO_BLOCOS]:
        if not isinstance(b, dict):
            raise ValueError("Legenda inválida.")
        texto = re.sub(r"\s+", " ", str(b.get("texto", ""))).strip()[:160]
        if not texto:
            continue
        ini = _numero(b.get("ini"), 0, duracao, "Tempo da legenda")
        fim = _numero(b.get("fim"), 0, duracao, "Tempo da legenda")
        if fim - ini < 0.1:
            fim = min(duracao, ini + 0.5)
        limpos.append({"ini": round(ini, 3), "fim": round(fim, 3), "texto": texto})
    return sorted(limpos, key=lambda b: b["ini"])


def blocos_de_grupos(grupos: list[dict]) -> list[dict]:
    return [{"ini": float(g["ini"]), "fim": float(g["fim"]), "texto": " ".join(p["p"] for p in g.get("palavras", []))}
            for g in grupos if g.get("palavras")]


def grupos_de_blocos(blocos: list[dict], atuais: list[dict]) -> list[dict]:
    """Mantém o tempo de cada palavra quando a legenda não foi alterada."""
    conhecidos: dict[str, list[dict]] = {}
    for g in atuais:
        conhecidos.setdefault(" ".join(p["p"] for p in g.get("palavras", [])), []).append(g)
    saida = []
    for b in blocos:
        grupo = next((g for g in conhecidos.get(b["texto"], []) if abs(float(g["ini"]) - b["ini"]) < 0.06 and abs(float(g["fim"]) - b["fim"]) < 0.06), None)
        saida.append(grupo or retextar({"ini": b["ini"], "fim": b["fim"], "palavras": []}, b["texto"]))
    return saida


def mesmas_legendas(a: list[dict], b: list[dict]) -> bool:
    x, y = blocos_de_grupos(a), blocos_de_grupos(b)
    return len(x) == len(y) and all(p["texto"] == q["texto"] and abs(p["ini"] - q["ini"]) < 0.06 and abs(p["fim"] - q["fim"]) < 0.06 for p, q in zip(x, y))


def validar_edicao(dados: dict, duracao: float, biblioteca) -> dict:
    return {
        "cortes": validar_cortes(dados.get("cortes"), duracao),
        "sons": validar_sons(dados.get("sons"), duracao, biblioteca),
        "filtro": filtros.validar(dados.get("filtro")),
        "intensidade": round(_numero(dados.get("intensidade", 100), 0, 100, "Intensidade")),
        "volume": round(_numero(dados.get("volume", 100), 0, 200, "Volume")),
    }


def encurtar_cortes(cortes: list[list[float]], alvo: float) -> list[list[float]]:
    """Mantém o final do vídeo, onde normalmente está a reação."""
    restante, saida = alvo, []
    for a, b in reversed(cortes):
        if restante <= 0:
            break
        inicio = max(a, b - restante)
        saida.insert(0, [round(inicio, 3), b])
        restante -= b - inicio
    return saida


def montar_fonte(fonte: Path, cortes: list[list[float]], destino: Path, duracao: float) -> Path:
    """Junta os trechos mantidos em um arquivo intermediário, com precisão de quadro."""
    if len(cortes) == 1 and cortes[0][0] <= 0.01 and cortes[0][1] >= duracao - 0.01:
        return fonte
    video = "".join(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}];" for i, (a, b) in enumerate(cortes))
    audio = "".join(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.012,afade=t=out:st={max(0.0, b - a - 0.012):.3f}:d=0.012[a{i}];"
                    for i, (a, b) in enumerate(cortes))
    tem_audio = _tem_audio(fonte)
    pares = "".join(f"[v{i}]" + (f"[a{i}]" if tem_audio else "") for i in range(len(cortes)))
    grafo = video + (audio if tem_audio else "") + f"{pares}concat=n={len(cortes)}:v=1:a={int(tem_audio)}[v]" + ("[a]" if tem_audio else "")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(fonte), "-filter_complex", grafo, "-map", "[v]"]
    if tem_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "256k"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(destino)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **sem_janela())
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "falha ao juntar os trechos").strip()[-300:])
    return destino


def _tem_audio(video: Path) -> bool:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
                       capture_output=True, text=True, **sem_janela())
    return bool(r.stdout.strip())


def criar_trilha(sons: list[dict], cortes: list[list[float]], duracao: float, biblioteca, destino: Path) -> None:
    """Mistura os efeitos nos tempos do vídeo já editado. Sons de trechos apagados saem junto."""
    trilha = np.zeros((int(duracao * SR) + 1, 2), dtype=np.float32)
    guardados: dict[str, np.ndarray] = {}
    for s in sons:
        alvo = saida_de(float(s["t"]), cortes)
        if alvo is None or not biblioteca.existe(s["som"]):  # o som pode ter sido apagado da biblioteca
            continue
        if s["som"] not in guardados:
            guardados[s["som"]] = ler_wav(biblioteca.caminho(s["som"]))
        ini = int(alvo * SR)
        parte = guardados[s["som"]][: max(0, len(trilha) - ini)]
        trilha[ini:ini + len(parte)] += parte * float(s["volume"])
    gravar_wav(destino, trilha)


def picos_do_audio(pcm: np.ndarray, pontos: int = 1600) -> list[float]:
    if not len(pcm):
        return []
    tamanho = max(1, len(pcm) // pontos)
    n = len(pcm) // tamanho
    blocos = np.abs(pcm[: n * tamanho].reshape(n, tamanho).astype(np.float32)).max(axis=1) / 32768
    maior = float(blocos.max()) or 1.0
    return [round(float(v / maior), 3) for v in blocos]
