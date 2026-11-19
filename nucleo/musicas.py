"""Músicas de fundo compostas pelo próprio Clipador: livres de direitos autorais.

Cada faixa é gerada por síntese a partir de uma receita (ritmo, acordes e timbres),
então não há gravação de terceiros. As faixas são criadas na primeira vez que alguém usa.
"""
from __future__ import annotations

import numpy as np

SR = 48000
NOTAS = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
MENOR, MAIOR = (0, 3, 7, 10), (0, 4, 7, 11)


def _hz(semitom: float) -> float:
    return 440.0 * 2 ** ((semitom - 9) / 12)  # semitom 0 = Dó central (C4)


def _t(n: int) -> np.ndarray:
    return np.arange(n) / SR


def _env(n: int, ataque: float, queda: float, sustentar: float = 0.0) -> np.ndarray:
    t = _t(n)
    e = np.exp(-t * queda) * (1 - sustentar) + sustentar if queda else np.ones(n)
    a = min(n, max(1, int(SR * ataque)))
    e[:a] *= np.linspace(0, 1, a)
    f = min(n, int(SR * .01))
    e[-f:] *= np.linspace(1, 0, f)
    return e


def _onda(freq: float | np.ndarray, n: int, tipo: str) -> np.ndarray:
    f = np.full(n, freq) if np.isscalar(freq) else freq
    fase = 2 * np.pi * np.cumsum(f) / SR
    if tipo == "sen":
        return np.sin(fase)
    if tipo == "tri":
        return 2 * np.abs(2 * ((fase / (2 * np.pi)) % 1) - 1) - 1
    if tipo == "qua":
        return np.sign(np.sin(fase)) * .55
    if tipo == "pulso":
        return np.where((fase / (2 * np.pi)) % 1 < .25, .5, -.5)
    return 2 * ((fase / (2 * np.pi)) % 1) - 1  # serra


def _passa_baixa(x: np.ndarray, corte: float) -> np.ndarray:
    e = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    e *= 1 / np.sqrt(1 + (f / corte) ** 4)
    return np.fft.irfft(e, len(x))


def _passa_alta(x: np.ndarray, corte: float) -> np.ndarray:
    e = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    e *= 1 / np.sqrt(1 + (corte / np.maximum(f, 1)) ** 4)
    return np.fft.irfft(e, len(x))


def _ruido(n: int, semente: int) -> np.ndarray:
    return np.random.default_rng(semente).normal(0, .35, n)


# ------------------------------------------------------------ instrumentos

def bumbo(forca: float = 1.0, grave: float = 50) -> np.ndarray:
    n = int(SR * .42)
    f = grave + 110 * np.exp(-_t(n) * 32)
    return np.tanh(_onda(f, n, "sen") * _env(n, .001, 7) * 1.6 * forca)


def caixa(semente: int = 3, brilho: float = 1.0) -> np.ndarray:
    n = int(SR * .22)
    corpo = _onda(185, n, "tri") * _env(n, .001, 24) * .5
    chiado = _passa_alta(_ruido(n, semente), 1800 * brilho) * _env(n, .001, 17)
    return corpo + chiado * 1.3


def palma(semente: int = 5) -> np.ndarray:
    n = int(SR * .25)
    r = _passa_alta(_ruido(n, semente), 1200)
    e = np.zeros(n)
    for k, atraso in enumerate((0, .011, .022)):
        i = int(SR * atraso)
        e[i:] += np.exp(-_t(n - i) * (60 if k < 2 else 16)) * (.7 if k < 2 else 1)
    return r * e


def chimbal(aberto: bool = False, semente: int = 9) -> np.ndarray:
    n = int(SR * (.3 if aberto else .05))
    return _passa_alta(_ruido(n, semente), 7000) * _env(n, .001, 9 if aberto else 75) * 1.2


