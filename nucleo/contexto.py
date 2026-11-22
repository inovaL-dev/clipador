"""Escolhe onde o corte começa e termina, cria o título e organiza a legenda."""
from __future__ import annotations

import re

CONECTIVOS = {
    "e", "mas", "aí", "ai", "então", "entao", "porque", "que", "daí", "dai", "tipo", "né", "ne",
    "ou", "pois", "porém", "também", "tambem", "só", "so", "isso", "ele", "ela",
}
FRACAS = {
    "de", "do", "da", "dos", "das", "o", "a", "os", "as", "um", "uma", "e", "que", "pra", "para",
    "no", "na", "nos", "nas", "em", "com", "por", "se", "ao", "à", "meu", "minha", "seu", "sua",
}
FORTES = re.compile(
    r"\b(nunca|não acredito|absurdo|insano|meu deus|caramba|caraca|ganhei|perdi|ganhou|perdeu|"
    r"acabou|mentira|olha|socorro|impossível|maluco|louco|doido|primeira vez)\b", re.I,
)
GANCHOS_REACAO = {
    "risada": "O chat não aguentou de tanto rir",
    "clipe": "O chat pediu pra clipar isso",
    "choque": "Ninguém esperava por isso",
    "hype": "O chat foi à loucura com isso",
    "manual": "Olha o que aconteceu na live",
    "destaque": "O melhor momento da live",
    "streamer": "Olha essa reação na live",
    "admirado": "Ele ficou sem palavras com isso",
    "jogo": "Olha o que aconteceu no jogo",
}
LIMITE_GANCHO = 58
LIMITE_GRUPO = 30


def _nucleo(palavra: str) -> str:
    return re.sub(r"^\W+|\W+$", "", palavra).casefold()


def frases(palavras: list[dict]) -> list[dict]:
    lista: list[dict] = []
    atual: list[dict] = []

    def fechar():
        if atual:
            lista.append({
                "ini": atual[0]["ini"], "fim": atual[-1]["fim"],
                "texto": " ".join(p["p"] for p in atual),
                "terminal": atual[-1]["p"][-1] in ".!?",
                "pausa": atual[0]["ini"] - lista[-1]["fim"] if lista else 9.0,
            })
            atual.clear()

    for p in (x for x in palavras if x["p"].strip()):
        if atual and p["ini"] - atual[-1]["fim"] >= 0.7:
            fechar()
        atual.append(p)
        longo = p["fim"] - atual[0]["ini"] > 12 and p["p"][-1] == ","
        if p["p"][-1] in ".!?" or longo:
            fechar()
    fechar()
    return lista


ANAFORAS = {"isso", "esse", "essa", "esses", "essas", "aquilo", "aquele", "aquela", "ele", "ela", "eles", "elas", "dele", "dela", "nele", "nela", "lá", "disso", "nisso"}
ABERTURAS = {"olha", "mano", "gente", "cara", "galera", "pessoal", "agora", "vamos", "bora", "sabe", "quando", "imagina", "hoje", "primeiro", "deixa", "vou", "quem", "qual", "como", "por"}
VAZIAS = FRACAS | CONECTIVOS | ANAFORAS | {"não", "nao", "sim", "muito", "mais", "tem", "tá", "ta", "foi", "era", "vai", "vou", "aqui", "agora", "como", "quando", "onde", "você", "voce", "eu", "nós", "nos", "gente", "mano", "cara", "assim", "está", "esta", "ser", "ter", "fazer"}


def _radicais(textos: list[str]) -> set[str]:
    """Palavras que indicam o assunto, sem contar as que aparecem em qualquer conversa."""
    saida = set()
    for texto in textos:
        for p in texto.split():
            n = _nucleo(p)
            if len(n) >= 4 and n not in VAZIAS:
                saida.add(n[:5])
    return saida


def _coesao(lista: list[dict], i: int) -> float:
    """De 0 a 1: quanto a frase `i` continua falando do mesmo assunto das anteriores."""
    antes, depois = _radicais([f["texto"] for f in lista[max(0, i - 3):i]]), _radicais([f["texto"] for f in lista[i:i + 2]])
    return len(antes & depois) / min(len(antes), len(depois)) if antes and depois else 0.0


