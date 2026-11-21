"""Efeitos de voz e de áudio, música que abaixa sob a fala e batidas da música.

A lista de efeitos segue o catálogo de áudio do Drift (voz, rádio, espaço, textura e utilidades),
feita com filtros do próprio FFmpeg para a exportação e a prévia soarem iguais.
"""
from __future__ import annotations

import numpy as np

TAXA = 48000

# id: (nome, grupo, cadeia de filtros do FFmpeg). Tudo começa em 48 kHz para os efeitos de tom ficarem certos.
EFEITOS = {
    "limpar_voz": ("Limpar voz", "Utilidades", "highpass=f=80,afftdn=nf=-25,acompressor=threshold=0.125:ratio=3:attack=10:release=120:makeup=1.5,equalizer=f=3200:t=q:w=1:g=3"),
    "reduzir_ruido": ("Reduzir ruído", "Utilidades", "afftdn=nf=-28"),
    "compressor": ("Compressor", "Utilidades", "acompressor=threshold=0.1:ratio=4:attack=5:release=100:makeup=2"),
    "tirar_chiado": ("Tirar chiado do S", "Utilidades", "deesser=i=0.6"),
    "mais_grave": ("Reforçar graves", "Utilidades", "bass=g=7:f=110"),
    "grave": ("Voz grossa", "Voz", "asetrate=48000*0.8,aresample=48000,atempo=1.25"),
    "esquilo": ("Esquilo", "Voz", "asetrate=48000*1.35,aresample=48000,atempo=0.7407"),
    "robo": ("Robô", "Voz", "afftfilt=real='hypot(re,im)*sin(0)':imag='hypot(re,im)*cos(0)':win_size=512:overlap=0.75,volume=1.4"),
    "vilao": ("Vilão", "Voz", "asetrate=48000*0.78,aresample=48000,atempo=1.2821,aecho=0.8:0.6:40:0.35,asoftclip=type=tanh"),
    "alien": ("Alienígena", "Voz", "asetrate=48000*1.15,aresample=48000,atempo=0.8696,aphaser=in_gain=0.6:out_gain=0.9:delay=2:decay=0.6:speed=1.2"),
    "telefone": ("Telefone", "Transmissão", "highpass=f=400,lowpass=f=3200,acompressor=threshold=0.1:ratio=6,volume=1.6"),
    "radio": ("Rádio comunicador", "Transmissão", "highpass=f=600,lowpass=f=2800,acrusher=bits=10:mix=0.35,volume=1.5"),
    "megafone": ("Megafone", "Transmissão", "highpass=f=700,lowpass=f=4200,asoftclip=type=atan,volume=1.5"),
    "abafado": ("Abafado", "Transmissão", "lowpass=f=700,volume=1.3"),
    "submerso": ("Debaixo d'água", "Transmissão", "lowpass=f=450,aecho=0.8:0.7:35:0.4,volume=1.3"),
    "eco": ("Eco", "Espaço", "aecho=0.8:0.85:280:0.35"),
    "caverna": ("Caverna", "Espaço", "aecho=0.8:0.88:60|120|180:0.4|0.3|0.2"),
    "estadio": ("Estádio", "Espaço", "aecho=0.8:0.9:90|200|330:0.35|0.25|0.15,highpass=f=120"),
    "tremolo": ("Tremolo", "Espaço", "tremolo=f=6:d=0.6"),
    "flanger": ("Flanger", "Espaço", "flanger=delay=2:depth=4:speed=0.4"),
    "coral": ("Coral", "Espaço", "chorus=0.5:0.9:50|60:0.4|0.32:0.25|0.4:2|1.3"),
    "oito_bits": ("8 bits", "Textura", "acrusher=bits=6:samples=8:mode=lin:mix=1"),
    "fita": ("Fita cassete", "Textura", "highpass=f=90,lowpass=f=7500,flanger=delay=1:depth=1:speed=0.3,acompressor=threshold=0.2:ratio=2"),
    "vinil": ("Disco de vinil", "Textura", "highpass=f=120,lowpass=f=6000,equalizer=f=1200:t=q:w=1:g=2"),
}


def cadeia(efeito: str | None) -> str:
    if not efeito or efeito not in EFEITOS:
        return ""
    return f"aresample={TAXA}," + EFEITOS[efeito][2]


