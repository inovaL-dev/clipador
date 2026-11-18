"""Dá uma nota de 0 a 100 para cada momento da live.

A nota combina a reação de voz do streamer com a aceleração e a emoção do chat. Tudo é
comparado com o ritmo da própria live, então funciona em chats pequenos e gigantes.
"""
from __future__ import annotations

import re
import statistics
import subprocess
from collections import Counter, deque
from pathlib import Path

import numpy as np

from .deteccao import REACOES
from .plataformas import sem_janela

LIMITES = {"baixa": 60, "media": 40, "alta": 30}
INTERVALO_MINIMO = 45
AQUECIMENTO = 5
RUIDO_MINIMO = 12
PEDIDO_CLIPE = REACOES["clipe"][1]


class Medidor:
    """Mede o quanto um valor foge do normal recente, sem se deixar levar por picos."""

    def __init__(self, piso: float, historico: int = 36):
        self.piso = piso
        self.hist: deque[float] = deque(maxlen=historico)

    def desvio(self, valor: float, piso: float | None = None) -> float:
        if len(self.hist) < AQUECIMENTO:
            return 0.0
        mediana = statistics.median(self.hist)
        mad = statistics.median(abs(v - mediana) for v in self.hist) * 1.4826
        return (valor - mediana) / max(mad, piso if piso is not None else self.piso)

    def guardar(self, valor: float) -> None:
        self.hist.append(valor)

    @property
    def mediana(self) -> float:
        return statistics.median(self.hist) if self.hist else 0.0


def medir_audio(arquivos: list[Path]) -> dict | None:
    """Mede volume, gritos curtos e brilho da voz nos trechos recém-gravados."""
    blocos = []
    for arq in arquivos:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(arq), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
            capture_output=True, **sem_janela(),
        )
        if r.stdout:
            blocos.append(np.frombuffer(r.stdout, dtype=np.int16))
    return medir_pcm(np.concatenate(blocos)) if blocos else None


def medir_pcm(pcm: np.ndarray, taxa: int = 16000) -> dict | None:
    tamanho = int(taxa * 0.05)
    n = len(pcm) // tamanho
    if n < 20:
        return None
    quadros = pcm[: n * tamanho].reshape(n, tamanho).astype(np.float32) / 32768
    db = 10 * np.log10(np.mean(quadros**2, axis=1) + 1e-10)
    som = db[db > -55]
    if len(som) < 10:
        return {"forte": -60.0, "medio": -60.0, "brilho": 0.0}
    limite = np.percentile(som, 75)
    fortes = quadros[db >= limite][:60]
    janela = np.hanning(tamanho)
    espectro = np.abs(np.fft.rfft(fortes * janela, axis=1)) ** 2
    freqs = np.fft.rfftfreq(tamanho, 1 / taxa)
    brilho = float(np.mean(np.sum(espectro * freqs, axis=1) / (np.sum(espectro, axis=1) + 1e-10)))
    return {"forte": float(np.percentile(som, 95)), "medio": float(np.mean(som)), "brilho": brilho}


def contar_exclamacoes(texto: str | None) -> int:
    from .sentidos import contar_exclamacoes as contar

    return contar(texto)


def analisar_chat(textos: list[str]) -> dict:
    total = len(textos)
    if not total:
        return {"emocao": 0.0, "pedidos": 0}
    emocionadas = sum(1 for t in textos if any(p.search(t) for _, p in REACOES.values()))
    normalizadas = Counter(re.sub(r"(.)\1{2,}", r"\1\1", t.casefold().strip()) for t in textos if t.strip())
    repetidas = normalizadas.most_common(1)[0][1] if normalizadas else 0
    return {
        "emocao": max(emocionadas, repetidas) / total,
        "pedidos": sum(1 for t in textos if PEDIDO_CLIPE.search(t)),
    }


