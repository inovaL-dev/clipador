"""Potencial de viralizar: uma nota de 0 a 100 para cada corte, com o motivo de cada parte.

É uma estimativa feita com o que o Clipador sabe do corte, não uma promessa de views:
- a força da reação na live (chat, voz, rosto e jogo), comparada com o normal da própria live;
- o gancho: o que acontece nos 3 primeiros segundos, quando quem rola o feed decide se fica;
- a história: começa no começo do assunto, tem preparação antes do momento e desfecho depois;
- o ritmo: quanto do vídeo tem fala e se há silêncios longos;
- a emoção na fala e a duração;
- quando o YouTube está conectado, o que já funcionou no próprio canal (tipo de reação e duração).
"""
from __future__ import annotations

import re

from . import contexto as ctx
from . import timeline as tl

REACOES_FORTES = {"risada": 6, "choque": 6, "hype": 5, "clipe": 6, "admirado": 5, "streamer": 4, "jogo": 3, "destaque": 2, "manual": 2}
GANCHO_BOM = re.compile(r"\b(olha|você|voce|nunca|ninguém|ninguem|primeira vez|não acredito|nao acredito|segredo|verdade|imagina|sabia|cuidado|meu deus|caraca|caramba)\b", re.I)


def _palavras(meta: dict) -> list[dict]:
    return sorted((p for g in meta.get("grupos") or [] for p in g.get("palavras") or []), key=lambda p: float(p["ini"]))


def _faixa(v: float, a: float, b: float) -> float:
    return max(a, min(b, v))


