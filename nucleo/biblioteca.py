"""Biblioteca de efeitos sonoros: sons criados pelo próprio sistema e sons enviados pelo usuário."""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import unicodedata
import wave
from pathlib import Path

import numpy as np

from .plataformas import sem_janela

SR = 48000
LIMITE_ENVIO = 120 * 1024 * 1024
DURACAO_MAXIMA_ENVIO = 1200


# ------------------------------------------------------------ peças básicas de síntese

def _t(d: float) -> np.ndarray:
    return np.arange(int(SR * d)) / SR


def _ruido(d: float, semente: int = 1) -> np.ndarray:
    return np.random.default_rng(semente).normal(0, 0.35, int(SR * d))


def _banda(x: np.ndarray, baixo: float, alto: float) -> np.ndarray:
    espectro = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    espectro *= np.clip((f - baixo * 0.7) / (baixo * 0.3 + 1), 0, 1) * np.clip((alto * 1.3 - f) / (alto * 0.3 + 1), 0, 1)
    return np.fft.irfft(espectro, len(x))


def _varrer(x: np.ndarray, corte: np.ndarray) -> np.ndarray:
    """Passa-baixa com abertura que muda ao longo do som."""
    a = 1 - np.exp(-2 * np.pi * np.clip(corte, 20, SR * 0.45) / SR)
    saida = np.empty(len(x))
    y = 0.0
    for i in range(len(x)):
        y += float(a[i]) * (float(x[i]) - y)
        saida[i] = y
    return saida


def _queda(d: float, velocidade: float) -> np.ndarray:
    return np.exp(-_t(d) * velocidade)


def _forma(n: int, ataque: float = 0.005, soltura: float = 0.03) -> np.ndarray:
    e = np.ones(n)
    a, s = min(n, int(SR * ataque)), min(n, int(SR * soltura))
    if a:
        e[:a] = np.linspace(0, 1, a)
    if s:
        e[-s:] *= np.linspace(1, 0, s)
    return e


def _fase(f: np.ndarray) -> np.ndarray:
    return 2 * np.pi * np.cumsum(f) / SR


def _nota(f: float | np.ndarray, d: float, tipo: str = "sen", ataque: float = 0.004, soltura: float = 0.04) -> np.ndarray:
    n = int(SR * d)
    freq = np.full(n, f, dtype=float) if np.isscalar(f) else np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(f)), f)
    fase = _fase(freq)
    if tipo == "qua":
        onda = np.sign(np.sin(fase)) * 0.6
    elif tipo == "ser":
        onda = 2 * ((fase / (2 * np.pi)) % 1) - 1
    elif tipo == "tri":
        onda = 2 * np.abs(2 * ((fase / (2 * np.pi)) % 1) - 1) - 1
    else:
        onda = np.sin(fase)
    return onda * _forma(n, ataque, soltura)


def _sino(f: float, d: float, brilho: float = 0.5, velocidade: float = 5.0) -> np.ndarray:
    t = _t(d)
    onda = np.sin(2 * np.pi * f * t) + brilho * np.sin(2 * np.pi * f * 2.01 * t) * np.exp(-t * 4) + brilho * 0.4 * np.sin(2 * np.pi * f * 3.02 * t) * np.exp(-t * 8)
    return onda * np.exp(-t * velocidade) * _forma(len(t), 0.002, 0.02)


def _mix(*partes: tuple) -> np.ndarray:
    """Cada parte é (instante, som) ou (instante, som, ganho)."""
    fim = max(int(p[0] * SR) + len(p[1]) for p in partes)
    saida = np.zeros(fim)
    for p in partes:
        ini = int(p[0] * SR)
        saida[ini:ini + len(p[1])] += p[1] * (p[2] if len(p) > 2 else 1.0)
    return saida


def _eco(x: np.ndarray, duracao: float = 0.5, quantidade: float = 0.25, semente: int = 3) -> np.ndarray:
    resposta = _ruido(duracao, semente) * np.exp(-_t(duracao) * 7 / duracao)
    tamanho = len(x) + len(resposta)
    molhado = np.fft.irfft(np.fft.rfft(x, tamanho) * np.fft.rfft(resposta, tamanho), tamanho)
    molhado = molhado / (np.abs(molhado).max() + 1e-9) * np.abs(x).max()
    return np.concatenate([x, np.zeros(len(resposta))]) * (1 - quantidade) + molhado * quantidade


def _whoosh(d: float, baixo: float, alto: float, semente: int = 1) -> np.ndarray:
    n = int(SR * d)
    pico = np.sin(np.linspace(0, np.pi, n)) ** 2
    return _varrer(_ruido(d, semente), baixo + (alto - baixo) * pico) * pico * 3


def _estalo(d: float = 0.03, baixo: float = 1200, alto: float = 9000, semente: int = 5) -> np.ndarray:
    return _banda(_ruido(d, semente), baixo, alto) * _queda(d, 3 / d)


def _soco(f: float = 90, d: float = 0.3) -> np.ndarray:
    t = _t(d)
    return np.sin(_fase(f * 0.55 + f * 1.8 * np.exp(-t * 28))) * np.exp(-t * 14)


def _bumbo(d: float = 0.25) -> np.ndarray:
    return _soco(62, d)