class PontuadorMomento:
    def __init__(self, sensibilidade: str = "media"):
        self.limite = LIMITES[sensibilidade]
        self.volume = Medidor(1.5)
        self.emocao = Medidor(0.08)
        self.forte = Medidor(1.5)
        self.medio = Medidor(1.5)
        self.brilho = Medidor(150.0)
        self.surpresa = Medidor(0.06)
        self.alegria = Medidor(0.08)
        self.movimento = Medidor(0.6)
        self.clarao = Medidor(2.0)
        self.janelas = 0
        self.ultimo_disparo = -1e9

    @property
    def aquecido(self) -> bool:
        return self.janelas > AQUECIMENTO

    def avaliar(self, msgs: int, textos: list[str], leitura: dict | None = None) -> dict:
        leitura = leitura or {}
        audio, visao = leitura.get("audio"), leitura.get("visao")
        self.janelas += 1

        ruido = max(1.5, self.volume.mediana**0.5)
        z_volume = self.volume.desvio(msgs, ruido)
        dados_chat = analisar_chat(textos)
        z_emocao = self.emocao.desvio(dados_chat["emocao"]) if msgs >= 4 else 0.0
        chat = _faixa((z_volume - 1.0) * 14, 50)
        emocao = _faixa((z_emocao - 1.0) * 9, 22) + (min(18, dados_chat["pedidos"] * 5) if dados_chat["pedidos"] >= 2 else 0)

        voz, z_medio = 0.0, 0.0
        if audio:
            z_forte, z_medio = self.forte.desvio(audio["forte"]), self.medio.desvio(audio["medio"])
            z_brilho = self.brilho.desvio(audio["brilho"])
            subida = max(z_forte, 0) * 0.55 + max(z_medio, 0) * 0.45
            if subida >= 1.0:  # brilho só conta quando a voz realmente subiu
                subida += max(z_brilho, 0) * 0.25
            voz = _faixa((subida - 1.0) * 20, 60)

        rosto = jogo = 0.0
        if visao:
            surpresa, alegria = visao.get("surpresa"), visao.get("alegria")
            if surpresa is not None and surpresa >= 0.2:
                rosto = _faixa((self.surpresa.desvio(surpresa) - 1.0) * 11, 40)
            if alegria is not None and alegria >= 0.4:
                rosto = max(rosto, _faixa((self.alegria.desvio(alegria) - 1.0) * 8, 24))
            jogo = _faixa((self.movimento.desvio(visao["movimento"]) - 1.7) * 12, 30)
            jogo += min(10, max(0, visao["cenas"] - 1) * 3)
            jogo += 6 if self.clarao.desvio(visao["clarao"]) >= 2.5 else 0
            jogo = min(42.0, jogo)

        exclamacao = min(40.0, contar_exclamacoes(leitura.get("fala")) * 22.0)
        # Ficar quieto de repente reforça a admiração, mas sozinho não é um momento.
        silencio = 12.0 if z_medio <= -1.2 and (rosto or jogo >= 15) else 0.0
        admirado = min(70.0, rosto + exclamacao + silencio)

        self.volume.guardar(msgs)
        if msgs >= 4:
            self.emocao.guardar(dados_chat["emocao"])
        if audio:
            self.forte.guardar(audio["forte"])
            self.medio.guardar(audio["medio"])
            self.brilho.guardar(audio["brilho"])
        if visao:
            self.movimento.guardar(visao["movimento"])
            self.clarao.guardar(visao["clarao"])
            if visao.get("surpresa") is not None:
                self.surpresa.guardar(visao["surpresa"])
            if visao.get("alegria") is not None:
                self.alegria.guardar(visao["alegria"])

        total_chat = min(100.0, chat + emocao)
        streamer = min(100.0, voz + admirado)
        # Oscilações pequenas não somam: só sinais claros formam um momento.
        sinais = [v for v in (total_chat, streamer, jogo) if v >= RUIDO_MINIMO]
        nota = min(100.0, sum(sinais)) if self.aquecido else 0.0
        causas = {"chat": total_chat, "streamer": voz, "admirado": admirado, "jogo": jogo}
        return {
            "nota": round(nota), "chat": round(total_chat), "streamer": round(streamer), "jogo": round(jogo),
            "causa": max(causas, key=causas.get),
        }

    def disparar(self, nota: float, pos: float) -> bool:
        if not self.aquecido or nota < self.limite or pos - self.ultimo_disparo < INTERVALO_MINIMO:
            return False
        self.ultimo_disparo = pos
        return True


def _faixa(valor: float, maximo: float) -> float:
    return max(0.0, min(maximo, valor))
