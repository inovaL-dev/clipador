"""Transcrição mais certeira em português do Brasil.

O que melhora a legenda, em ordem de efeito:
1. Modelo maior: o large-v3-turbo erra bem menos em português que o small, com velocidade parecida com o medium.
2. Vocabulário: nome do canal, título da live (nomes de jogos e de pessoas), palavras que você cadastrou
   e palavras que você já corrigiu vão como "palavras esperadas" em toda janela de áudio (hotwords).
3. Busca mais ampla (beam 5) e detector de voz mais sensível, para não engolir fala baixa por cima do jogo.
4. Limpeza: frases que o Whisper inventa em silêncio ou música ("Legendas pela comunidade Amara.org",
   "Obrigado por assistir") e repetições em loop saem da legenda.
5. Correções aprendidas: quando você corrige uma palavra na legenda de um corte, o Clipador passa
   a trocar aquele erro sozinho nos próximos cortes.
"""
from __future__ import annotations

import difflib
import inspect
import os
import re
import unicodedata

MODELOS = ("base", "small", "medium", "large-v3-turbo")
MODELO_PRECISO = "large-v3-turbo"

# O Whisper foi treinado com muito vídeo legendado: em silêncio ou música ele "completa" com estas frases.
INVENTADAS = re.compile(r"legendas? (pela|por) comunidade|amara\.org|legendad[oa] por|legendas? (feitas? )?por|tradu[cç][aã]o (e|por)|www\.|\.com\.br", re.I)
# Estas o streamer pode falar de verdade: só saem quando o trecho parece silêncio ou música.
TALVEZ_INVENTADAS = re.compile(r"obrigad[oa]s? por (assistir|ter assistido)|inscreva-se no canal|ative o sininho|até o próximo vídeo", re.I)
# Palavras comuns demais para trocar na primeira correção ("mas" -> "mais" depende da frase).
COMUNS = {"a", "o", "e", "é", "de", "da", "do", "que", "se", "na", "no", "em", "um", "uma", "mas", "mais", "ta", "tá", "ja", "já", "so", "só",
          "pra", "pro", "com", "por", "nao", "não", "eu", "ele", "ela", "voce", "você", "isso", "esse", "essa", "aqui", "ai", "aí", "la", "lá", "ne", "né"}

# Diz ao Whisper o jeito da fala (português do Brasil, informal, com pontuação) sem frases que ele possa repetir.
PROMPT = {
    "pt": "Transcrição de uma live em português do Brasil, com gírias, nomes de jogos e pontuação.",
    "es": "Transcripción de un directo en español, con jerga, nombres de juegos y puntuación.",
    "en": "Transcript of a live stream in English, with slang, game names and punctuation.",
}
GENERICAS = {"live", "ao vivo", "hoje", "agora", "dia", "parte", "ep", "episodio", "episódio", "novo", "nova", "jogando", "pt", "br", "ptbr", "pt-br"}


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def chave(palavra: str) -> str:
    """Forma de comparar palavras: sem pontuação, sem acento e em minúsculas."""
    return _sem_acento(re.sub(r"[^\w-]", "", palavra)).casefold()


def memoria_gb() -> float:
    try:
        if os.name == "nt":
            import ctypes

            class Estado(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            e = Estado()
            e.dwLength = ctypes.sizeof(Estado)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e))
            return e.ullTotalPhys / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (AttributeError, OSError, ValueError):
        return 8.0


def aguenta_modelo_preciso() -> bool:
    """O large-v3-turbo precisa de uns 3 GB livres e de processador com pelo menos 4 núcleos."""
    return memoria_gb() >= 7.5 and (os.cpu_count() or 2) >= 4


def palavras_esperadas(vocabulario: str = "", canal: str = "", titulo: str = "", corrigidas: list[str] | None = None) -> str:
    """Lista curta de nomes e termos que costumam aparecer na live."""
    itens: list[str] = []
    for parte in re.split(r"[,;\n]+", vocabulario or ""):
        if parte.strip():
            itens.append(parte.strip())
    if canal:
        itens.append(canal)
    # Do título, só o que parece nome próprio: GTA, Valorant, Minecraft, Free Fire...
    for t in re.findall(r"\b(?:[A-ZÁÉÍÓÚÂÊÔÃÕÇ][\w'-]+|[A-Z0-9]{2,})(?:\s+(?:[A-Z][\w'-]+|[A-Z0-9]{2,}|\d+))*", titulo or ""):
        limpas, pular = [], False
        for w in t.split():  # tira "LIVE", "Dia 3", "Parte 2"...
            if w.casefold() in GENERICAS:
                pular = True
                continue
            if pular and w.isdigit():
                continue
            pular = False
            limpas.append(w)
        t = " ".join(limpas)
        if len(t) > 2:
            itens.append(t)
    itens += corrigidas or []
    vistos, final = set(), []
    for i in itens:
        if chave(i) and chave(i) not in vistos:
            vistos.add(chave(i))
            final.append(i)
    return ", ".join(final)[:220]