def _caixa(d: float = 0.18, semente: int = 7) -> np.ndarray:
    t = _t(d)
    return (_banda(_ruido(d, semente), 900, 8000) * 2 + np.sin(2 * np.pi * 190 * t) * 0.7) * np.exp(-t * 22)


def _prato(d: float = 0.9, semente: int = 9) -> np.ndarray:
    return _banda(_ruido(d, semente), 3500, 15000) * 2 * _queda(d, 5)


def _acorde(notas: list[float], d: float, tipo: str = "ser") -> np.ndarray:
    return sum(_nota(f, d, tipo, 0.01, d * 0.35) for f in notas) / len(notas)


def _seq(notas: list[float], passo: float, d: float, tipo: str = "qua") -> np.ndarray:
    return _mix(*[(i * passo, _nota(f, d, tipo, 0.002, 0.02)) for i, f in enumerate(notas) if f])


# ------------------------------------------------------------ transições

def whoosh_rapido(): return _whoosh(0.32, 500, 6500)
def whoosh_longo(): return _whoosh(1.1, 250, 4800, 2)
def swipe(): return _whoosh(0.2, 1500, 11000, 3)
def zoom_in(): return _mix((0, _whoosh(0.5, 300, 7000, 4)), (0, _nota(np.geomspace(140, 950, 40), 0.5, "tri", 0.02, 0.1), 0.3))
def zoom_out(): return _mix((0, _whoosh(0.5, 300, 5000, 5)), (0, _nota(np.geomspace(950, 110, 40), 0.5, "tri", 0.02, 0.1), 0.3))


def riser(d: float, semente: int = 6) -> np.ndarray:
    n = int(SR * d)
    subida = np.linspace(0, 1, n) ** 2.2
    ruido = _varrer(_ruido(d, semente), 200 + 9000 * subida) * subida * 2.5
    tom = _nota(np.geomspace(90, 780, 60), d, "ser", 0.05, 0.02) * subida * 0.35
    return ruido + tom


def riser_curto(): return riser(1.4)
def riser_longo(): return riser(3.2, 8)
def reverso(): return _prato(1.6, 12)[::-1] * 1.4


def glitch():
    rng = np.random.default_rng(14)
    partes = []
    t = 0.0
    while t < 0.55:
        d = float(rng.uniform(0.018, 0.06))
        partes.append((t, _nota(float(rng.uniform(180, 3200)), d, "qua", 0.001, 0.003)))
        t += d
    return _mix(*partes)


def fita_voltando():
    d = 0.9
    rng = np.random.default_rng(16)
    f = np.abs(np.cumsum(rng.normal(0, 1, 90))) * 22 + 260
    return _nota(f, d, "ser", 0.01, 0.1) * 0.7 + _banda(_ruido(d, 17), 1800, 7000) * 0.5


def transicao_digital():
    return _mix((0, _seq([1760, 1320, 1975, 2637], 0.05, 0.05, "qua"), 0.6), (0.05, _whoosh(0.34, 800, 8000, 18), 0.6))


def vento(): return _whoosh(2.0, 180, 1600, 19)


# ------------------------------------------------------------ impactos

def boom_grave():
    t = _t(1.3)
    return _mix((0, np.sin(_fase(38 + 100 * np.exp(-t * 11))) * np.exp(-t * 3.6)), (0, _estalo(0.05, 300, 5000), 0.8))


def impacto_cinema():
    t = _t(2.2)
    grave = np.sin(_fase(34 + 120 * np.exp(-t * 13))) * np.exp(-t * 2.4)
    corpo = _banda(_ruido(2.2, 21), 180, 2200) * np.exp(-t * 8) * 1.7
    return _eco(grave + corpo, 0.5, 0.2)[:int(SR * 2.4)]


def soco(): return _mix((0, _soco(110, 0.22)), (0, _estalo(0.04, 800, 6000, 22), 0.8))
def tapa(): return _banda(_ruido(0.14, 23), 1200, 9000) * _queda(0.14, 45) * 2.2
def pancada_metal():
    t = _t(1.1)
    onda = sum(np.sin(2 * np.pi * f * t) * np.exp(-t * v) for f, v in ((410, 6), (1033, 9), (1812, 13), (2970, 20)))
    return _mix((0, onda / 3), (0, _estalo(0.05, 500, 8000, 24)))


def queda_corpo(): return _mix((0, _soco(70, 0.34)), (0.13, _soco(58, 0.28), 0.55), (0, _banda(_ruido(0.2, 25), 200, 1800) * _queda(0.2, 22), 0.6))


def vidro_quebrando():
    rng = np.random.default_rng(26)
    partes = [(0, _banda(_ruido(0.35, 27), 1800, 14000) * _queda(0.35, 13) * 2)]
    for _ in range(26):
        partes.append((float(rng.uniform(0.02, 1.0)), _sino(float(rng.uniform(2600, 8800)), 0.22, 0.2, 26), float(rng.uniform(0.12, 0.42))))
    return _mix(*partes)


def explosao(d: float = 2.4, semente: int = 28) -> np.ndarray:
    t = _t(d)
    corpo = _varrer(_ruido(d, semente), 120 + 5000 * np.exp(-t * 5)) * np.exp(-t * 2.3) * 4
    return corpo + np.sin(_fase(32 + 90 * np.exp(-t * 9))) * np.exp(-t * 2.4)


