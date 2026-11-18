"""Decide quando o chat explodiu e que tipo de reação aconteceu."""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, deque

SENSIBILIDADES = {
    "baixa": {"multiplicador": 4.0, "minimo": 30.0},
    "media": {"multiplicador": 3.0, "minimo": 15.0},
    "alta": {"multiplicador": 2.0, "minimo": 8.0},
}

REACOES = {
    "risada": ("Risada", re.compile(r"k{3,}|\brs{2,}\b|ha(?:ha)+|\blol\b|\blul\b|kekw|omegalul|😂|🤣", re.I)),
    "clipe": ("Pediram clipe", re.compile(r"\bclip|\bcorta\b|\bcortem\b", re.I)),
    "choque": ("Choque", re.compile(r"meu deus|nossa|oloco|oloko|\bwtf\b|\bomg\b|caraca|caramba|que isso|😱|😳", re.I)),
    "hype": ("Hype", re.compile(r"\bpog|\bgg+\b|\bw+\b|absurd|insano|monstro|brabo|lend[aá]rio|gol+|🔥|🐐", re.I)),
}


class Detector:
    """Compara cada janela de 10 s com o ritmo normal da live."""

    def __init__(self, multiplicador=3.0, minimo=15.0, aquecimento=6, historico=30, intervalo=60):
        self.multiplicador = multiplicador
        self.minimo = minimo
        self.aquecimento = aquecimento
        self.intervalo = intervalo
        self.hist: deque[float] = deque(maxlen=historico)
        self.ultimo = -math.inf
        self.seguidos = 0

    @property
    def base(self) -> float:
        return statistics.median(self.hist) if self.hist else 0.0

    @property
    def limite(self) -> float:
        return max(self.minimo, max(self.base, 1e-9) * self.multiplicador)

    @property
    def aquecido(self) -> bool:
        return len(self.hist) >= self.aquecimento

    def alimentar(self, valor: float, agora: float) -> bool:
        if not self.aquecido:
            self.hist.append(valor)
            return False
        if valor < self.limite:
            self.seguidos = 0
            self.hist.append(valor)
            return False
        # Um pico muito longo vira o novo normal da live.
        self.seguidos += 1
        if self.seguidos >= 6:
            self.hist.append(valor)
        if agora - self.ultimo < self.intervalo:
            return False
        self.ultimo = agora
        return True


class SeletorMomento:
    """Guarda o momento mais forte para garantir cortes mesmo sem explosão no chat."""

    def __init__(self, intervalo: float):
        self.intervalo = intervalo
        self.ultimo_corte = 0.0
        self.melhor: dict | None = None

    def registrar(self, pos: float, nota: float, dados: dict) -> None:
        if pos < 15 or (self.ultimo_corte and pos - self.ultimo_corte < 40):
            return  # evita repetir o trecho do corte anterior
        if self.melhor is None or nota > self.melhor["nota"]:
            self.melhor = {**dados, "pos": pos, "nota": nota}

    def vencido(self, pos: float) -> dict | None:
        if self.intervalo and self.melhor and pos - self.ultimo_corte >= self.intervalo:
            return self.melhor
        return None

    def marcar_corte(self, pos: float) -> None:
        self.ultimo_corte = pos
        self.melhor = None

    def restante(self, pos: float) -> float | None:
        return max(0.0, self.intervalo - (pos - self.ultimo_corte)) if self.intervalo else None


def classificar_reacao(textos: list[str]) -> dict:
    votos = Counter()
    for texto in textos:
        for tipo, (_, padrao) in REACOES.items():
            if padrao.search(texto):
                votos[tipo] += 1
    tipo = votos.most_common(1)[0][0] if votos else "hype"
    return {"tipo": tipo, "rotulo": REACOES[tipo][0]}


def mensagens_marcantes(textos: list[str], limite=5) -> list[str]:
    contagem = Counter()
    original = {}
    for texto in textos:
        limpo = re.sub(r"\s+", " ", texto).strip()
        if not 2 <= len(limpo) <= 40:
            continue
        chave = limpo.casefold()
        contagem[chave] += 1
        original.setdefault(chave, limpo)
    return [original[c] for c, _ in contagem.most_common(limite)]