def opcoes(modelo, idioma: str, esperadas: str = "", rapido: bool = False) -> dict:
    """Opções da transcrição; só passa as que a versão instalada do faster-whisper conhece."""
    desejadas = {
        "language": idioma, "beam_size": 1 if rapido else 5, "best_of": 1 if rapido else 5,
        "vad_filter": True, "vad_parameters": {"threshold": .4, "min_silence_duration_ms": 450, "speech_pad_ms": 250},
        "condition_on_previous_text": False, "initial_prompt": PROMPT.get(idioma),
        "hotwords": esperadas or None, "no_repeat_ngram_size": 0 if rapido else 4,
        "hallucination_silence_threshold": None if rapido else 2.0,
    }
    try:
        aceitas = set(inspect.signature(modelo.transcribe).parameters)
    except (TypeError, ValueError):
        aceitas = set(desejadas)
    return {k: v for k, v in desejadas.items() if k in aceitas and v is not None}


def limpar_trechos(trechos) -> list[dict]:
    """Junta as palavras, sem as frases inventadas e sem as repetições em loop."""
    palavras: list[dict] = []
    for t in trechos:
        texto = (t.text or "").strip()
        if INVENTADAS.search(texto):
            continue
        if TALVEZ_INVENTADAS.search(texto) and (getattr(t, "no_speech_prob", 0) > .3 or getattr(t, "avg_logprob", 0) < -.9):
            continue
        for p in t.words or []:
            w = p.word.strip()
            if not w:
                continue
            if getattr(p, "probability", 1.0) < .05 and len(palavras) and chave(w) == chave(palavras[-1]["p"]):
                continue
            palavras.append({"p": w, "ini": round(p.start, 3), "fim": round(p.end, 3)})
    saida: list[dict] = []
    for p in palavras:  # "não não não não não não" -> no máximo 3 seguidas
        if len(saida) >= 3 and all(chave(x["p"]) == chave(p["p"]) for x in saida[-3:]):
            continue
        saida.append(p)
    return saida


def correcoes_valendo(aprendidas: dict) -> dict:
    """Erros com palavra comum só são trocados depois de você corrigir duas vezes."""
    return {k: v for k, v in (aprendidas or {}).items() if v.get("n", 0) >= 2 or (k not in COMUNS and len(k) >= 3)}


def aplicar_correcoes(palavras: list[dict], correcoes: dict) -> list[dict]:
    """Troca os erros que você já corrigiu antes. As chaves são sequências de 1 a 3 palavras."""
    if not correcoes or not palavras:
        return palavras
    tamanhos = sorted({len(k.split()) for k in correcoes}, reverse=True)
    saida, i = [], 0
    while i < len(palavras):
        for n in tamanhos:
            trecho = palavras[i:i + n]
            k = " ".join(chave(p["p"]) for p in trecho)
            certo = correcoes.get(k)
            if len(trecho) == n and certo:
                novas = certo["certo"].split()
                pont = re.search(r"[.,!?…;:]+$", trecho[-1]["p"])
                if pont and not re.search(r"[.,!?…;:]$", novas[-1]):
                    novas[-1] += pont[0]
                if trecho[0]["p"][:1].isupper() and novas[0][:1].islower():
                    novas[0] = novas[0][:1].upper() + novas[0][1:]
                ini, fim = trecho[0]["ini"], trecho[-1]["fim"]
                passo = (fim - ini) / len(novas)
                saida += [{"p": w, "ini": round(ini + j * passo, 3), "fim": round(ini + (j + 1) * passo, 3)} for j, w in enumerate(novas)]
                i += n
                break
        else:
            saida.append(palavras[i])
            i += 1
    return saida


def diferencas(antes: list[str], depois: list[str]) -> list[tuple[str, str]]:
    """Trocas curtas feitas à mão na legenda: [(errado, certo)], cada lado com até 3 palavras."""
    a, b = [chave(x) for x in antes], [chave(x) for x in depois]
    trocas = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "replace" or not (1 <= i2 - i1 <= 3 and 1 <= j2 - j1 <= 3):
            continue
        errado = " ".join(a[i1:i2])
        certo = " ".join(re.sub(r"[.,!?…;:]+$", "", x) for x in depois[j1:j2]).strip()
        if errado and certo and errado != " ".join(chave(x) for x in certo.split()):
            trocas.append((errado, certo))
    return trocas