def explosao_distante(): return _banda(explosao(2.8, 29), 20, 480) * 2.4
def trovao():
    t = _t(3.4)
    rng = np.random.default_rng(30)
    ronco = 0.5 + 0.5 * np.interp(t, np.linspace(0, 3.4, 26), rng.uniform(0, 1, 26))
    return _varrer(_ruido(3.4, 31), 160 + 1300 * np.exp(-t * 2.6)) * ronco * np.exp(-t * 1.0) * 5


def porta_batendo(): return _mix((0, _soco(82, 0.42)), (0, _banda(_ruido(0.12, 32), 300, 3000) * _queda(0.12, 30)), (0.1, _estalo(0.04, 700, 3000, 33), 0.5))
def terremoto():
    t = _t(3)
    return _banda(_ruido(3, 34), 20, 130) * 5 * np.sin(np.pi * t / 3) ** 0.7 * (0.7 + 0.3 * np.sin(2 * np.pi * 7 * t))


def bass_drop():
    t = _t(2)
    return _mix((0, np.sin(_fase(np.geomspace(190, 34, len(t)))) * np.minimum(1, (2 - t) * 2)), (0, _bumbo(0.5), 0.8))


def sub_drop():
    t = _t(1.4)
    return np.sin(_fase(np.geomspace(110, 28, len(t)))) * np.exp(-t * 1.5)


# ------------------------------------------------------------ comédia

def boing():
    t = _t(0.75)
    f = 170 * (1 + 0.38 * np.sin(2 * np.pi * 15 * t) * np.exp(-t * 3.5)) * (1 + t * 1.3)
    return np.sin(_fase(f)) * np.exp(-t * 4.4)


def mola():
    t = _t(1.0)
    return np.sin(_fase(300 + 230 * np.sin(2 * np.pi * 9 * t) * np.exp(-t * 2))) * np.exp(-t * 3.2)


def _apito(f0: float, f1: float, d: float = 0.8) -> np.ndarray:
    t = _t(d)
    f = np.geomspace(f0, f1, len(t)) * (1 + 0.012 * np.sin(2 * np.pi * 6 * t))
    return (np.sin(_fase(f)) + 0.15 * np.sin(_fase(2 * f))) * _forma(len(t), 0.04, 0.08)


def apito_descendo(): return _apito(1700, 340)
def apito_subindo(): return _apito(340, 1700)
def buzina_palhaco(): return _mix((0, _acorde([360, 366, 720], 0.2, "ser")), (0.27, _acorde([300, 305, 600], 0.34, "ser")))
def ba_dum_tss(): return _mix((0, _caixa(0.14)), (0.17, _bumbo(0.22)), (0.34, _caixa(0.12), 0.9), (0.42, _prato(1.0), 0.75))
def trombone_triste():
    notas = [(311, 0.34), (294, 0.34), (277, 0.34), (262, 1.05)]
    partes, t = [], 0.0
    for f, d in notas:
        vib = f * (1 + 0.016 * np.sin(2 * np.pi * 5.5 * _t(d))) if d > 0.5 else f
        partes.append((t, _nota(vib, d, "ser", 0.03, 0.09)))
        t += d
    som = _mix(*partes)
    return _varrer(som, np.full(len(som), 1500.0))


def plop(): return np.sin(_fase(np.geomspace(320, 880, int(SR * 0.09)))) * _forma(int(SR * 0.09), 0.004, 0.05)
def splat(): return _mix((0, _soco(115, 0.17)), (0, _banda(_ruido(0.26, 36), 250, 3000) * _queda(0.26, 16), 1.1))
def pato():
    def q(d):
        t = _t(d)
        f = 620 * (1 - 0.18 * t / d)
        return _banda(np.sign(np.sin(_fase(f))) * 0.7, 700, 2600) * np.sin(np.pi * t / d) ** 0.6
    return _mix((0, q(0.17)), (0.24, q(0.21)))


def fracasso(): return _seq([523, 494, 466, 311], 0.21, 0.32, "ser")
def queda_desenho(): return _mix((0, _apito(1800, 240, 1.1)), (1.1, _soco(62, 0.45), 1.5), (1.12, _estalo(0.06, 500, 3000, 37), 0.7))
def grilos():
    partes = []
    for bloco in range(5):
        for i in range(3):
            partes.append((bloco * 0.56 + i * 0.066, _nota(4400, 0.045, "sen", 0.004, 0.012)))
    return _mix(*partes)


# ------------------------------------------------------------ interface