def lista() -> list[dict]:
    return [{"id": k, "nome": v[0], "grupo": v[1]} for k, v in EFEITOS.items()]


# ------------------------------------------------------------ música que abaixa quando alguém fala

JANELA = 960  # 20 ms


def ganho_ducking(fala: np.ndarray, forca: float = .65, limiar_db: float = -42.0) -> np.ndarray:
    """Ganho por janela de 20 ms para a música: desce rápido quando há voz e volta devagar."""
    n = len(fala) // JANELA
    if n == 0:
        return np.ones(1, np.float32)
    nivel = np.empty(n, np.float32)
    bloco = 3000  # janelas por vez, para não carregar horas de áudio na memória
    for i in range(0, n, bloco):
        j = min(n, i + bloco)
        parte = np.asarray(fala[i * JANELA:j * JANELA], np.float32).reshape(j - i, JANELA, -1)
        nivel[i:j] = 10 * np.log10(np.mean(parte ** 2, axis=(1, 2)) + 1e-10)
    alvo = np.clip((nivel - limiar_db) / 12, 0, 1)
    ataque, soltura = 1 - np.exp(-1 / 3.0), 1 - np.exp(-1 / 22.0)  # ~60 ms para descer, ~450 ms para voltar
    env = np.empty(n, np.float32)
    atual = 0.0
    for k in range(n):
        a = alvo[k]
        atual += (a - atual) * (ataque if a > atual else soltura)
        env[k] = atual
    return (1 - max(0.0, min(.95, forca)) * env).astype(np.float32)


def aplicar_ganho(musica, ganho: np.ndarray, destino) -> None:
    """Soma a música com o ganho (interpolado por amostra) dentro de `destino`."""
    total = len(musica)
    centros = (np.arange(len(ganho), dtype=np.float64) + .5) * JANELA
    passo = TAXA * 20
    for i in range(0, total, passo):
        j = min(total, i + passo)
        g = np.interp(np.arange(i, j, dtype=np.float64), centros, ganho).astype(np.float32)
        destino[i:j] += np.asarray(musica[i:j], np.float32) * g[:, None]


# ------------------------------------------------------------ batidas da música

def batidas(pcm: np.ndarray, taxa: int = 16000) -> tuple[list[float], float]:
    """Encontra o andamento e as batidas: fluxo espectral, autocorrelação e grade com a melhor fase."""
    x = pcm.astype(np.float32) / 32768
    janela, salto = 1024, 256
    if len(x) < janela * 8:
        return [], 0.0
    quadros = 1 + (len(x) - janela) // salto
    idx = np.arange(janela)[None, :] + salto * np.arange(quadros)[:, None]
    esp = np.abs(np.fft.rfft(x[idx] * np.hanning(janela)[None, :], axis=1))
    esp = np.log1p(esp * 10)
    fluxo = np.maximum(0, np.diff(esp, axis=0)).sum(axis=1)
    fluxo = np.concatenate([[0], fluxo])
    fluxo -= np.convolve(fluxo, np.ones(16) / 16, "same")
    fluxo = np.maximum(fluxo, 0)
    if fluxo.max() <= 0:
        return [], 0.0
    fluxo /= fluxo.max()
    fps = taxa / salto
    menor, maior = int(fps * 60 / 180), int(fps * 60 / 70)
    ac = np.correlate(fluxo, fluxo, "full")[len(fluxo) - 1:]
    if maior >= len(ac):
        return [], 0.0
    lags = np.arange(menor, maior + 1)
    peso = np.exp(-0.5 * (np.log2(60 * fps / lags / 120) / 0.9) ** 2)  # prefere andamentos perto de 120 BPM
    periodo = int(lags[np.argmax(ac[menor:maior + 1] * peso)])
    fases = [fluxo[f::periodo].sum() for f in range(periodo)]
    fase = int(np.argmax(fases))
    tempos = []
    k = fase
    while k < len(fluxo):  # ajusta cada batida ao pico mais próximo, sem fugir da grade
        a, b = max(0, k - 3), min(len(fluxo), k + 4)
        pico = a + int(np.argmax(fluxo[a:b]))
        tempos.append(round((pico * salto + janela / 2) / taxa, 3))  # centro da janela que viu o ataque
        k += periodo
    return tempos, round(60 * fps / periodo, 1)