def _nota_inicio(lista: list[dict], i: int) -> float:
    """Quanto esta frase funciona como começo para quem não viu nada antes."""
    f = lista[i]
    palavras = [_nucleo(p) for p in f["texto"].split()]
    if i == 0:
        return -4.0 if f["ini"] < 0.8 else 1.5  # a primeira frase pode ter sido gravada pela metade
    ant = lista[i - 1]["texto"].rstrip()
    nota = min(f["pausa"], 3.0)
    if ant[-1:] == "?":
        nota -= 3.0  # esta frase responde a pergunta anterior
    elif ant[-1:] in ".!":
        nota += 1.0
    elif f["pausa"] < 0.7:
        nota -= 3.0  # a pessoa ainda estava no meio da frase
    if palavras[0] in CONECTIVOS:
        nota -= 3.0
    if any(p in ANAFORAS for p in palavras[:3]):
        nota -= 1.5
    if palavras[0] in ABERTURAS:
        nota += 1.0
    coesao = _coesao(lista, i)
    return nota + (1.0 if coesao == 0 else -2.5 * coesao)


def _nota_fim(lista: list[dict], i: int, disponivel: float) -> float:
    """Quanto esta frase fecha bem o assunto."""
    f = lista[i]
    texto = f["texto"].rstrip()
    ultima = _nucleo(texto.split()[-1])
    prox = lista[i + 1] if i + 1 < len(lista) else None
    nota = 2.0 if texto[-1:] in ".!" else 0.0
    if ultima in FRACAS or ultima in CONECTIVOS or texto[-1:] in ",;:":
        nota -= 3.5
    if prox is None:
        return nota - (3.0 if f["fim"] >= disponivel - 0.6 else 0.0)
    if texto[-1:] == "?" and prox["pausa"] < 2.5:
        nota -= 3.0  # não termina em uma pergunta com a resposta logo depois
    nota += min(prox["pausa"], 2.0)
    if prox["pausa"] < 1.0 and _nucleo(prox["texto"].split()[0]) in CONECTIVOS:
        nota -= 3.0
    return nota - 1.5 * _coesao(lista, i + 1)


MUDA_ASSUNTO = re.compile(r"^(enfim|bom|beleza|bora|pessoal|galera|chat|voltando|mudando|ok|tá bom|ta bom|então tá|entao ta|agora vamos|agora bora|outra coisa|deixa eu|vamos lá|vamos la)\b", re.I)
FECHA_ASSUNTO = re.compile(r"\b(mudando de assunto|voltando (pro|para o|ao) jogo|enfim|bora jogar|vamos jogar|bora lá|bora la)\b", re.I)


def _fronteira(lista: list[dict], m: int) -> float:
    """Quanto entre a frase `m - 1` e a `m` existe uma troca de assunto (0 = mesma conversa, 1 ou mais = assunto novo)."""
    if m <= 0 or m >= len(lista):
        return 2.0
    f, ant = lista[m], lista[m - 1]
    texto = f["texto"].strip()
    palavras = [_nucleo(p) for p in texto.split()]
    nota = max(0.0, min(1.0, (f["pausa"] - .6) / 1.6))  # uma pausa longa costuma separar assuntos
    if MUDA_ASSUNTO.search(texto):
        nota += .8
    if FECHA_ASSUNTO.search(ant["texto"]):
        nota += 1.0  # a frase de antes anunciou a troca ("mudando de assunto", "enfim")
    if palavras and palavras[0] in CONECTIVOS:
        nota -= .5  # "e", "mas", "aí", "porque": continua a frase de antes
    if any(p in ANAFORAS for p in palavras[:3]):
        nota -= .35  # "isso", "ele", "lá": aponta para algo dito antes
    if ant["texto"].rstrip()[-1:] == "?":
        nota -= .6  # é a resposta da pergunta anterior
    if not ant["terminal"] and f["pausa"] < 1.0:
        nota -= .4
    return nota - .8 * _coesao(lista, m)