def pop(): return np.sin(_fase(np.geomspace(1300, 300, int(SR * 0.075)))) * _forma(int(SR * 0.075), 0.002, 0.04)
def clique(): return _mix((0, _estalo(0.012, 1600, 9000, 38)), (0.03, _estalo(0.01, 2200, 9000, 39), 0.6))
def ding(): return _sino(1568, 1.1, 0.5, 4)
def ding_duplo(): return _mix((0, _sino(1319, 0.5, 0.5, 6)), (0.17, _sino(1760, 0.9, 0.5, 5)))
def notificacao(): return _mix((0, _sino(880, 0.4, 0.3, 8)), (0.12, _sino(1319, 0.6, 0.3, 7)))
def moeda(): return _mix((0, _nota(988, 0.08, "qua", 0.001, 0.01)), (0.08, _nota(1319, 0.42, "qua", 0.001, 0.2)))
def sucesso(): return _mix((0, _sino(659, 0.4, 0.3, 6)), (0.11, _sino(784, 0.4, 0.3, 6)), (0.22, _sino(1047, 0.9, 0.4, 4)))
def erro(): return _mix((0, _nota(196, 0.17, "qua", 0.002, 0.03)), (0.2, _nota(147, 0.34, "qua", 0.002, 0.06)))
def level_up(): return _seq([523, 659, 784, 1047, 1319, 1568], 0.075, 0.13, "qua")
def power_up(): return _nota(np.geomspace(190, 1700, 40) * (1 + 0.14 * np.sin(np.linspace(0, 60, 40))), 0.72, "qua", 0.004, 0.08)
def game_over(): return _seq([494, 466, 440, 415, 392, 370, 349, 262], 0.17, 0.2, "qua")
def caixa_registradora(): return _mix((0, _estalo(0.03, 900, 5000, 40)), (0.06, _sino(2093, 0.5, 0.5, 8)), (0.08, _sino(2637, 0.9, 0.5, 5)), (0.32, _soco(130, 0.1), 0.45))
def camera_foto(): return _mix((0, _estalo(0.03, 1200, 7000, 41), 1.2), (0.11, _estalo(0.045, 700, 5000, 42)))
def digitacao():
    rng = np.random.default_rng(43)
    return _mix(*[(i * 0.092 + float(rng.uniform(0, 0.03)), _estalo(0.018, 1400, 7000, 44 + i), float(rng.uniform(0.6, 1))) for i in range(14)])


def bolha(): return _mix(*[(i * 0.075, np.sin(_fase(np.geomspace(420 + 90 * i, 900 + 150 * i, int(SR * 0.06)))) * _forma(int(SR * 0.06), 0.004, 0.03)) for i in range(4)])


# ------------------------------------------------------------ tensão

def coracao(): return _mix(*[(i * 0.92 + d, _soco(58, 0.24), g) for i in range(3) for d, g in ((0, 1.0), (0.22, 0.7))])
def drone_suspense():
    t = _t(4)
    return (np.sin(2 * np.pi * 55 * t) + 0.7 * np.sin(2 * np.pi * 58.3 * t) + 0.35 * np.sin(2 * np.pi * 110.7 * t)) * np.sin(np.pi * t / 4) ** 1.3


def sirene_policia():
    t = _t(3.2)
    return np.sign(np.sin(_fase(980 + 480 * np.sin(2 * np.pi * 0.95 * t)))) * 0.45 * _forma(len(t), 0.1, 0.25)


def alarme(): return _mix(*[(i * 0.48, _nota(np.array([740, 1110]), 0.36, "qua", 0.004, 0.02)) for i in range(5)])
def relogio(): return _mix(*[(i * 0.5, _estalo(0.022, 1800 if i % 2 else 1200, 7000, 60 + i)) for i in range(6)])
def stinger(): return _mix((0, _acorde([110, 116.5, 164.8, 233, 311], 1.6, "ser")), (0, _soco(50, 0.7), 0.9))
def cordas_tensas():
    t = _t(3)
    f = np.geomspace(330, 660, len(t))
    return sum(np.sin(_fase(f * r * (1 + 0.006 * np.sin(2 * np.pi * 9.5 * t)))) for r in (1, 1.06, 1.5)) / 3 * (t / 3) ** 1.1 * _forma(len(t), 0.1, 0.08)


def contagem(): return _mix(*[(i, _nota(880, 0.14, "sen", 0.002, 0.03)) for i in range(3)], (3, _nota(1760, 0.65, "sen", 0.002, 0.12)))
def radar(): return _mix(*[(i * 0.8, _sino(1650, 0.65, 0.1, 7)) for i in range(3)])


# ------------------------------------------------------------ jogo e ação

def tiro_pistola(semente: int = 70):
    t = _t(0.62)
    return _eco(_banda(_ruido(0.62, semente), 180, 8000) * np.exp(-t * 19) * 4 + np.sin(_fase(70 + 170 * np.exp(-t * 40))) * np.exp(-t * 15), 0.3, 0.15)


def rajada(): return _mix(*[(i * 0.085, tiro_pistola(71 + i)[:int(SR * 0.3)], 0.82) for i in range(10)])
def recarga(): return _mix((0, _estalo(0.03, 900, 5000, 80), 1.1), (0.16, _estalo(0.04, 600, 3800, 81)), (0.44, _soco(180, 0.06), 0.5), (0.52, _estalo(0.05, 1200, 5000, 82), 1.2))
def laser(): return _nota(np.geomspace(2600, 240, 40), 0.3, "qua", 0.002, 0.06)
def laser_duplo(): return _mix((0, laser()), (0.17, laser(), 0.7))
def pulo_8bit(): return _nota(np.geomspace(230, 880, 30), 0.19, "qua", 0.002, 0.03)
def item_8bit(): return _seq([988, 1319, 1568, 2093], 0.055, 0.1, "qua")
def explosao_8bit():
    rng = np.random.default_rng(83)
    amostra = np.repeat(rng.choice([-1.0, 1.0], int(SR * 0.9 / 90)), 90)
    return amostra * _queda(len(amostra) / SR, 4.5)