def calcular(meta: dict, aprendizado=None) -> dict:
    """Devolve {"nota", "nivel", "partes": [{"nome", "pontos", "maximo", "texto"}], "dicas": [...]}."""
    palavras = _palavras(meta)
    duracao = float(meta.get("duracao_fonte") or meta.get("duracao") or 0) or (float(palavras[-1]["fim"]) if palavras else 0.0)
    momento = meta.get("momento_fonte")
    cortes = (meta.get("edicao") or {}).get("cortes")
    if cortes and (len(cortes) > 1 or cortes[0][0] > .01 or cortes[0][1] < duracao - .01):  # o vídeo final tem pedaços cortados
        palavras = [p for g in tl.mapear_grupos(meta.get("grupos") or [], cortes) for p in g["palavras"]]
        duracao = tl.duracao_total(cortes)
        if momento is not None:
            momento = tl.proxima_saida(float(momento), cortes)
    partes, dicas = [], []

    # 1. Reação na live (até 30)
    forca = float(meta.get("forca") or 0)
    tipo = meta.get("reacao") or "destaque"
    pontos = _faixa(forca * .26, 0, 26) + min(4, REACOES_FORTES.get(tipo, 2) * .7)
    texto = "O chat e o streamer reagiram muito acima do normal da live." if forca >= 70 else \
        "Reação clara, acima do normal da live." if forca >= 45 else "Reação fraca: foi um corte de intervalo ou um momento morno."
    partes.append({"nome": "Reação", "pontos": round(pontos), "maximo": 30, "texto": texto})

    # 2. Gancho nos 3 primeiros segundos (até 20)
    previa = meta.get("abertura") if meta.get("previa_usada") else None
    if previa:  # o vídeo abre com o auge: os primeiros segundos são a prévia
        inicio = [p for p in _palavras(meta) if previa[0] <= float(p["ini"]) < previa[1]]
    else:
        inicio = [p for p in palavras if float(p["ini"]) < 3.0]
    frase0 = " ".join(p["p"] for p in inicio)
    pontos = 0.0
    if len(inicio) >= 3:
        pontos += 7
    elif inicio:
        pontos += 3
    else:
        dicas.append("Os 3 primeiros segundos não têm fala. Comece mais perto do momento ou ponha um título forte no começo.")
    if GANCHO_BOM.search(frase0) or ctx.FORTES.search(frase0):
        pontos += 6
    if re.search(r"[?!]", frase0):
        pontos += 3
    if previa:
        pontos += 4
    if inicio and not previa and ctx._nucleo(inicio[0]["p"]) in ctx.CONECTIVOS:
        pontos -= 5
        dicas.append(f"O vídeo abre com “{inicio[0]['p']}”, que soa como continuação. Comece uma frase depois.")
    gancho = (meta.get("gancho") or "").strip()
    if gancho and len(gancho) <= ctx.LIMITE_GANCHO:
        pontos += 4
    elif not gancho:
        dicas.append("Sem título no vídeo: um título curto nos primeiros segundos segura quem chegou agora.")
    pontos = _faixa(pontos, 0, 20)
    partes.append({"nome": "Gancho", "pontos": round(pontos), "maximo": 20,
                   "texto": "Abre com o auge e volta para o começo da história." if previa and pontos >= 12 else "Começa com fala forte e título." if pontos >= 15 else "O começo podia prender mais." if pontos >= 8 else "O começo é fraco para quem está rolando o feed."})

    # 3. História completa (até 20)
    lista = ctx.frases(palavras)
    pontos = 0.0
    if lista:
        primeira = [ctx._nucleo(p) for p in lista[0]["texto"].split()[:3]]
        solta = primeira and (primeira[0] in ctx.CONECTIVOS or (not GANCHO_BOM.match(lista[0]["texto"]) and any(p in ctx.ANAFORAS for p in primeira[:2])))
        if primeira and not solta:
            pontos += 6
        else:
            dicas.append("A primeira frase depende do que foi dito antes. Volte o começo uma frase no editor.")
        if lista[-1]["texto"].rstrip()[-1:] in ".!?":
            pontos += 6
        else:
            dicas.append("O vídeo termina no meio de uma frase. Estique o fim até a frase acabar.")
        if momento is not None:
            prep = float(momento) - float(lista[0]["ini"])
            desf = float(lista[-1]["fim"]) - float(momento)
            pontos += 4 if prep >= 6 else 2 if prep >= 3 else 0
            pontos += 4 if desf >= 2 else 1 if desf >= 0 else 0
            if prep < 3:
                dicas.append("Pouca preparação antes do momento: quem não viu a live pode não entender o que aconteceu.")
        else:
            pontos += 4
    else:
        pontos = 8  # momento de jogo sem fala: a imagem conta a história
    partes.append({"nome": "História", "pontos": round(pontos), "maximo": 20,
                   "texto": "Tem começo, meio e fim." if pontos >= 16 else "A história está quase completa." if pontos >= 10 else "Falta contexto ou desfecho."})

    # 4. Ritmo (até 15)
    if palavras and duracao > 0:
        fala = sum(max(0.0, float(p["fim"]) - float(p["ini"])) for p in palavras) / duracao
        buracos = [(float(b["ini"]) - float(a["fim"]), float(a["fim"])) for a, b in zip(palavras, palavras[1:])]
        maior, onde = max(buracos, default=(0.0, 0.0))
        pontos = _faixa(fala / .55 * 12, 0, 12) + (3 if maior < 2.0 else 1 if maior < 3.5 else 0)
        if maior >= 2.5:
            dicas.append(f"Silêncio de {maior:.1f} s em {int(onde // 60)}:{int(onde % 60):02d}. Corte a pausa no editor (IA > Cortar pausas).".replace(".", ",", 1))
        texto = "Fala do começo ao fim, sem buracos." if pontos >= 12 else "Algumas pausas deixam o ritmo mais lento." if pontos >= 7 else "Muito tempo sem fala."
    else:
        pontos, texto = 6, "Momento sem fala: o ritmo depende da ação na tela."
    partes.append({"nome": "Ritmo", "pontos": round(pontos), "maximo": 15, "texto": texto})

    # 5. Emoção na fala (até 10)
    todo = " ".join(p["p"] for p in palavras)
    fortes = len(ctx.FORTES.findall(todo))
    gritos = todo.count("!")
    pontos = _faixa(fortes * 2.5 + gritos * 1.5 + (3 if tipo in ("risada", "choque") else 0), 0, 10)
    partes.append({"nome": "Emoção", "pontos": round(pontos), "maximo": 10,
                   "texto": "Muita emoção na voz e nas palavras." if pontos >= 7 else "Alguma emoção." if pontos >= 3 else "Fala calma, pouca emoção."})

    # 6. Duração (até 5)
    d = float(duracao if cortes else (meta.get("duracao_fonte") or meta.get("duracao") or duracao)) + ((previa[1] - previa[0]) if previa else 0)
    pontos = 5 if 15 <= d <= 45 else 3 if 12 <= d <= 59 else 1
    if d > 59:
        dicas.append("Passa de 59 segundos: o YouTube pode não tratar como Short.")
    partes.append({"nome": "Duração", "pontos": pontos, "maximo": 5, "texto": f"{int(d)} s" + (" (ideal para Shorts)" if pontos == 5 else "")})

    nota = sum(p["pontos"] for p in partes)

    # O que o canal já mostrou: tipos de reação e durações que deram mais views que a média
    canal = None
    if aprendizado is not None:
        try:
            peso = float(aprendizado.peso(tipo))
            des = (aprendizado.m.get("desempenho") or {})
            faixa_d = "até 30 s" if d <= 30 else "30 a 45 s" if d <= 45 else "mais de 45 s"
            dur = (des.get("duracoes") or {}).get(faixa_d)
            fator_d = (dur["media"] / des["media"]) if dur and dur.get("n", 0) >= 3 and des.get("media") else 1.0
            ajuste = round(_faixa((peso - 1) * 25 + (min(1.3, max(.7, fator_d)) - 1) * 15, -10, 10))
            if ajuste:
                nota += ajuste
                canal = {"nome": "No seu canal", "pontos": ajuste, "maximo": 10,
                         "texto": ("Cortes assim costumam ter mais views que a média do seu canal." if ajuste > 0 else "Cortes assim costumam ter menos views que a média do seu canal.")}
        except (AttributeError, KeyError, TypeError, ZeroDivisionError):
            canal = None
    if canal:
        partes.append(canal)
    nota = int(_faixa(round(nota), 1, 99))
    nivel = "alto" if nota >= 75 else "medio" if nota >= 55 else "baixo"
    return {"nota": nota, "nivel": nivel, "partes": partes, "dicas": dicas[:4]}


def de_montagem(meta: dict, cortes: dict) -> dict | None:
    """Montagem: a média das cenas, com um bônus pelo ritmo de troca de cenas."""
    notas = [c["potencial"]["nota"] for i in meta.get("origens") or [] if (c := cortes.get(i)) and c.get("potencial")]
    if not notas:
        return None
    nota = int(_faixa(round(sum(notas) / len(notas) + 4), 1, 99))
    return {"nota": nota, "nivel": "alto" if nota >= 75 else "medio" if nota >= 55 else "baixo",
            "partes": [{"nome": "Cenas", "pontos": nota, "maximo": 100, "texto": f"Média das {len(notas)} cenas, com bônus pelo ritmo das trocas."}], "dicas": []}