def cowbell(semitom: float, dur: float) -> np.ndarray:
    n = int(SR * dur)
    f = _hz(semitom)
    x = _onda(f, n, "qua") + _onda(f * 1.48, n, "qua") * .7
    return _passa_baixa(_passa_alta(x, 500), 3500) * _env(n, .002, 9) * .8


def grave_808(semitom: float, dur: float, deslize: float | None = None, sujo: float = 1.2) -> np.ndarray:
    n = int(SR * dur)
    f = np.full(n, _hz(semitom))
    if deslize is not None:
        k = min(n, int(SR * .09))
        f[:k] = np.linspace(_hz(deslize), _hz(semitom), k)
    return np.tanh(_onda(f, n, "sen") * sujo * 1.4) * _env(n, .004, 1.6, .25) * .9


def baixo(semitom: float, dur: float, tipo: str = "sen", corte: float = 900) -> np.ndarray:
    n = int(SR * dur)
    x = _onda(_hz(semitom), n, tipo)
    if tipo != "sen":
        x = _passa_baixa(x, corte)
    return x * _env(n, .006, 3, .55)


def acorde(semitons: list[float], dur: float, tipo: str = "serra", corte: float = 1800, ataque: float = .08, queda: float = 0, sust: float = 1.0) -> np.ndarray:
    n = int(SR * dur)
    x = sum(_onda(_hz(s) * d, n, tipo) for s in semitons for d in (1.0, 1.004))
    x = _passa_baixa(x / (2 * len(semitons)), corte)
    return x * (_env(n, ataque, queda, sust) if queda else _env(n, ataque, 0))


def toque(semitom: float, dur: float, tipo: str = "tri", queda: float = 7, corte: float | None = None) -> np.ndarray:
    n = int(SR * dur)
    x = _onda(_hz(semitom), n, tipo)
    if corte:
        x = _passa_baixa(x, corte)
    return x * _env(n, .003, queda)


def sino(semitom: float, dur: float) -> np.ndarray:
    n = int(SR * dur)
    t, f = _t(n), _hz(semitom)
    x = np.sin(2 * np.pi * f * t) + .5 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 6) + .25 * np.sin(2 * np.pi * f * 5.4 * t) * np.exp(-t * 12)
    return x * _env(n, .002, 3.2) * .6


def tambor(semitom: float = -12, semente: int = 4) -> np.ndarray:
    n = int(SR * .5)
    f = _hz(semitom) * (1 + .6 * np.exp(-_t(n) * 25))
    return np.tanh((_onda(f, n, "sen") + _passa_baixa(_ruido(n, semente), 900) * .3) * _env(n, .002, 6) * 1.3)


def drone(semitom: float, n: int) -> np.ndarray:
    t = _t(n)
    x = sum(_onda(_hz(semitom) * m * (1 + .002 * k), n, "serra") for k, m in enumerate((1, 1.5, 2)))
    x = _passa_baixa(x, 420) * (.6 + .4 * np.sin(2 * np.pi * .11 * t))
    return x * .35