def motor_acelerando():
    t = _t(2.4)
    f = 52 + 165 * (t / 2.4) ** 1.5
    return _varrer(np.sign(np.sin(_fase(f))) * 0.55 + np.sign(np.sin(_fase(f * 1.5))) * 0.25, 500 + f * 16) * 1.9 * _forma(len(t), 0.1, 0.25)


def pneu_cantando():
    t = _t(1.6)
    return _banda(np.sin(_fase(1250 + 150 * np.sin(2 * np.pi * 21 * t))) + _ruido(1.6, 84), 700, 3800) * _forma(len(t), 0.05, 0.4)


def buzina_carro(): return _mix((0, _acorde([392, 494], 0.32, "ser")), (0.42, _acorde([392, 494], 0.6, "ser")))
def freada(): return _mix((0, _banda(np.sin(_fase(np.geomspace(2200, 1250, int(SR * 1.1)))) + _ruido(1.1, 85), 700, 4200) * _forma(int(SR * 1.1), 0.02, 0.2)), (1.1, _soco(90, 0.3), 0.8))
def espada(): return _mix((0, _whoosh(0.25, 900, 8000, 86), 1.0), (0.2, _sino(3300, 0.75, 0.7, 7), 0.8), (0.2, _sino(4170, 0.5, 0.6, 9), 0.5))
def passos(): return _mix(*[(i * 0.42, _soco(92, 0.11)) for i in range(5)])


# ------------------------------------------------------------ festa e música

def buzina_festa(): return _mix(*[(i * 0.24, _acorde([233, 311, 466, 622], 0.2 if i < 3 else 0.8, "ser")) for i in range(4)])
def fanfarra():
    return _mix((0, _acorde([523, 659, 784], 0.18, "ser")), (0.2, _acorde([523, 659, 784], 0.18, "ser")), (0.4, _acorde([523, 659, 784], 0.18, "ser")), (0.6, _acorde([659, 784, 1047], 1.1, "ser")), (0.6, _prato(1.2), 0.3))


def rufar():
    n = 36
    return _mix(*[(i * 0.058, _caixa(0.1, 90 + i), 0.45 + 0.55 * i / n) for i in range(n)], (n * 0.058, _prato(1.2), 1.0), (n * 0.058, _bumbo(0.3), 1.0))


def aplausos():
    rng = np.random.default_rng(127)
    d = 3.2
    partes = [(float(rng.uniform(0, d - 0.2)), _banda(_ruido(0.04, 130 + i % 12), 800, 7000) * _queda(0.04, 90), float(rng.uniform(0.25, 0.8))) for i in range(420)]
    som = _mix(*partes)
    return som * _forma(len(som), 0.3, 0.8)


def acorde_surpresa(): return _mix((0, _acorde([196, 233, 311, 392], 1.4, "ser")), (0, _soco(70, 0.5)))
def vitoria(): return _seq([523, 523, 523, 659, 784, 659, 784, 1047], 0.13, 0.22, "ser")
def brilho():
    rng = np.random.default_rng(145)
    return _mix(*[(i * 0.055, _sino(float(rng.choice([1760, 2093, 2349, 2637, 3136, 3520])), 0.45, 0.3, 9), 0.7) for i in range(16)])


def harpa(): return _mix(*[(i * 0.06, _sino(f, 1.0, 0.3, 4), 0.72) for i, f in enumerate([262, 330, 392, 523, 659, 784, 1047, 1319])])
def confete(): return _mix((0, pop(), 1.2), (0.05, brilho(), 0.7))


