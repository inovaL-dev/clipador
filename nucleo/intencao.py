"""O que você quer nos cortes de um vídeo gravado (ideia trazida do Cortador Automático).

Você marca o tipo de momento ou escreve com suas palavras ("quando ele foge da polícia", "as risadas") e isso
muda de verdade quais momentos viram corte: os momentos em que o chat fala disso, e em que o sinal certo
(risada no chat, grito do streamer, ação no jogo) aparece, ganham força na escolha.
As palavras que você escrever também viram busca no chat da live.
"""
from __future__ import annotations

import re
import unicodedata

INTENCOES = {
    "engracado": {"nome": "Engraçado", "gatilhos": r"engra[cç]ad|risad|rir\b|piada|zoeir|meme|kk+|divertid|humor",
                  "chat": r"k{3,}|ha(ha)+|rs{2,}|kekw|omegalul|lul\b|😂|🤣|palha[cç]|zoeira|morri", "causa": ("chat",)},
    "susto": {"nome": "Susto e tensão", "gatilhos": r"susto|tens[aã]o|medo|terror|perigo|quase|desesper|nervos",
              "chat": r"susto|medo|socorro|corre|quase|meu deus|😱|😳|nervos|cora[cç][aã]o", "causa": ("streamer", "chat")},
    "jogada": {"nome": "Jogada e clutch", "gatilhos": r"jogad|clutch|kill|abate|play|gol\b|ace\b|vit[oó]ria|ganh|mira|headshot",
               "chat": r"clutch|\bace\b|insano|absurd|monstro|brabo|pog|\bgg\b|\bw+\b|gol+|🔥|🐐|que jogada|mito", "causa": ("jogo", "chat")},
    "deu_ruim": {"nome": "Deu ruim", "gatilhos": r"deu ruim|falha|fail|erro|morreu|perdeu|vergonha|mico",
                 "chat": r"deu ruim|f+\b|rip|perdeu|vergonha|n[aã]o acredito|kkk+|💀|😭|lixo", "causa": ("chat", "streamer")},
    "reacao": {"nome": "Reação forte", "gatilhos": r"rea[cç][aã]o|react|surpres|choque|chocad|grit|admirad",
               "chat": r"meu deus|nossa|que isso|caraca|caramba|wtf|omg|oloco|😱|😳|🤯", "causa": ("streamer", "admirado")},
    "revelacao": {"nome": "Revelação e sorteio", "gatilhos": r"revela|abertura|abrir|sorteio|caixa|pack|carta|unbox|raro|lend[aá]ri|pr[eê]mio",
                  "chat": r"veio|saiu|raro|lend[aá]ri|sorte|pr[eê]mio|ganhou|🎉|🍀", "causa": ("admirado", "chat")},
    "perseguicao": {"nome": "Perseguição e fuga", "gatilhos": r"persegui|fuga|fugir|pol[ií]cia|procurad|gta|rp\b",
                    "chat": r"pol[ií]cia|corre|foge|fuga|viatura|helic[oó]ptero|escapou|preso|pres[oa]", "causa": ("jogo", "chat")},
    "briga": {"nome": "Treta e discussão", "gatilhos": r"treta|briga|discuss|polemic|polêmic|xing|barraco|desabaf",
              "chat": r"treta|briga|barraco|eita|vish|calma|tretou|🍿|polemic", "causa": ("streamer", "chat")},
}
VAZIAS = set("quero queria gostaria preciso melhores melhor momentos momento partes parte trechos trecho cortes corte video videos "
             "mais muito para pra que com dos das uma onde quando ele ela eles elas sobre tudo coisa coisas fazer tenha tem seja ser bem "
             "todo toda todos pega pegue foco focar deixa faz pode vai pessoas galera aparece acontece fica tipo estilo forma jeito live".split())


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def interpretar(escolhidas: list | None, texto: str = "") -> dict:
    """Junta os tipos marcados com o que você escreveu. Devolve {"ids", "termos", "resumo"}."""
    ids = [i for i in (escolhidas or []) if i in INTENCOES]
    texto = " ".join(str(texto or "").split())[:200]
    normal = _sem_acento(texto)
    for i, d in INTENCOES.items():
        if texto and i not in ids and (re.search(d["gatilhos"], texto, re.I) or re.search(d["gatilhos"], normal, re.I)):
            ids.append(i)
    termos = []
    for p in re.findall(r"[a-zà-ú0-9]{4,}", texto.lower()):
        limpo = _sem_acento(p)
        if limpo not in VAZIAS and limpo not in termos:
            termos.append(limpo)
    nomes = [INTENCOES[i]["nome"] for i in ids] + [f"“{t}”" for t in termos[:4]]
    return {"ids": ids, "termos": termos[:8], "texto": texto, "resumo": ", ".join(nomes)}


def bonus(nota: dict, intencao: dict | None) -> float:
    """Quanto um bloco de 10 s ganha por combinar com o que você pediu (0 a 60)."""
    if not intencao or not (intencao.get("ids") or intencao.get("termos")):
        return 0.0
    textos = [_sem_acento(str(t)) for t in nota.get("textos") or []]
    total = 0.0
    for i in intencao.get("ids") or []:
        d = INTENCOES[i]
        if textos:
            batem = sum(1 for t in textos if re.search(d["chat"], t, re.I))
            total += min(25.0, batem / len(textos) * 60 + min(8, batem))
        if nota.get("causa") in d["causa"]:
            total += 8.0
    termos = intencao.get("termos") or []
    if termos and textos:
        batem = sum(1 for t in textos if any(x in t for x in termos))
        total += min(25.0, batem * 4.0)
    return min(60.0, total)
