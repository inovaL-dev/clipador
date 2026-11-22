"""Gancho de abertura dos Shorts: começar pelo auge.

Quem rola o feed decide em 1 a 2 segundos se fica. Por isso o corte pode abrir com 1,5 a 3 segundos do
melhor momento (o grito, a risada, o susto), voltar com um efeito de fita rebobinando e então contar a
história do começo.

Só vale a pena quando a prévia se entende sozinha. Um pedaço de frase solto no começo deixa o vídeo sem
sentido, então a prévia só entra quando:
- existe um pico de som de verdade perto do momento, e ele é o mais forte do corte (o auge mesmo);
- o trecho é uma reação que se entende sem contexto: riso, grito, uma fala forte curta ou uma frase
  inteira e curta, que começa e termina em pausa;
- a prévia não repete o que já aparece nos primeiros segundos.
Na dúvida, não tem prévia: o corte começa direto na história.

O Clipador também aprende: quando você tira a prévia de um corte ou apaga cortes que abriam com ela,
ele passa a exigir um auge ainda mais claro.
"""
from __future__ import annotations

import re

from . import contexto as ctx

RISO = re.compile(r"^(k{3,}|(ha){2,}h?|(he){2,}h?|(rs){2,}|kakak\w*|aha+h*|hahaha\w*)$", re.I)
GRITO = re.compile(r"^(a{3,}h*|o{3,}h*|u{3,}h*|ah{2,}|nã{2,}o+|nao{2,}|n[ãa]o+o+|caraca+|caramba+|meu deus+|vai+i+|ai+i+)$", re.I)
DURACAO = (1.4, 2.4, 3.2)  # mínima, ideal e máxima da prévia
SEM_PREVIA_ANTES = 5.0      # se o auge já está nos primeiros segundos, o começo prende sozinho
PAUSA = .22                  # silêncio que separa uma frase da outra
PICO_MINIMO = 2.6            # força mínima do pico de som (desvios acima do normal do corte)
MAX_PALAVRAS = 7             # uma prévia com mais palavras que isso é conversa, não reação


def _palavras(grupos: list[dict]) -> list[dict]:
    return sorted((p for g in grupos or [] for p in g.get("palavras") or [] if str(p.get("p", "")).strip()), key=lambda p: float(p["ini"]))


def _reacao(p: dict) -> bool:
    n = ctx._nucleo(p["p"])
    return bool(RISO.match(n) or GRITO.match(n) or ctx.FORTES.search(p["p"]) or p["p"].rstrip().endswith("!"))


def _termina_frase(palavras: list[dict], i: int) -> bool:
    """A palavra i fecha uma frase: pontuação ou pausa antes da próxima."""
    if palavras[i]["p"].rstrip()[-1:] in ".!?":
        return True
    return i + 1 >= len(palavras) or float(palavras[i + 1]["ini"]) - float(palavras[i]["fim"]) >= PAUSA


def _comeca_frase(palavras: list[dict], i: int) -> bool:
    if i == 0:
        return True
    if palavras[i - 1]["p"].rstrip()[-1:] in ".!?":
        return True
    return float(palavras[i]["ini"]) - float(palavras[i - 1]["fim"]) >= PAUSA and ctx._nucleo(palavras[i]["p"]) not in ctx.CONECTIVOS


def escolher(grupos: list[dict], duracao: float, momento: float | None, picos: list[tuple[float, float]], exigencia: float = 1.0) -> list[float] | None:
    """Devolve [início, fim] da prévia no tempo do corte, ou None quando ela não faria sentido."""
    if duracao < 16 or momento is None:
        return None
    exigencia = max(1.0, min(1.8, float(exigencia or 1.0)))
    palavras = _palavras(grupos)
    a0, b0 = max(0.0, momento - 1.5), min(duracao - 1.0, momento + 6.0)
    perto = [(float(t), float(f)) for t, f in picos if a0 <= t <= b0]
    if not perto:
        return None
    t, forca = max(perto, key=lambda x: x[1])
    maior = max(float(f) for _, f in picos)
    # Tem que ser o auge do corte de verdade, não só um barulho a mais
    if forca < PICO_MINIMO * exigencia or forca < maior * .85:
        return None
    if t - 1.0 < SEM_PREVIA_ANTES:
        return None

    # A frase falada no pico (a palavra mais perto dele e a frase inteira em volta)
    perto_do_pico = [k for k, p in enumerate(palavras) if float(p["fim"]) > t - .7 and float(p["ini"]) < t + .7]
    if not perto_do_pico:
        # Só som (grito, susto, explosão no jogo): uma janela curta em volta do pico, sem cortar fala
        ini, fim = t - .7, t + 1.2
        for p in palavras:
            if float(p["ini"]) < ini < float(p["fim"]) or float(p["ini"]) < fim < float(p["fim"]):
                return None
        return _fechar(ini, fim, duracao)
    k = min(perto_do_pico, key=lambda n: abs((float(palavras[n]["ini"]) + float(palavras[n]["fim"])) / 2 - t))
    i = j = k
    while not _comeca_frase(palavras, i) and float(palavras[j]["fim"]) - float(palavras[i - 1]["ini"]) <= DURACAO[2]:
        i -= 1
    while not _termina_frase(palavras, j) and float(palavras[j + 1]["fim"]) - float(palavras[i]["ini"]) <= DURACAO[2]:
        j += 1
    trecho = palavras[i:j + 1]
    if not (_comeca_frase(palavras, i) and _termina_frase(palavras, j)):
        return None  # a frase não cabe inteira em 3 segundos: sem prévia
    if len(trecho) > MAX_PALAVRAS:
        return None
    if not any(_reacao(p) for p in trecho) and len(trecho) > 3:
        return None  # conversa comum, sem reação: não prende ninguém
    if ctx._nucleo(trecho[-1]["p"]) in ctx.CONECTIVOS:
        return None  # termina em "e", "que", "mas": fica pela metade
    ini, fim = float(trecho[0]["ini"]) - .12, float(trecho[-1]["fim"]) + .25
    if fim - ini < DURACAO[0]:  # reação curta: deixa um respiro do som em volta, sem pegar outra fala
        antes = float(palavras[i - 1]["fim"]) + .05 if i > 0 else 0.0
        depois = float(palavras[j + 1]["ini"]) - .05 if j + 1 < len(palavras) else duracao
        falta = DURACAO[0] + .1 - (fim - ini)
        ini, fim = max(antes, ini - falta / 2), min(depois, fim + falta / 2)
    if ini < SEM_PREVIA_ANTES:
        return None
    return _fechar(ini, fim, duracao)


def _fechar(ini: float, fim: float, duracao: float) -> list[float] | None:
    fim = min(fim, duracao - .5, ini + DURACAO[2])
    if fim - ini < DURACAO[0] - .02 or ini < SEM_PREVIA_ANTES:
        return None
    return [round(max(0.0, ini), 3), round(fim, 3)]


def descrever(abertura: list[float]) -> str:
    a, b = abertura
    return f"Gancho de abertura: começa com o auge ({int(a // 60)}:{int(a % 60):02d}, {b - a:.1f} s) e volta para o começo da história".replace(".", ",", 1)