def _raciocinio(lista: list[dict], k: int, limite: float) -> tuple[int, int]:
    """Começo e fim do assunto que contém a frase `k`: a história inteira em volta do momento."""
    ini = k
    while ini > 0 and _fronteira(lista, ini) < .9 and lista[k]["fim"] - lista[ini - 1]["ini"] <= limite:
        ini -= 1
    fim = k
    while fim + 1 < len(lista) and _fronteira(lista, fim + 1) < .9 and lista[fim + 1]["fim"] - lista[ini]["ini"] <= limite:
        fim += 1
    return ini, fim


def escolher_janela(palavras: list[dict], momento: float, disponivel: float, minimo: float = 25, maximo: float = 60,
                    atraso: float = 6.0, preparo: float = 3.0, desfecho: float = 3.0, teto_depois: float = 28.0) -> tuple[float, float]:
    """Procura o começo e o fim que contam uma história inteira.

    O corte precisa ter a preparação (quem assiste entende o que está acontecendo), o momento em si e o desfecho
    (a reação termina e a ideia fecha). Nunca começa no meio de um raciocínio nem termina no meio da explicação.
    `momento` é quando o chat reagiu; o acontecimento vem `atraso` segundos antes."""
    lista = frases(palavras)
    evento = momento - atraso
    alvo = minimo + (maximo - minimo) * 0.45
    teto = min(momento + teto_depois, disponivel)
    fins = [(j, f) for j, f in enumerate(lista) if evento + max(desfecho, 4.0) <= f["fim"] <= teto]  # o desfecho vem depois do acontecimento
    inicios = [(i, f, _nota_inicio(lista, i)) for i, f in enumerate(lista) if f["ini"] <= evento - preparo]
    melhor, nota_melhor = None, -1e9
    if lista and fins and inicios:
        k = max((n for n, f in enumerate(lista) if f["ini"] <= max(evento, lista[0]["ini"])), default=0)
        comeco, final = _raciocinio(lista, k, maximo - 2)
        corte = [min(1.0, max(0.0, _fronteira(lista, n))) for n in range(len(lista) + 1)]
        notas_fim = {j: _nota_fim(lista, j, disponivel) for j, _ in fins}
        piso = max(15.0, minimo * .6)  # uma história completa vale mais que segundos a mais de outro assunto
        for j, b in fins:
            nota_b = notas_fim[j] - max(0.0, momento - b["fim"]) * .1
            if j < final:
                nota_b -= 2.0 + 1.5 * (1 - corte[j + 1])  # cortaria antes da ideia terminar
            elif j == final:
                nota_b += 2.0
            else:
                nota_b -= 1.5 + (b["fim"] - lista[final]["fim"]) / 6  # já entrou em outro assunto
            for i, a, nota_a in inicios:
                duracao = b["fim"] - a["ini"]
                if not (piso <= duracao <= maximo and i <= j):
                    continue
                nota = nota_a + nota_b - abs(duracao - alvo) / 22 - max(0.0, minimo - duracao) * .12
                if i > comeco:
                    nota -= 1.5 + 1.5 * (1 - corte[i])  # começaria no meio do raciocínio
                elif i == comeco:
                    nota += 2.5
                else:
                    nota -= 1.0 + (lista[comeco]["ini"] - a["ini"]) / 10  # sobra de outro assunto no começo
                prep = evento - a["ini"]
                if prep < 8:
                    nota -= (8 - prep) * .45  # pouca preparação: quem chega agora não entende
                if nota > nota_melhor:
                    melhor, nota_melhor = (i, j), nota
    if melhor:
        i, j = melhor
    else:
        # Pouca fala ou live recém-iniciada: usa o que existe, sem cortar uma frase ao meio.
        j = max(fins, key=lambda x: _nota_fim(lista, x[0], disponivel))[0] if fins else None
        fim = lista[j]["fim"] if j is not None else min(momento + 10, disponivel)
        inicio = max(0.0, fim - alvo)
        dentro = [k for k, f in enumerate(lista) if f["fim"] >= inicio and fim - f["ini"] <= maximo]
        if not dentro:
            return inicio, min(disponivel, fim + 0.4)
        i = dentro[0]
        if j is None:
            return max(0.0, lista[i]["ini"] - 0.2), min(disponivel, fim + 0.4)
    ini = lista[i]["ini"] - 0.2 if i == 0 else max(lista[i - 1]["fim"] + 0.02, lista[i]["ini"] - 0.2)
    fim = lista[j]["fim"] + 0.5 if j + 1 == len(lista) else min(lista[j]["fim"] + 0.5, lista[j + 1]["ini"] - 0.03)
    return max(0.0, ini), min(disponivel, fim)