C = [
    ("whoosh_rapido", "Whoosh rápido", "Transições", "passar corte troca cena vento", whoosh_rapido),
    ("whoosh_longo", "Whoosh longo", "Transições", "passar vento cena lento", whoosh_longo),
    ("swipe", "Deslizar", "Transições", "swipe arrastar passar rapido", swipe),
    ("zoom_in", "Zoom aproximando", "Transições", "aproximar entrada foco", zoom_in),
    ("zoom_out", "Zoom afastando", "Transições", "afastar saida", zoom_out),
    ("riser_curto", "Subida curta", "Transições", "riser tensao antes do impacto preparar", riser_curto),
    ("riser_longo", "Subida longa", "Transições", "riser tensao clima crescendo", riser_longo),
    ("reverso", "Prato invertido", "Transições", "reverse reverso entrada", reverso),
    ("glitch", "Glitch digital", "Transições", "falha erro computador interferencia bug", glitch),
    ("fita_voltando", "Fita voltando", "Transições", "rebobinar rewind voltar tempo", fita_voltando),
    ("transicao_digital", "Transição digital", "Transições", "tecnologia futurista computador", transicao_digital),
    ("vento", "Vento passando", "Transições", "ar clima ambiente", vento),
    ("boom_grave", "Boom grave", "Impactos", "bum pancada grave forte cena", boom_grave),
    ("impacto_cinema", "Impacto de cinema", "Impactos", "trailer filme choque surpresa forte", impacto_cinema),
    ("soco", "Soco", "Impactos", "luta bater murro porrada", soco),
    ("tapa", "Tapa", "Impactos", "bofetada estalo bater", tapa),
    ("pancada_metal", "Pancada no metal", "Impactos", "batida carro ferro bater colisao", pancada_metal),
    ("queda_corpo", "Queda no chão", "Impactos", "caiu cair tombo", queda_corpo),
    ("vidro_quebrando", "Vidro quebrando", "Impactos", "janela quebrou estilhaço", vidro_quebrando),
    ("explosao", "Explosão", "Impactos", "bomba granada explodir fogo", explosao),
    ("explosao_distante", "Explosão distante", "Impactos", "bomba longe guerra", explosao_distante),
    ("trovao", "Trovão", "Impactos", "chuva tempestade raio", trovao),
    ("porta_batendo", "Porta batendo", "Impactos", "fechar casa", porta_batendo),
    ("terremoto", "Terremoto", "Impactos", "tremor chao rumble", terremoto),
    ("bass_drop", "Bass drop", "Impactos", "grave musica batida queda", bass_drop),
    ("sub_drop", "Queda grave", "Impactos", "sub grave profundo", sub_drop),
    ("boing", "Boing", "Comédia", "mola pulo engraçado desenho", boing),
    ("mola", "Mola vibrando", "Comédia", "engraçado balançar", mola),
    ("apito_descendo", "Apito descendo", "Comédia", "cair desenho engraçado queda", apito_descendo),
    ("apito_subindo", "Apito subindo", "Comédia", "subir desenho engraçado", apito_subindo),
    ("buzina_palhaco", "Buzina de palhaço", "Comédia", "circo engraçado bobo", buzina_palhaco),
    ("ba_dum_tss", "Ba dum tss", "Comédia", "piada bateria rimshot risada", ba_dum_tss),
    ("trombone_triste", "Trombone triste", "Comédia", "falhou perdeu sad fail", trombone_triste),
    ("plop", "Plop", "Comédia", "gota aparecer engraçado", plop),
    ("splat", "Splat", "Comédia", "esmagar lama cair", splat),
    ("pato", "Pato", "Comédia", "quack engraçado meme", pato),
    ("fracasso", "Vinheta de fracasso", "Comédia", "fail errou perdeu", fracasso),
    ("queda_desenho", "Queda de desenho", "Comédia", "cair tombo apito engraçado", queda_desenho),
    ("grilos", "Grilos", "Comédia", "silencio constrangedor vergonha ninguem riu", grilos),
    ("pop", "Pop", "Interface", "aparecer texto bolha", pop),
    ("clique", "Clique", "Interface", "mouse botao apertar", clique),
    ("ding", "Ding", "Interface", "sino ideia acerto", ding),
    ("ding_duplo", "Ding duplo", "Interface", "sino campainha", ding_duplo),
    ("notificacao", "Notificação", "Interface", "celular mensagem alerta", notificacao),
    ("moeda", "Moeda", "Interface", "dinheiro coin jogo ganhar", moeda),
    ("sucesso", "Sucesso", "Interface", "acertou conseguiu ganhou", sucesso),
    ("erro", "Erro", "Interface", "errou falha negado", erro),
    ("level_up", "Level up", "Interface", "subiu nivel jogo conquista", level_up),
    ("power_up", "Power up", "Interface", "poder jogo energia", power_up),
    ("game_over", "Game over", "Interface", "morreu perdeu fim jogo", game_over),
    ("caixa_registradora", "Caixa registradora", "Interface", "dinheiro grana comprou pagar", caixa_registradora),
    ("camera_foto", "Foto", "Interface", "camera tirar print captura", camera_foto),
    ("digitacao", "Digitação", "Interface", "teclado escrever digitar", digitacao),
    ("bolha", "Bolhas", "Interface", "agua borbulhar", bolha),
    ("coracao", "Batida do coração", "Tensão", "medo nervoso suspense", coracao),
    ("drone_suspense", "Clima de suspense", "Tensão", "drone misterio terror grave", drone_suspense),
    ("sirene_policia", "Sirene de polícia", "Tensão", "viatura perseguição policia", sirene_policia),
    ("alarme", "Alarme", "Tensão", "perigo aviso alerta", alarme),
    ("relogio", "Relógio", "Tensão", "tic tac tempo espera", relogio),
    ("stinger", "Susto", "Tensão", "terror jumpscare medo acorde", stinger),
    ("cordas_tensas", "Cordas tensas", "Tensão", "violino suspense crescendo", cordas_tensas),
    ("contagem", "Contagem regressiva", "Tensão", "tempo largada bip", contagem),
    ("radar", "Radar", "Tensão", "sonar submarino bip", radar),
    ("tiro_pistola", "Tiro de pistola", "Jogo e ação", "arma atirar disparo bala", tiro_pistola),
    ("rajada", "Rajada", "Jogo e ação", "metralhadora arma tiros fuzil", rajada),
    ("recarga", "Recarregar arma", "Jogo e ação", "pente municao reload", recarga),
    ("laser", "Laser", "Jogo e ação", "tiro espaço futurista", laser),
    ("laser_duplo", "Laser duplo", "Jogo e ação", "tiro espaço futurista", laser_duplo),
    ("pulo_8bit", "Pulo 8 bits", "Jogo e ação", "retro arcade pular", pulo_8bit),
    ("item_8bit", "Item 8 bits", "Jogo e ação", "retro arcade pegar coletar", item_8bit),
    ("explosao_8bit", "Explosão 8 bits", "Jogo e ação", "retro arcade bomba", explosao_8bit),
    ("motor_acelerando", "Motor acelerando", "Jogo e ação", "carro corrida moto acelerar", motor_acelerando),
    ("pneu_cantando", "Pneu cantando", "Jogo e ação", "carro drift curva derrapar", pneu_cantando),
    ("buzina_carro", "Buzina de carro", "Jogo e ação", "transito buzinar", buzina_carro),
    ("freada", "Freada e batida", "Jogo e ação", "carro acidente frear colisao", freada),
    ("espada", "Espada", "Jogo e ação", "lamina corte luta", espada),
    ("passos", "Passos", "Jogo e ação", "andar caminhar pegada", passos),
    ("buzina_festa", "Buzina de festa", "Festa", "air horn hype comemorar mlg", buzina_festa),
    ("fanfarra", "Fanfarra", "Festa", "vitoria trompete campeao", fanfarra),
    ("rufar", "Rufar de tambores", "Festa", "bateria suspense revelar", rufar),
    ("aplausos", "Aplausos", "Festa", "palmas plateia parabens", aplausos),
    ("acorde_surpresa", "Acorde de surpresa", "Festa", "revelação choque musica", acorde_surpresa),
    ("vitoria", "Vitória", "Festa", "ganhou jogo campeao musica", vitoria),
    ("brilho", "Brilho mágico", "Festa", "magia sparkle estrela lindo", brilho),
    ("harpa", "Harpa mágica", "Festa", "sonho lindo admirar glissando", harpa),
    ("confete", "Confete", "Festa", "comemorar festa parabens", confete),
]
from .musicas import catalogo as _musicas  # noqa: E402
C += _musicas()
CATALOGO = {c[0]: {"id": c[0], "nome": c[1], "categoria": c[2], "tags": c[3], "gerar": c[4]} for c in C}
CATEGORIAS = list(dict.fromkeys(c[2] for c in C))


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.casefold()) if unicodedata.category(c) != "Mn")


