"""Melhora sozinho os cortes com potencial baixo, antes de montar o vídeo.

O potencial é calculado com a fala e com o tempo do corte, então dá para testar várias versões em
menos de um segundo e montar só a melhor:
- outros começos e fins para a história (mais curta, mais preparação, desfecho mais longo);
- sem as pausas longas no meio da fala (o trecho em volta do momento nunca é cortado: ali o jogo fala sozinho);
- o título refeito para cada versão.
O que não dá para mudar é a força da reação da live: um momento morno continua morno.
"""
from __future__ import annotations

from . import contexto as ctx
from . import potencial

PAUSA_MINIMA = 1.1    # silêncio mais longo que isto no meio da fala pode sair
FOLGA = .25           # fica um pouco de silêncio antes e depois de cada fala
PROTEGIDO = (4.0, 3.0)  # segundos antes e depois do momento que nunca são cortados
GANHO_MINIMO = 3      # só troca o corte se a nota subir pelo menos isto


def cortes_sem_pausas(palavras: list[dict], duracao: float, momento: float | None) -> list[list[float]]:
    """Pedaços que ficam no vídeo, tirando os silêncios longos entre as falas."""
    if len(palavras) < 2:
        return [[0.0, round(duracao, 3)]]
    lista = sorted(palavras, key=lambda p: float(p["ini"]))
    cortes, inicio = [], 0.0
    for a, b in zip(lista, lista[1:]):
        fim_a, ini_b = float(a["fim"]), float(b["ini"])
        if ini_b - fim_a < PAUSA_MINIMA:
            continue
        x, y = fim_a + FOLGA, ini_b - FOLGA
        if momento is not None and x < momento + PROTEGIDO[1] and y > momento - PROTEGIDO[0]:
            continue
        if x - inicio > .3:
            cortes.append([round(inicio, 3), round(x, 3)])
        inicio = y
    cortes.append([round(inicio, 3), round(duracao, 3)])
    tirado = duracao - sum(b - a for a, b in cortes)
    if tirado > duracao / 3 or tirado < .8:  # corta pouco demais para valer, ou demais e perde a naturalidade
        return [[0.0, round(duracao, 3)]]
    return cortes


def _versao(palavras: list[dict], ini: float, fim: float, momento_chat: float, titulo: str, meta: dict, aprendizado, sem_pausas: bool, manter_titulo: bool = False) -> dict:
    duracao = fim - ini
    trecho = [{"p": p["p"], "ini": round(max(0.0, p["ini"] - ini), 3), "fim": round(min(duracao, p["fim"] - ini), 3)}
              for p in palavras if p["fim"] > ini + .05 and p["ini"] < fim - .05]
    momento_fonte = round(min(max(0.0, momento_chat - ini - 4), max(0.0, duracao - 1)), 2)
    grupos = ctx.agrupar_legenda(trecho)
    cortes = cortes_sem_pausas(trecho, duracao, momento_fonte) if sem_pausas else [[0.0, round(duracao, 3)]]
    gancho = (meta.get("gancho") or "") if manter_titulo else ctx.criar_gancho(trecho, momento_chat - ini, titulo, meta.get("reacao") or "")
    prova = {**meta, "grupos": grupos, "duracao": round(duracao, 2), "duracao_fonte": round(duracao, 3), "momento_fonte": momento_fonte,
             "gancho": gancho, "edicao": {"cortes": cortes}}
    nota = potencial.calcular(prova, aprendizado)
    return {"ini": round(ini, 3), "fim": round(fim, 3), "cortes": cortes, "nota": nota["nota"], "gancho": gancho, "potencial": nota}


def melhor_versao(palavras: list[dict], momento_chat: float, disponivel: float, minimo: float, maximo: float,
                  atual: tuple[float, float], titulo: str, meta: dict, aprendizado=None, limiar: int = 75, manter_titulo: bool = False) -> dict:
    """Testa outras versões do corte e devolve a melhor, com o que mudou. `atual` é a janela já escolhida."""
    base = _versao(palavras, *atual, momento_chat, titulo, meta, aprendizado, False, manter_titulo)
    resultado = {"antes": base["nota"], "depois": base["nota"], "escolhida": base, "mudancas": []}
    if base["nota"] >= limiar:
        return resultado
    janelas = {tuple(round(x, 2) for x in atual)}
    variacoes = [(minimo, maximo, 3.0, 3.0), (15, 35, 3.0, 3.0), (18, 45, 6.0, 3.0), (max(15, minimo - 5), maximo, 6.0, 5.0),
                 (minimo, min(maximo, 45), 4.0, 5.0), (20, maximo, 8.0, 4.0), (15, 30, 2.0, 3.0)]
    for mn, mx, prep, desf in variacoes:
        mn = max(mn, min(minimo, 18))  # respeita a duração mínima escolhida, sem passar de 18 s
        mn, mx = min(mn, mx - 5), max(mx, mn + 5)
        try:
            janelas.add(tuple(round(x, 2) for x in ctx.escolher_janela(palavras, momento_chat, disponivel, mn, mx, preparo=prep, desfecho=desf)))
        except Exception:
            continue
    # Começar uma frase depois: tira "e aí", "então"... do começo, sem perder a preparação do momento
    evento = momento_chat - 6
    for f in ctx.frases(palavras):
        s = float(f["ini"]) - .15
        if atual[0] < s <= atual[0] + 8 and s < evento - 3 and atual[1] - s >= 12:
            janelas.add((round(s, 2), round(atual[1], 2)))
    melhor = base
    for ini, fim in janelas:
        for sem_pausas in (False, True):
            v = _versao(palavras, ini, fim, momento_chat, titulo, meta, aprendizado, sem_pausas, manter_titulo)
            if v["nota"] > melhor["nota"]:
                melhor = v
    if melhor["nota"] - base["nota"] < GANHO_MINIMO:
        return resultado
    mudancas = []
    if (melhor["ini"], melhor["fim"]) != (round(atual[0], 3), round(atual[1], 3)):
        antes, depois = atual[1] - atual[0], melhor["fim"] - melhor["ini"]
        mudancas.append(f"começo e fim refeitos ({round(antes)} s → {round(depois)} s)")
    if len(melhor["cortes"]) > 1:
        tirado = (melhor["fim"] - melhor["ini"]) - sum(b - a for a, b in melhor["cortes"])
        mudancas.append(f"{len(melhor['cortes']) - 1} {'pausa cortada' if len(melhor['cortes']) == 2 else 'pausas cortadas'} ({tirado:.1f} s)".replace(".", ","))
    if melhor["gancho"] != base["gancho"]:
        mudancas.append("título novo")
    return {"antes": base["nota"], "depois": melhor["nota"], "escolhida": melhor, "mudancas": mudancas}