def inicio_com_sentido(palavras: list[dict], de: float, ate: float) -> float | None:
    """O melhor começo de frase entre `de` e `ate`: de preferência onde um assunto novo abre."""
    lista = frases(palavras)
    opcoes = [(n, f) for n, f in enumerate(lista) if de <= f["ini"] <= ate]
    if not opcoes:
        return None
    n, f = max(opcoes, key=lambda x: min(1.5, _fronteira(lista, x[0])) + _nota_inicio(lista, x[0]) * .3 - (x[1]["ini"] - de) / 20)
    return max(de, f["ini"] - .15)


def trecho_de_cena(grupos: list[dict], momento: float, total: float, minimo: float = 9.0, maximo: float = 18.0) -> tuple[float, float]:
    """O trecho de um corte que entra numa montagem: curto, mas com começo, meio e fim.

    `momento` já é o instante do acontecimento dentro do corte."""
    palavras = [p for g in grupos for p in g.get("palavras") or []]
    if not palavras:
        ini = max(0.0, momento - minimo * .55)
        return round(ini, 3), round(min(total, ini + minimo), 3)
    ini, fim = escolher_janela(palavras, momento, total, minimo, maximo, atraso=0.0, preparo=2.0, desfecho=1.5, teto_depois=min(10.0, maximo * .6))
    return round(ini, 3), round(fim, 3)


def ajustar_a_frases(palavras: list[dict], ini: float, fim: float, limite_ini: float, limite_fim: float) -> tuple[float, float]:
    """Leva as pontas de um trecho para o começo e o fim das frases mais próximas."""
    lista = frases(palavras)
    for f in lista:
        if f["ini"] < ini < f["fim"]:
            ini = f["ini"] if f["ini"] >= limite_ini else ini
            break
    for f in lista:
        if f["ini"] < fim < f["fim"] and f["fim"] <= limite_fim:
            fim = f["fim"] + 0.15
            break
    return max(limite_ini, ini - 0.1), min(limite_fim, fim)


def _encurtar(texto: str, limite: int = LIMITE_GANCHO) -> str:
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) > limite:
        texto = texto[:limite].rsplit(" ", 1)[0]
        while texto.split() and _nucleo(texto.split()[-1]) in FRACAS:
            texto = texto.rsplit(" ", 1)[0] if " " in texto else ""
    return texto.rstrip(" ,;:-.")


def criar_gancho(palavras: list[dict], momento: float, titulo_live: str, reacao: str) -> str:
    melhor, nota_melhor = "", 1.0
    for f in frases(palavras):
        tamanho = len(f["texto"])
        if tamanho < 14:
            continue
        nota = 3.0 - abs((f["ini"] + f["fim"]) / 2 - (momento - 4)) / 8
        nota += 1.5 if f["texto"][-1] in "!?" else 0
        nota += 2.0 if FORTES.search(f["texto"]) else 0
        nota += 1.0 if tamanho <= LIMITE_GANCHO else -1.0
        nota -= 1.5 if _nucleo(f["texto"].split()[0]) in CONECTIVOS else 0
        if nota > nota_melhor:
            melhor, nota_melhor = f["texto"], nota
    if melhor:
        texto = _encurtar(melhor)
        pontuacao = melhor[-1] if melhor[-1] in "!?" and len(melhor) <= LIMITE_GANCHO else ""
        return texto[:1].upper() + texto[1:] + pontuacao
    return GANCHOS_REACAO.get(reacao) or _encurtar(titulo_live) or GANCHOS_REACAO["manual"]