def gerar_audio(som_id: str) -> np.ndarray:
    """Devolve o som em estéreo, com volume igualado e sem estalo no final."""
    x = np.asarray(CATALOGO[som_id]["gerar"](), dtype=np.float64)
    x = x - float(np.mean(x))
    # Ondas quadradas soam muito mais altas: o volume é igualado pela energia, não só pelo pico.
    x = x * min(0.89 / (float(np.abs(x).max()) + 1e-9), 0.3 / (float(np.sqrt(np.mean(x ** 2))) + 1e-9))
    fim = min(len(x), int(SR * 0.012))
    x[-fim:] *= np.linspace(1, 0, fim)
    return np.stack([x, x], axis=1)


def ler_wav(arquivo: Path) -> np.ndarray:
    with wave.open(str(arquivo), "rb") as w:
        dados = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    return dados.reshape(-1, 2)


def gravar_wav(arquivo: Path, dados: np.ndarray) -> None:
    pcm = (np.clip(dados, -1, 1) * 32767).astype(np.int16)
    temporario = arquivo.with_suffix(".tmp")
    with wave.open(str(temporario), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    temporario.replace(arquivo)


class Biblioteca:
    def __init__(self, dados: Path):
        self.pasta = Path(dados) / "sons"
        self.meus = self.pasta / "meus"
        self.meus.mkdir(parents=True, exist_ok=True)
        self.indice = self.meus / "lista.json"
        self.trava = threading.RLock()
        try:
            self.enviados: dict[str, dict] = json.loads(self.indice.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.enviados = {}

    def _salvar(self) -> None:
        temporario = self.indice.with_suffix(".tmp")
        temporario.write_text(json.dumps(self.enviados, ensure_ascii=False), encoding="utf-8")
        temporario.replace(self.indice)

    def existe(self, som_id: str) -> bool:
        return som_id in CATALOGO or som_id in self.enviados

    def nome(self, som_id: str) -> str:
        return (CATALOGO.get(som_id) or self.enviados.get(som_id) or {}).get("nome", som_id)

    def caminho(self, som_id: str) -> Path:
        if som_id in self.enviados:
            return self.meus / f"{som_id}.wav"
        if som_id not in CATALOGO:
            raise KeyError(som_id)
        arquivo = self.pasta / f"{som_id}.wav"
        with self.trava:
            if not arquivo.exists():
                gravar_wav(arquivo, gerar_audio(som_id))
        return arquivo

    def listar(self, busca: str = "", categoria: str = "") -> list[dict]:
        termos = _sem_acento(busca).split()
        saida = []
        itens = [{**{k: v for k, v in s.items() if k != "gerar"}, "meu": False} for s in CATALOGO.values()]
        meus = [{"id": k, "nome": v["nome"], "categoria": "Meus sons", "tags": "", "meu": True} for k, v in self.enviados.items()]
        for s in [*meus, *itens]:
            if categoria and s["categoria"] != categoria:
                continue
            nome = _sem_acento(s["nome"])
            texto = f"{nome} {_sem_acento(s['categoria'])} {_sem_acento(s['tags'])}"
            if all(t in texto for t in termos):
                pontos = sum(3 if t in nome else 1 for t in termos)
                saida.append((-pontos, s))
        saida.sort(key=lambda x: x[0])
        return [s for _, s in saida]

    def enviar(self, nome: str, conteudo: bytes) -> dict:
        if not conteudo:
            raise ValueError("Escolha um arquivo de som.")
        if len(conteudo) > LIMITE_ENVIO:
            raise ValueError("O som precisa ter no máximo 120 MB.")
        titulo = re.sub(r"\s+", " ", Path(nome).stem.replace("_", " ")).strip()[:60] or "Meu som"
        som_id = f"meu-{int(time.time() * 1000)}"
        destino = self.meus / f"{som_id}.wav"
        original = self.meus / f"{som_id}.envio"  # M4A precisa de um arquivo: o índice fica no final
        original.write_bytes(conteudo)
        try:
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(original), "-t", str(DURACAO_MAXIMA_ENVIO), "-vn", "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", "-f", "wav", str(destino)],
                capture_output=True, **sem_janela(),
            )
        finally:
            original.unlink(missing_ok=True)
        if r.returncode != 0 or not destino.exists() or destino.stat().st_size < 2000:
            destino.unlink(missing_ok=True)
            raise ValueError("Não consegui ler este arquivo. Use MP3, WAV, OGG ou M4A.")
        with self.trava:
            self.enviados[som_id] = {"nome": titulo, "criado": time.time()}
            self._salvar()
        return {"id": som_id, "nome": titulo, "categoria": "Meus sons", "tags": "", "meu": True}

    def remover(self, som_id: str) -> None:
        with self.trava:
            if som_id not in self.enviados:
                raise ValueError("Só dá para apagar os sons enviados por você.")
            del self.enviados[som_id]
            self._salvar()
        (self.meus / f"{som_id}.wav").unlink(missing_ok=True)