def chiado_vinil(n: int, semente: int = 11) -> np.ndarray:
    rng = np.random.default_rng(semente)
    x = _passa_baixa(_passa_alta(rng.normal(0, .04, n), 900), 6000)
    estalos = np.zeros(n)
    estalos[rng.integers(0, n, n // SR * 7)] = rng.uniform(.2, .6, n // SR * 7)
    return x + _passa_alta(estalos, 2000)


def eco(x: np.ndarray, atraso: float, volta: float = .35, vezes: int = 4) -> np.ndarray:
    saida = np.copy(x)
    d = int(SR * atraso)
    for k in range(1, vezes + 1):
        if d * k >= len(x):
            break
        saida[d * k:] += x[:-d * k] * volta ** k
    return saida


# ------------------------------------------------------------ montagem da música

class Faixa:
    def __init__(self, bpm: float, compassos: int, swing: float = 0.0):
        self.bpm, self.compassos, self.swing = bpm, compassos, swing
        self.passo = 60 / bpm / 4
        self.n = int(SR * self.passo * 16 * compassos) + SR * 2
        self.camadas: dict[str, np.ndarray] = {}

    def em(self, passo: int) -> float:
        return passo * self.passo + (self.passo * self.swing if passo % 2 else 0)

    def por(self, camada: str, inicio: float, som: np.ndarray, ganho: float = 1.0) -> None:
        alvo = self.camadas.setdefault(camada, np.zeros(self.n))
        i = int(inicio * SR)
        if i >= self.n:
            return
        fim = min(self.n, i + len(som))
        alvo[i:fim] += som[:fim - i] * ganho

    def ritmo(self, camada: str, padrao: str, som, compassos: range, ganho: float = 1.0) -> None:
        """Padrão de 16 passos: x = toca, o = toca mais fraco, . = silêncio."""
        for c in compassos:
            for k, ch in enumerate(padrao):
                if ch in "xo":
                    self.por(camada, self.em(c * 16 + k), som() if callable(som) else som, ganho * (1 if ch == "x" else .55))

    def bombear(self, camada: str, profundidade: float = .7) -> None:
        """Efeito de "respirar" com o bumbo, comum na música eletrônica."""
        x = self.camadas.get(camada)
        if x is None:
            return
        batida = int(SR * self.passo * 4)
        e = 1 - profundidade * np.exp(-_t(batida) * 9)
        x *= np.resize(e, len(x))

    def mixar(self, volumes: dict[str, float]) -> np.ndarray:
        x = sum(self.camadas[k] * volumes.get(k, 1.0) for k in self.camadas)
        fim = int(SR * self.passo * 16 * self.compassos)
        x = x[:fim + SR]
        cauda = len(x) - fim
        x[fim:] *= np.linspace(1, 0, cauda)
        entra = int(SR * .02)
        x[:entra] *= np.linspace(0, 1, entra)
        x = np.tanh(x * 1.1) / np.tanh(1.1)
        return x


def _progressao(raiz: int, graus: list[tuple[int, tuple]]) -> list[list[int]]:
    return [[raiz + g + i for i in tipo] for g, tipo in graus]


def _melodia(rng, acordes: list[list[int]], compassos: int, densidade: float, oitava: int = 12, passo_nota: int = 2) -> list[tuple[int, int, int]]:
    """Cria um motivo de 2 compassos com notas dos acordes e repete com pequenas variações."""
    motivo = []
    for k in range(0, 32, passo_nota):
        if rng.random() < densidade:
            motivo.append((k, int(rng.integers(0, 4)), passo_nota * int(rng.choice([1, 1, 2]))))
    notas = []
    for c in range(0, compassos, 2):
        varia = c % 8 == 6
        for k, grau, dur in motivo:
            compasso = c + k // 16
            if compasso >= compassos:
                continue
            ac = acordes[compasso % len(acordes)]
            g = (grau + (1 if varia and k % 4 == 0 else 0)) % len(ac)
            notas.append((compasso * 16 + k % 16, ac[g] + oitava, dur))
    return notas


def compor(estilo: str, semente: int) -> np.ndarray:
    rng = np.random.default_rng(semente)
    raiz = int(rng.choice([-3, -2, 0, 2, 3, 5]))
    if estilo == "lofi":
        f = Faixa(80, 20, swing=.18)
        ac = _progressao(raiz, [(2, MENOR), (7, (0, 4, 7, 10)), (0, MAIOR), (9, MENOR)])
        for c in range(f.compassos):
            f.por("acorde", f.em(c * 16), acorde(ac[c % 4], f.passo * 16 + .3, "tri", 1400, .05), .9)
            f.por("baixo", f.em(c * 16), baixo(ac[c % 4][0] - 24, f.passo * 6), .9)
            f.por("baixo", f.em(c * 16 + 10), baixo(ac[c % 4][0] - 24, f.passo * 4), .7)
        tocar = range(2, f.compassos)
        f.ritmo("bumbo", "x.....x...x.....", lambda: bumbo(.8, 55), tocar)
        f.ritmo("caixa", "....x.......x...", lambda: _passa_baixa(caixa(3, .7), 5000), tocar, .6)
        f.ritmo("chimbal", "x.o.x.o.x.o.x.oo", chimbal, tocar, .35)
        for p, s, d in _melodia(rng, ac, f.compassos, .45):
            if p >= 64:
                f.por("melodia", f.em(p), sino(s, f.passo * d + .6), .45)
        f.por("vinil", 0, chiado_vinil(f.n, semente), .35)
        return f.mixar({"acorde": .55, "baixo": .8, "bumbo": .9, "caixa": .7, "chimbal": .6, "melodia": .5, "vinil": .5})
    if estilo == "trap":
        f = Faixa(140, 32)
        ac = _progressao(raiz, [(0, MENOR), (8, MAIOR), (3, MAIOR), (10, MAIOR)])
        for c in range(f.compassos):
            f.por("acorde", f.em(c * 16), acorde(ac[(c // 2) % 4], f.passo * 16, "serra", 900, .2), .7)
        tocar = range(4, f.compassos)
        f.ritmo("bumbo", "x.........x..x..", lambda: bumbo(1, 45), tocar)
        f.ritmo("palma", "........x.......", palma, tocar, .9)
        for c in tocar:
            pad = "xxxxxxxxxxxxxxxx" if c % 4 != 3 else "xxxxxxxx" + "x.x.xxxxxxxx"[:8]
            for k, ch in enumerate(pad):
                if ch == "x":
                    f.por("chimbal", f.em(c * 16 + k), chimbal(False, 9 + k), .5 if k % 2 else .8)
            if c % 4 == 3:
                for k in range(12, 16):
                    f.por("chimbal", f.em(c * 16 + k) + f.passo / 2, chimbal(False, 30 + k), .45)
            r = ac[(c // 2) % 4][0] - 24
            f.por("808", f.em(c * 16), grave_808(r, f.passo * 10, r + 5 if c % 2 else None))
            f.por("808", f.em(c * 16 + 13), grave_808(r + 7, f.passo * 3), .8)
        for p, s, d in _melodia(rng, [[a for a in x] for x in ac], f.compassos, .35, 12, 2):
            f.por("sino", f.em(p), sino(s, f.passo * d + .4), .5)
        return f.mixar({"acorde": .35, "bumbo": 1, "palma": .7, "chimbal": .5, "808": .9, "sino": .55})
    if estilo == "phonk":
        f = Faixa(130, 32)
        ac = _progressao(raiz, [(0, MENOR), (0, MENOR), (5, MENOR), (7, MENOR)])
        tocar = range(2, f.compassos)
        f.ritmo("bumbo", "x..x..x...x..x..", lambda: bumbo(1.1, 48), tocar)
        f.ritmo("caixa", "....x.......x...", lambda: caixa(3, 1.2), tocar, .8)
        f.ritmo("chimbal", "x.x.x.x.x.x.x.xx", chimbal, tocar, .4)
        frase = [0, 0, 3, 0, 7, 5, 3, 0]
        for c in range(f.compassos):
            r = ac[c % 4][0]
            for k in range(8):
                f.por("cowbell", f.em(c * 16 + k * 2), cowbell(r + 12 + frase[(k + c) % 8], f.passo * 2), .6)
            if c >= 2:
                f.por("808", f.em(c * 16), grave_808(r - 24, f.passo * 8, sujo=2.4), .9)
                f.por("808", f.em(c * 16 + 10), grave_808(r - 24 + 3, f.passo * 6, sujo=2.4), .8)
        return f.mixar({"bumbo": 1, "caixa": .7, "chimbal": .5, "cowbell": .55, "808": .85})
    if estilo == "eletronica":
        f = Faixa(124, 32)
        ac = _progressao(raiz, [(9, MENOR), (5, MAIOR), (0, MAIOR), (7, MAIOR)])
        tocar = range(4, f.compassos)
        f.ritmo("bumbo", "x...x...x...x...", lambda: bumbo(1, 50), tocar)
        f.ritmo("palma", "....x.......x...", palma, range(8, f.compassos), .7)
        f.ritmo("chimbal", "..x...x...x...x.", lambda: chimbal(True), tocar, .45)
        for c in range(f.compassos):
            a = ac[(c // 2) % 4]
            for k in (0, 3, 6, 10, 12):
                f.por("acorde", f.em(c * 16 + k), acorde([s + 12 for s in a[:3]], f.passo * 2.5, "serra", 2600, .01, 9, .2), .9)
            if c >= 4:
                for k in (2, 6, 10, 14):
                    f.por("baixo", f.em(c * 16 + k), baixo(a[0] - 24, f.passo * 1.8, "serra", 600), .9)
        for p, s, d in _melodia(rng, ac, f.compassos, .5, 24, 1):
            if p >= 128:
                f.por("lead", f.em(p), toque(s, f.passo * d + .1, "pulso", 9, 4000), .3)
        f.bombear("acorde", .75)
        f.bombear("baixo", .5)
        return f.mixar({"bumbo": 1, "palma": .6, "chimbal": .45, "acorde": .5, "baixo": .7, "lead": .5})
    if estilo == "suspense":
        f = Faixa(90, 20)
        r = raiz - 12
        f.por("drone", 0, drone(r - 12, f.n), 1)
        for c in range(f.compassos):
            for k in range(0, 16, 2):
                f.por("pulso", f.em(c * 16 + k), toque(r + (1 if c % 4 == 3 else 0), f.passo * 1.6, "serra", 14, 700), .45)
            if c % 4 == 0:
                f.por("impacto", f.em(c * 16), tambor(r - 24), 1)
            if c >= 8:
                f.ritmo("tique", "x...x...x...x...", lambda: chimbal(False, 70), range(c, c + 1), .4)
        for c in range(4, f.compassos, 4):
            f.por("sino", f.em(c * 16 + 8), sino(r + 25, 3), .35)
        return f.mixar({"drone": .8, "pulso": .6, "impacto": .9, "tique": .5, "sino": .5})
    if estilo == "epico":
        f = Faixa(100, 24)
        ac = _progressao(raiz, [(0, MENOR), (8, MAIOR), (3, MAIOR), (10, MAIOR)])
        for c in range(f.compassos):
            a = ac[c % 4]
            f.por("cordas", f.em(c * 16), acorde([a[0], a[1], a[2], a[0] + 12], f.passo * 16 + .2, "serra", 2200 if c >= 8 else 1100, .25), .9)
            f.por("baixo", f.em(c * 16), baixo(a[0] - 24, f.passo * 16, "serra", 300), .8)
        tocar = range(4, f.compassos)
        f.ritmo("tambores", "x..x..x...x.x.x.", lambda: tambor(-17), tocar)
        f.ritmo("caixa", "....x.......x...", lambda: eco(caixa(3), .12, .3, 3), range(8, f.compassos), .7)
        for p, s, d in _melodia(rng, ac, f.compassos, .4, 12, 4):
            if p >= 128:
                f.por("metais", f.em(p), toque(s, f.passo * d, "serra", 1.5, 2400), .4)
        return f.mixar({"cordas": .55, "baixo": .6, "tambores": .9, "caixa": .55, "metais": .6})
    if estilo == "divertido":
        f = Faixa(118, 24)
        ac = _progressao(raiz, [(0, MAIOR[:3]), (5, MAIOR[:3]), (7, MAIOR[:3]), (0, MAIOR[:3])])
        tocar = range(2, f.compassos)
        f.ritmo("bumbo", "x.......x.......", lambda: bumbo(.8, 60), tocar)
        f.ritmo("palma", "....x.......x...", palma, tocar, .7)
        f.ritmo("chimbal", "x.x.x.x.x.x.x.x.", chimbal, tocar, .3)
        for c in range(f.compassos):
            a = ac[c % 4]
            for k in (0, 4, 8, 12):
                f.por("baixo", f.em(c * 16 + k), toque(a[0] - 24 + (7 if k in (4, 12) else 0), f.passo * 2, "tri", 10), .9)
            for k in (2, 6, 10, 14):
                f.por("pluck", f.em(c * 16 + k), acorde([s + 12 for s in a], f.passo * 1.2, "qua", 3000, .002, 14, 0), .8)
        for p, s, d in _melodia(rng, ac, f.compassos, .55, 24, 2):
            f.por("sino", f.em(p), sino(s, f.passo * d + .3), .5)
        return f.mixar({"bumbo": .9, "palma": .6, "chimbal": .4, "baixo": .7, "pluck": .45, "sino": .6})
    if estilo == "8bit":
        f = Faixa(150, 32)
        ac = _progressao(raiz, [(0, MAIOR[:3]), (9, MENOR[:3]), (5, MAIOR[:3]), (7, MAIOR[:3])])
        tocar = range(2, f.compassos)
        f.ritmo("bateria", "x...o.x.x...o...", lambda: _passa_baixa(_ruido(int(SR * .06), 2), 3000) * _env(int(SR * .06), .001, 50) * 2, tocar)
        for c in range(f.compassos):
            a = ac[(c // 2) % 4]
            for k in range(16):
                f.por("arpejo", f.em(c * 16 + k), toque(a[k % 3] + 12, f.passo * .9, "pulso", 4), .45)
            for k in range(0, 16, 2):
                f.por("baixo", f.em(c * 16 + k), toque(a[0] - 12, f.passo * 1.8, "tri", 2), .9)
        for p, s, d in _melodia(rng, ac, f.compassos, .6, 24, 2):
            if p >= 64:
                f.por("lead", f.em(p), toque(s, f.passo * d * .95, "qua", 2), .35)
        return f.mixar({"bateria": .7, "arpejo": .35, "baixo": .7, "lead": .55})
    if estilo == "synthwave":
        f = Faixa(100, 24)
        ac = _progressao(raiz, [(9, MENOR), (5, MAIOR), (0, MAIOR), (7, MAIOR)])
        tocar = range(4, f.compassos)
        f.ritmo("bumbo", "x.......x.......", lambda: bumbo(1, 52), tocar)
        f.ritmo("caixa", "....x.......x...", lambda: eco(caixa(3), .09, .45, 6), tocar, .7)
        f.ritmo("chimbal", "x.x.x.x.x.x.x.x.", chimbal, tocar, .3)
        for c in range(f.compassos):
            a = ac[c % 4]
            f.por("pad", f.em(c * 16), acorde([s + 12 for s in a], f.passo * 16 + .3, "serra", 1600, .4), .8)
            for k in range(0, 16, 2):
                f.por("baixo", f.em(c * 16 + k), baixo(a[0] - 24, f.passo * 1.7, "serra", 700), .8)
            for k in range(16):
                f.por("arpejo", f.em(c * 16 + k), toque(a[k % 4] + 24, f.passo * .8, "serra", 12, 3000), .3)
        return f.mixar({"bumbo": 1, "caixa": .6, "chimbal": .35, "pad": .5, "baixo": .7, "arpejo": .35})
    if estilo == "chill":
        f = Faixa(92, 20)
        ac = _progressao(raiz, [(0, MAIOR), (9, MENOR), (5, MAIOR), (7, (0, 4, 7, 10))])
        tocar = range(2, f.compassos)
        f.ritmo("bumbo", "x.........x.....", lambda: bumbo(.7, 58), tocar)
        f.ritmo("palma", "....x.......x...", lambda: _passa_baixa(palma(), 4000), tocar, .5)
        f.ritmo("chimbal", "..x...x...x...x.", chimbal, tocar, .3)
        for c in range(f.compassos):
            a = ac[c % 4]
            for k in (0, 6, 10):
                for s in a:
                    f.por("piano", f.em(c * 16 + k) + .012 * a.index(s), sino(s, f.passo * 6), .35)
            f.por("baixo", f.em(c * 16), baixo(a[0] - 24, f.passo * 12), .8)
        return f.mixar({"bumbo": .8, "palma": .5, "chimbal": .35, "piano": .7, "baixo": .7})
    if estilo == "funk":
        f = Faixa(130, 32)
        ac = _progressao(raiz, [(0, MENOR), (0, MENOR), (8, MAIOR), (10, MAIOR)])
        tocar = range(2, f.compassos)
        f.ritmo("bumbo", "x..x..x...x..x..", lambda: bumbo(1.1, 46), tocar)
        f.ritmo("tambor", "...x..x....x..x.", lambda: tambor(-5, 8), tocar, .7)
        f.ritmo("palma", "....x.......x...", palma, tocar, .8)
        f.ritmo("chimbal", "x.x.x.x.x.x.x.x.", chimbal, tocar, .3)
        for c in range(f.compassos):
            a = ac[c % 4]
            f.por("808", f.em(c * 16), grave_808(a[0] - 24, f.passo * 6, sujo=1.8), .9)
            f.por("808", f.em(c * 16 + 6), grave_808(a[0] - 24, f.passo * 4, sujo=1.8), .8)
            if c % 2:
                f.por("sopro", f.em(c * 16 + 12), toque(a[2] + 12, f.passo * 3, "serra", 6, 2500), .35)
        return f.mixar({"bumbo": 1, "tambor": .7, "palma": .7, "chimbal": .4, "808": .85, "sopro": .6})
    raise KeyError(estilo)


PACKS = (
    ("lofi", "Lo-fi", "estudar calmo relaxar vlog conversa", ("Café da tarde", "Chuva na janela")),
    ("trap", "Trap", "beat rap pesado 808 hype", ("Noite na quebrada", "Corrente de ouro")),
    ("phonk", "Phonk", "drift carro gamer agressivo cowbell", ("Drift na madrugada", "Fumaça no asfalto")),
    ("eletronica", "Eletrônica", "house edm dançar festa energia", ("Pista cheia", "Luz neon")),
    ("suspense", "Suspense", "tensão terror mistério investigação", ("Algo está errado", "Corredor escuro")),
    ("epico", "Épico", "trailer cinema vitória batalha grandioso", ("Última batalha", "Coroação")),
    ("divertido", "Divertido", "comédia engraçado feliz alegre fofo", ("Dia de sol", "Trapalhada")),
    ("8bit", "Gamer 8-bit", "jogo retro arcade pixel videogame", ("Fase bônus", "Chefão final")),
    ("synthwave", "Synthwave", "anos 80 retro neon dirigir noite", ("Estrada de neon", "Fita cassete")),
    ("chill", "Chill", "tranquilo suave bonito viagem", ("Pôr do sol", "Brisa leve")),
    ("funk", "Funk", "baile batidão brasil dança", ("Batidão", "Baile de favela")),
)


def catalogo() -> list[tuple]:
    """Entradas no formato da biblioteca de sons: (id, nome, categoria, palavras, gerar)."""
    saida = []
    for n, (estilo, pack, tags, nomes) in enumerate(PACKS):
        for k, nome in enumerate(nomes):
            semente = 1000 + n * 17 + k * 101
            saida.append((f"musica_{estilo}_{k + 1}", nome, f"Música: {pack}", f"musica fundo trilha {pack.lower()} {tags}", (lambda e=estilo, s=semente: compor(e, s))))
    return saida