# ---------- Título que cria curiosidade ----------
# Em vez de repetir uma frase da fala, o título conta que algo aconteceu sem dizer o quê. Cada tipo de
# acontecimento ganha pontos pelas palavras que aparecem perto do momento (quanto mais perto, mais vale);
# o tipo com mais pontos escolhe o título. Sem pontos suficientes, fica o título tirado da fala.
_CURIOSIDADE = {
    "desafio": (re.compile(r"\b(duvido|aposto|apostar|chuta|adivinha|quem acerta|voc[eê]s acham)\b", re.I),
                ["Quem acertar o final ganha", "Duvido você adivinhar o que vem", "Ninguém acertou o que veio depois"]),
    "dinheiro": (re.compile(r"\b(\d+[.,]?\d*)\s*(mil|milh\w+|bilh\w+|k)\b|\b(reais|conto|pila|grana|dinheiro)\b", re.I),
                 ["Olha o valor que ele falou", "Ninguém esperava esse valor", "O valor desse momento é absurdo"]),
    "raro": (re.compile(r"\b(nunca vi|nunca aconteceu|primeira vez|rar[ií]ssim\w*|lend[aá]ri\w*|m[ií]tic\w*|imposs[ií]vel)\b", re.I),
             ["Ninguém tinha visto isso na live", "Isso nunca tinha acontecido", "Um dos momentos mais raros da live"]),
    "tragedia": (re.compile(r"\b(perdi|perdeu|deu ruim|se ferrou|morri|morreu|quebrou|errei|vacilei|acabou tudo)\b", re.I),
                 ["O final desse lance foi trágico", "Era pra dar certo, mas olha", "Ele não esperava esse final"]),
    "virada": (re.compile(r"\b(consegui|ganhei|ganhamos|venci|virou|virada|finalmente|deu certo|passei)\b", re.I),
               ["Ele finalmente conseguiu", "Espera pra ver a virada", "Ninguém achou que ia dar certo"]),
}


def gancho_promessa(palavras: list[dict], momento: float) -> str | None:
    """Título que cria curiosidade a partir do que acontece perto do momento. None quando não tem material."""
    pontos: dict[str, float] = {}
    for p in palavras:
        distancia = abs(float(p["ini"]) - momento)
        if distancia > 20:
            continue
        peso = 1.0 if distancia <= 6 else .5
        for tipo, (regra, _) in _CURIOSIDADE.items():
            if regra.search(p["p"]):
                pontos[tipo] = pontos.get(tipo, 0.0) + peso
    # expressões de duas palavras ("deu ruim", "nunca vi") só aparecem no texto corrido
    corrido = " ".join(p["p"] for p in palavras if abs(float(p["ini"]) - momento) <= 20)
    for tipo, (regra, _) in _CURIOSIDADE.items():
        pontos[tipo] = pontos.get(tipo, 0.0) + 1.0 * len([m for m in regra.finditer(corrido) if " " in m.group(0)])
    if not pontos or max(pontos.values()) < 1.0:
        return None
    tipo = max(pontos, key=pontos.get)
    opcoes = _CURIOSIDADE[tipo][1]
    return opcoes[int(momento * 10 + len(corrido)) % len(opcoes)]  # o mesmo corte dá sempre o mesmo título


def criar_post(gancho: str, canal: str, credito: str, titulo_live: str, plataforma: str, ident: str) -> str:
    contexto = f"Momento da live de {canal}"
    if titulo_live:
        contexto += f": {_encurtar(titulo_live, 90)}"
    marca = re.sub(r"[^0-9a-zA-Z]", "", canal or ident).lower()
    return f"{gancho}\n\n{contexto}.\nCréditos: {credito}\n\n#cortes #live #{plataforma} #{marca}\n"


def nucleo_da_acao(grupos: list[dict], momento: float, duracao: float, folga: float = 1.3, teto: float = 14.0) -> list[float]:
    """Trecho em que a coisa realmente acontece: a fala em volta do momento, sem as sobras."""
    ini, fim = max(0.0, momento - 1.5), min(duracao, momento + 4.0)
    blocos = sorted((float(g["ini"]), float(g["fim"])) for g in grupos)
    mudou = True
    while mudou:
        mudou = False
        for a, b in blocos:
            if b < ini and ini - b <= folga and fim - a <= teto:
                ini, mudou = a, True
            elif a > fim and a - fim <= folga and b - ini <= teto:
                fim, mudou = b, True
            elif a < ini <= b and fim - a <= teto:
                ini, mudou = a, True
            elif a <= fim < b and b - ini <= teto:
                fim, mudou = b, True
    if fim - ini < 5:
        fim = min(duracao, ini + 5)
        ini = max(0.0, fim - 5)
    return [round(ini, 2), round(fim, 2)]