# ------------------------------------------------------------ sons que combinam com o corte

PALAVRAS = [
    (r"\b(atir|tiro|bala|dispar)", "tiro_pistola", 0.42),
    (r"\b(rajada|metralh|fuzil)", "rajada", 0.4),
    (r"\b(explod|explos|bomba|granada)", "explosao", 0.45),
    (r"\b(pol[ií]cia|viatura|sirene|procurado)", "sirene_policia", 0.26),
    (r"\b(bateu|batida|capot|colid|acidente)", "freada", 0.4),
    (r"\b(acelera|corrida|motor|turbo)", "motor_acelerando", 0.28),
    (r"\b(drift|derrap)", "pneu_cantando", 0.32),
    (r"\b(dinheiro|grana|milh[ãõ]|banco|rico|paguei|comprei)", "caixa_registradora", 0.42),
    (r"\b(morr[ie]|perdi|perdeu|game over)", "game_over", 0.38),
    (r"\b(caiu|ca[ií]|tombo|despenc)", "queda_desenho", 0.4),
    (r"\b(socorro|medo|cuidado|assust)", "coracao", 0.42),
    (r"\b(ganhei|venci|consegui|ganhamos|vit[óo]ria)", "sucesso", 0.42),
    (r"\b(kkk+|hahaha+|rindo|engraçad)", "boing", 0.36),
    (r"\b(soco|porrada|murro)", "soco", 0.45),
    (r"\b(quebrou|quebrei|vidro)", "vidro_quebrando", 0.38),
    (r"\b(lind[oa]|maravilh|perfeit)", "brilho", 0.34),
]
REACAO = {
    "risada": ("ba_dum_tss", 0.42), "choque": ("impacto_cinema", 0.5), "jogo": ("boom_grave", 0.46), "hype": ("buzina_festa", 0.32),
    "clipe": ("sucesso", 0.42), "admirado": ("harpa", 0.34), "streamer": ("impacto_cinema", 0.46), "destaque": ("boom_grave", 0.46), "manual": ("boom_grave", 0.42),
}


def sugerir_sons(grupos: list[dict], duracao: float, momento: float | None, reacao: str | None) -> list[dict]:
    """Escolhe poucos efeitos, ligados ao que foi dito e à reação do streamer."""
    sons: list[dict] = []
    limite = max(2, int(duracao / 8) + 1)

    def livre(t: float, espaco: float = 4.5) -> bool:
        return all(abs(t - s["t"]) >= espaco for s in sons)

    if momento is not None and 0 <= momento < duracao:
        som, volume = REACAO.get(reacao or "", REACAO["destaque"])
        sons.append({"som": som, "t": round(momento, 2), "volume": volume})
        if reacao in ("choque", "hype", "streamer") and momento >= 2.2:
            sons.append({"som": "riser_curto", "t": round(momento - 1.4, 2), "volume": 0.24})
    if livre(0.0, 2.0):
        sons.append({"som": "whoosh_rapido", "t": 0.0, "volume": 0.3})
    usados = {s["som"] for s in sons}
    for palavra in (p for g in grupos for p in g.get("palavras", [])):
        if len(sons) >= limite:
            break
        t = float(palavra["ini"])
        for padrao, som, volume in PALAVRAS:
            if som not in usados and t < duracao - 0.4 and livre(t) and re.search(padrao, palavra["p"], re.I):
                sons.append({"som": som, "t": round(t, 2), "volume": volume})
                usados.add(som)
                break
    return sorted(sons, key=lambda s: s["t"])
