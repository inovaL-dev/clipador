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


def escolher_janela(palavras: list[dict], momento: float, disponivel: float,
                    minimo: float = 25, maximo: float = 60) -> tuple[float, float]:
    """Procura o melhor par de começo e fim: o assunto abre, a reação acontece e a ideia termina."""
    lista = frases(palavras)
    evento = momento - 6  # o chat reage alguns segundos depois do acontecimento
    alvo = minimo + (maximo - minimo) * 0.45
    teto = min(momento + 28, disponivel)
    fins = [(j, f) for j, f in enumerate(lista) if momento + 3 <= f["fim"] <= teto]
    inicios = [(i, f, _nota_inicio(lista, i)) for i, f in enumerate(lista) if f["ini"] <= evento - 3]
    melhor, nota_melhor = None, -1e9
    for j, b in fins:
        nota_b = _nota_fim(lista, j, disponivel) - max(0.0, b["fim"] - momento - 12) / 10
        for i, a, nota_a in inicios:
            duracao = b["fim"] - a["ini"]
            if minimo <= duracao <= maximo and i <= j:
                nota = nota_a + nota_b - abs(duracao - alvo) / 14
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
    if novas == [p["p"] for p in grupo.get("palavras", [])]:
        return grupo
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