def agrupar_legenda(palavras: list[dict]) -> list[dict]:
    """Forma blocos curtos que acompanham a fala e não terminam em palavra solta."""
    grupos: list[list[dict]] = []
    atual: list[dict] = []
    for p in palavras:
        tamanho = sum(len(x["p"]) + 1 for x in atual) + len(p["p"])
        if atual and (p["ini"] - atual[-1]["fim"] > 0.45 or len(atual) >= 5 or tamanho > LIMITE_GRUPO):
            grupos.append(atual)
            atual = []
        atual.append(p)
        if p["p"][-1] in ".!?" or (p["p"][-1] == "," and len(atual) >= 2):
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)

    for i in range(len(grupos) - 1):
        grupo, seguinte = grupos[i], grupos[i + 1]
        cabe = sum(len(x["p"]) + 1 for x in seguinte) + len(grupo[-1]["p"]) <= LIMITE_GRUPO
        junto = seguinte[0]["ini"] - grupo[-1]["fim"] <= 0.45
        if len(grupo) >= 2 and _nucleo(grupo[-1]["p"]) in FRACAS and cabe and junto and len(seguinte) < 5:
            seguinte.insert(0, grupo.pop())
    return [{"ini": g[0]["ini"], "fim": g[-1]["fim"], "palavras": g} for g in grupos if g]


def retextar(grupo: dict, texto: str) -> dict:
    """Aplica o texto corrigido à mão, redistribuindo o tempo entre as palavras."""
    novas = texto.split()
    antigas = grupo.get("palavras") or []
    if novas == [p["p"] for p in antigas]:
        return grupo
    if antigas:  # só o que mudou ganha tempo novo; as palavras que ficaram iguais mantêm o tempo certo da fala
        import difflib
        norma = lambda w: re.sub(r"[^\w]", "", w).casefold()
        saida = []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=[norma(p["p"]) for p in antigas], b=[norma(w) for w in novas], autojunk=False).get_opcodes():
            if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
                saida += [{**antigas[i], "p": novas[j]} for i, j in zip(range(i1, i2), range(j1, j2))]
            elif op in ("replace", "insert"):
                a = float(antigas[i1 - 1]["fim"]) if op == "insert" and i1 else float(antigas[min(i1, len(antigas) - 1)]["ini"]) if op == "replace" else float(grupo["ini"])
                b = float(antigas[i2 - 1]["fim"]) if op == "replace" else (float(antigas[i1]["ini"]) if i1 < len(antigas) else max(a + .2, float(grupo["fim"])))
                b = max(b, a + .12 * (j2 - j1))
                passo = (b - a) / (j2 - j1)
                saida += [{"p": novas[j], "ini": round(a + k * passo, 3), "fim": round(a + (k + 1) * passo, 3)} for k, j in enumerate(range(j1, j2))]
        if len(saida) == len(novas):
            saida.sort(key=lambda p: p["ini"])
            return {"ini": min(float(grupo["ini"]), saida[0]["ini"]), "fim": max(float(grupo["fim"]), saida[-1]["fim"]), "palavras": saida}
    ini, fim = float(grupo["ini"]), max(float(grupo["fim"]), float(grupo["ini"]) + 0.2)
    total = sum(len(p) + 1 for p in novas) or 1
    pos, saida = ini, []
    for p in novas:
        dur = (fim - ini) * (len(p) + 1) / total
        saida.append({"p": p, "ini": round(pos, 3), "fim": round(pos + dur, 3)})
        pos += dur
    return {"ini": ini, "fim": fim, "palavras": saida}


def quebrar_linhas(palavras: list[str], por_linha: int = 17) -> int | None:
    """Índice da quebra em duas linhas equilibradas, ou None se couber em uma."""
    if len(" ".join(palavras)) <= por_linha or len(palavras) < 2:
        return None
    melhor, diferenca = 1, 1e9
    for i in range(1, len(palavras)):
        a, b = len(" ".join(palavras[:i])), len(" ".join(palavras[i:]))
        d = abs(a - b) + (3 if _nucleo(palavras[i - 1]) in FRACAS else 0)
        if d < diferenca:
            melhor, diferenca = i, d
    return melhor
