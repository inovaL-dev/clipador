"""Modelos de legenda e de título usados nos Shorts e nos vídeos longos."""
from __future__ import annotations

import re

from functools import lru_cache
from pathlib import Path

from . import filtros
from .contexto import FORTES, quebrar_linhas
from .modelos_legenda import MODELOS as MODELOS_EDITOR

PASTA_FONTES = Path(__file__).resolve().parent.parent / "fontes"


@lru_cache(maxsize=1)
def fontes() -> dict[str, str]:
    """Arquivo da fonte (sem .ttf) -> nome que o FFmpeg usa para achá-la, como "Montserrat Black"."""
    from PIL import ImageFont
    saida = {}
    for arquivo in sorted(PASTA_FONTES.glob("*.ttf")):
        try:
            familia, peso = ImageFont.truetype(str(arquivo), 10).getname()
        except OSError:
            continue
        saida[arquivo.stem] = familia if peso in ("Regular", "Normal", "Book") or peso in familia else f"{familia} {peso}"
    return saida

CORES = {"amarelo": "FFC933", "verde": "39FF88", "vermelho": "FF4B5C", "azul": "38BDF8", "rosa": "FF5FCF", "laranja": "FF8A1F", "branco": "FFFFFF"}
LEGENDAS = ("react", "destaque", "caixa", "impacto", "palavra", "neon", "faixa", "classica", "karaoke", "hormozi", *MODELOS_EDITOR)
GANCHOS = ("faixa", "preto", "alerta", "branco", "contorno", "neon", "impacto", "quadrinho", "manchete", "gamer", "desenho", "minimal", "sombra3d", "marcador", "nenhum")
# Modelos de título com outra fonte: fonte, texto, contorno, tipo de borda (1 letra, 3 caixa), contorno, sombra, cor da sombra, tamanho, giro
TITULOS_EXTRA = {
    "impacto": ("Anton", "branco", "preto", 1, .14, .05, "preto", 1.3, 0),
    "quadrinho": ("Bangers", "destaque", "preto", 1, .16, .07, "preto", 1.3, -3),
    "manchete": ("Bebas Neue", "branco", "vermelho", 3, .3, 0, "preto", 1.35, 0),
    "gamer": ("Russo One", "destaque", "escuro", 3, .34, 0, "preto", 1.05, 0),
    "desenho": ("Luckiest Guy", "branco", "destaque", 1, .15, .06, "preto", 1.2, 0),
    "minimal": ("Montserrat Black", "branco", "preto", 1, 0, .05, "sombra", 1.0, 0),
    "sombra3d": ("Archivo Black", "branco", "preto", 1, .06, .1, "destaque", 1.1, 0),
    "marcador": ("Permanent Marker", "preto", "branco", 3, .32, 0, "preto", 1.1, -2),
}
TAMANHOS = {"pequeno": 0.86, "medio": 1.0, "grande": 1.18}
TEMPOS_GANCHO = (3, 5, 8)
POSICOES = ("legenda_x", "legenda_y", "gancho_x", "gancho_y", "legenda_hx", "legenda_hy", "gancho_hx", "gancho_hy")
PADRAO = {"legenda": "destaque", "gancho": "faixa", "cor": "amarelo", "tamanho": "medio", "tempo_gancho": 5, "filtro": "nenhum", "filtro_forca": 100,
          "sons_auto": True, "zoom_forca": 100, "ritmo": 5.0, "camera_dinamica": False, "arroba": "", "encerramento": True,
          "fonte_legenda": "", "fonte_titulo": "", "barra_progresso": False, "abertura": True, **{p: None for p in POSICOES}}
ARROBA = re.compile(r"^@?([A-Za-z0-9_.]{2,30})$")


def _posicao(valor) -> float | None:
    """Fração da tela entre 0 e 1; vazio significa o lugar automático."""
    if valor in (None, "", "null"):
        return None
    numero = float(valor)
    if not 0 <= numero <= 1:
        raise ValueError
    return round(numero, 4)


def normalizar(estilo: dict | None, base: dict | None = None) -> dict:
    """Junta o estilo escolhido com o padrão e ignora valores desconhecidos."""
    final = dict(PADRAO)
    for origem in (base, estilo):
        for chave, valor in (origem or {}).items():
            if (chave == "legenda" and valor in LEGENDAS) or (chave == "gancho" and valor in GANCHOS) \
                    or (chave == "cor" and valor in CORES) or (chave == "tamanho" and valor in TAMANHOS):
                final[chave] = valor
            elif chave == "tempo_gancho" and str(valor).isdigit() and int(valor) in TEMPOS_GANCHO:
                final[chave] = int(valor)
            elif chave == "filtro" and valor in filtros.FILTROS:
                final[chave] = valor
            elif chave == "filtro_forca" and str(valor).isdigit() and 0 <= int(valor) <= 100:
                final[chave] = int(valor)
            elif chave == "zoom_forca":
                final[chave] = int(min(200, max(0, float(valor))))
            elif chave == "ritmo":
                final[chave] = float(min(8.0, max(2.0, float(valor))))
            elif chave in ("sons_auto", "camera_dinamica", "encerramento", "barra_progresso", "abertura"):
                final[chave] = valor in (True, "true", "True", 1, "1")
            elif chave in ("fonte_legenda", "fonte_titulo"):
                final[chave] = valor if valor in fontes() else ""
            elif chave == "arroba":
                m = ARROBA.match(str(valor or "").strip())
                final[chave] = f"@{m[1]}" if m else ""
            elif chave in POSICOES:
                try:
                    final[chave] = _posicao(valor)
                except (TypeError, ValueError):
                    pass
    return final


def validar(estilo: dict) -> dict:
    final = normalizar(estilo)
    for chave, valor in estilo.items():
        if chave in POSICOES:
            try:
                _posicao(valor)
            except (TypeError, ValueError):
                raise ValueError("Posição inválida.") from None
        elif chave in ("sons_auto", "zoom_forca", "ritmo", "camera_dinamica", "encerramento", "barra_progresso", "abertura"):
            continue
        elif chave == "arroba":
            if str(valor or "").strip() and not final["arroba"]:
                raise ValueError("Escreva o @ só com letras, números, ponto ou sublinhado.")
        elif chave in PADRAO and str(final[chave]) != str(valor):
            raise ValueError("Escolha um estilo válido.")
    return final


def ponto(est: dict, chave_x: str, chave_y: str, largura: int, altura: int, x: int, y: int) -> tuple[int, int]:
    """Lugar escolhido pelo usuário ou o lugar automático do layout."""
    px = x if est.get(chave_x) is None else round(est[chave_x] * largura)
    py = y if est.get(chave_y) is None else round(est[chave_y] * altura)
    return px, py


def cor_ass(nome_ou_hex: str) -> str:
    h = CORES.get(nome_ou_hex, nome_ou_hex)
    return f"&H{h[4:6]}{h[2:4]}{h[:2]}&"


def cor_bgr(nome: str) -> tuple[int, int, int]:
    h = CORES[nome]
    return int(h[4:6], 16), int(h[2:4], 16), int(h[:2], 16)


def _alfa(cor: str, alfa: str = "00") -> str:
    return f"&H{alfa}{cor[2:-1]}"


def _maiusculas(t: str) -> str:
    return re.sub(r"[{}\\]", "", t).upper()


def _natural(t: str) -> str:
    return re.sub(r"[{}\\]", "", t)


def _estilo(nome: str, tamanho: float, frente: str, contorno: str, fundo: str, borda: int, largura: float, sombra: float, fonte: str = "Poppins") -> str:
    return (f"Style: {nome},{fonte},{round(tamanho)},{frente},&H00FFFFFF,{contorno},{fundo},-1,0,0,0,100,100,0,0,"
            f"{borda},{round(largura, 1)},{round(sombra, 1)},2,60,60,0,1")


@lru_cache(maxsize=None)
def proporcao(arquivo: str) -> float:
    """Quanto o FFmpeg encolhe a letra desta fonte: ele mede a altura total da linha
    (usWinAscent + usWinDescent), e o editor mede a letra. Sem isso a Bungee sairia com metade do tamanho."""
    import struct
    try:
        dados = (PASTA_FONTES / f"{arquivo}.ttf").read_bytes()
        n = struct.unpack(">H", dados[4:6])[0]
        tabelas = {dados[12 + 16 * i:16 + 16 * i]: struct.unpack(">I", dados[20 + 16 * i:24 + 16 * i])[0] for i in range(n)}
        em = struct.unpack(">H", dados[tabelas[b"head"] + 18:tabelas[b"head"] + 20])[0]
        sobe, desce = struct.unpack(">HH", dados[tabelas[b"OS/2"] + 74:tabelas[b"OS/2"] + 78])
        return max(.9, min(3.0, (sobe + desce) / em))
    except (OSError, KeyError, struct.error, ZeroDivisionError):
        return 1.5


def _hex_ass(cor: str, opacidade: float = 100) -> str:
    """#RRGGBB -> &HAABBGGRR do formato de legenda."""
    c = (cor or "#000000").lstrip("#").upper().ljust(6, "0")[:6]
    alfa = max(0, min(255, round(255 * (1 - opacidade / 100))))
    return f"&H{alfa:02X}{c[4:6]}{c[2:4]}{c[0:2]}"


def fonte_ass(arquivo: str) -> str:
    return fontes().get(arquivo, "Poppins")


LETRA_EDITOR = 0.9  # os modelos do editor são maiores que a legenda automática; aqui ficam um pouco menores


def modelo_editor(est: dict) -> dict | None:
    item = MODELOS_EDITOR.get(est["legenda"])
    if not item:
        return None
    m = dict(item[2])
    if est.get("fonte_legenda"):
        m["fonte"] = est["fonte_legenda"]
    return m


def _estilo_editor(est: dict, m: dict) -> str:
    k = LETRA_EDITOR * TAMANHOS[est["tamanho"]]  # tamanho da letra em pixels, como no editor
    tamanho = m["tamanho"] * k * proporcao(m["fonte"])
    frente = _hex_ass(m.get("cor", "#FFFFFF"))
    if m.get("fundo"):  # caixa atrás da frase
        return (f"Style: Legenda,{fonte_ass(m['fonte'])},{round(tamanho)},{frente},&H00FFFFFF,{_hex_ass(m.get('fundo_cor', '#000000'), m.get('fundo_opac', 100))},&H00000000,0,0,0,0,100,100,"
                f"{m.get('espacamento', 0)},0,3,{round(m.get('fundo_pad', 12) * k, 1)},0,2,60,60,0,1")
    contorno = m.get("contorno", 0) * k
    brilho = m.get("sombra") and m.get("sombra_blur", 0) >= 10 and not m.get("sombra_y", 4)
    cor_contorno = _hex_ass(m.get("sombra_cor", "#000000"), 70) if brilho else _hex_ass(m.get("contorno_cor", "#000000"))
    if brilho:
        contorno = max(contorno, 3 * k)
    if m.get("relevo"):
        sombra, cor_sombra = m["relevo"] * k * .6, _hex_ass(m.get("relevo_cor", "#000000"))
    elif m.get("sombra") and not brilho:
        sombra, cor_sombra = max(1.5, m.get("sombra_y", 4) * k * .6), _hex_ass(m.get("sombra_cor", "#000000"), m.get("sombra_opac", 60))
    else:
        sombra, cor_sombra = 0, "&H00000000"
    sublinhado = -1 if m.get("sublinhado") else 0
    return (f"Style: Legenda,{fonte_ass(m['fonte'])},{round(tamanho)},{frente},&H00FFFFFF,{cor_contorno},{cor_sombra},0,0,{sublinhado},0,100,100,"
            f"{m.get('espacamento', 0)},0,1,{round(contorno, 1)},{round(sombra, 1)},2,60,60,0,1")


def estilo_legenda(est: dict, base: float) -> str:
    if m := modelo_editor(est):
        return _estilo_editor(est, m)
    t = base * TAMANHOS[est["tamanho"]]
    destaque = cor_ass(est["cor"])
    modelos = {
        "destaque": ("&H00FFFFFF", "&H00000000", "&H80000000", 1, t * 0.106, 2),
        "caixa": ("&H00FFFFFF", "&H00000000", "&H80000000", 1, t * 0.09, 2),
        "impacto": (_alfa(destaque), "&H00000000", "&H80000000", 1, t * 0.13, 4),
        "palavra": ("&H00FFFFFF", "&H00000000", "&H80000000", 1, t * 0.13, 3),
        "neon": (_alfa(destaque), _alfa(destaque, "50"), "&H00000000", 1, t * 0.07, 0),
        "faixa": ("&H00FFFFFF", "&H28000000", "&H00000000", 3, t * 0.2, 0),
        "classica": ("&H00FFFFFF", "&H00000000", "&H70000000", 1, t * 0.05, t * 0.05),
        "karaoke": ("&H00FFFFFF", "&H00000000", "&H80000000", 1, t * 0.1, 2),
        "hormozi": ("&H00FFFFFF", "&H00000000", "&H90000000", 1, t * 0.12, 3),
        "react": (_alfa(destaque), "&H00000000", "&H00000000", 1, t * 0.12, 0),
    }
    frente, contorno, fundo, borda, largura, sombra = modelos[est["legenda"]]
    original = {"hormozi": "Anton", "react": "Roboto-Black"}.get(est["legenda"], "Poppins-Bold")
    escolhida = est.get("fonte_legenda") or original
    t *= proporcao(escolhida) / proporcao(original)  # outra fonte, mesmo tamanho de letra
    return _estilo("Legenda", t * {"impacto": 1.45, "palavra": 1.25, "hormozi": 1.3, "react": 1.35}.get(est["legenda"], 1), frente, contorno, fundo, borda, largura, sombra, fonte_ass(escolhida))


SOLTAS = {"o", "a", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", "no", "na", "nos", "nas", "em", "e", "que", "pra", "pro", "com", "por", "pelo", "pela", "meu", "minha", "seu", "sua", "se", "me", "te", "lhe", "não", "nao", "muito", "mais", "ao"}


def picar(grupos: list[dict], palavras_max: int = 3, letras_max: int = 16) -> list[dict]:
    """Quebra a legenda em pedaços de 1 a 3 palavras, como nos cortes de react.

    Corta antes nas pausas e depois de pontuação, para cada pedaço ser uma ideia curta."""
    saida = []
    for g in grupos:
        atual: list[dict] = []
        for p in g.get("palavras") or []:
            if atual:
                letras = sum(len(x["p"]) + 1 for x in atual) + len(p["p"])
                pausa = float(p["ini"]) - float(atual[-1]["fim"]) >= .35
                if len(atual) >= palavras_max or letras > letras_max or pausa or atual[-1]["p"][-1:] in ".!?,;:":
                    leva = []
                    while not pausa and len(atual) > 1 and len(leva) < 2 and atual[-1]["p"][-1:].isalnum() and re.sub(r"\W", "", atual[-1]["p"]).casefold() in SOLTAS:
                        leva.insert(0, atual.pop())  # "Ele pegou o | carro" vira "Ele pegou | o carro"
                    saida.append({"ini": atual[0]["ini"], "fim": atual[-1]["fim"], "palavras": atual})
                    atual = leva
            atual.append(p)
        if atual:
            saida.append({"ini": atual[0]["ini"], "fim": atual[-1]["fim"], "palavras": atual})
    return saida


def _palavra(texto: str, ativa: bool, est: dict, base: float, ja_falada: bool = False, primeira: bool = False) -> str:
    destaque = cor_ass(est["cor"])
    modelo = est["legenda"]
    if modelo == "karaoke":  # as palavras já faladas ficam na cor de destaque, como num karaokê
        if ativa:
            return f"{{\\c{destaque}\\fscx112\\fscy112}}{texto}{{\\c&HFFFFFF&\\fscx100\\fscy100}}"
        return f"{{\\c{destaque}}}{texto}{{\\c&HFFFFFF&}}" if ja_falada else texto
    if modelo == "hormozi":  # primeira palavra em vermelho e a falada um pouco maior
        cor_p = "&H2D2DFF&" if primeira else "&HFFFFFF&"
        if ativa:
            return f"{{\\c{cor_p}\\fscx110\\fscy110}}{texto}{{\\c&HFFFFFF&\\fscx100\\fscy100}}"
        return f"{{\\c{cor_p}}}{texto}{{\\c&HFFFFFF&}}" if primeira else texto
    if not ativa or modelo == "classica":
        return texto
    if modelo == "caixa":
        borda = round(base * TAMANHOS[est["tamanho"]] * 0.14)
        normal = round(base * TAMANHOS[est["tamanho"]] * 0.09, 1)
        tinta = "&H141414&" if est["cor"] != "vermelho" else "&HFFFFFF&"
        return f"{{\\c{tinta}\\3c{destaque}\\bord{borda}}}{texto}{{\\c&HFFFFFF&\\3c&H000000&\\bord{normal}}}"
    if modelo == "neon":
        return f"{{\\c&HFFFFFF&\\fscx110\\fscy110}}{texto}{{\\c{destaque}\\fscx100\\fscy100}}"
    if modelo == "destaque" and (FORTES.search(texto) or texto[-1:] in "!?"):
        return f"{{\\c&H4B5CFF&\\fscx116\\fscy116}}{texto}{{\\c&HFFFFFF&\\fscx100\\fscy100}}"
    return f"{{\\c{destaque}}}{texto}{{\\c&HFFFFFF&}}"


def eventos_legenda(grupos: list[dict], duracao: float, est: dict, cx: int, y: int, base: float, por_linha: int, tempo, y_em=None) -> list[str]:
    """Cria a legenda no modelo escolhido; `tempo` converte segundos para o formato do arquivo."""
    modelo = est["legenda"]
    if modelo == "react":  # pedaços curtos, amarelos, presos logo abaixo da divisão da tela
        linhas = []
        pedacos = picar(grupos)
        for n, g in enumerate(pedacos):
            ini = float(g["palavras"][0]["ini"])
            proximo = float(pedacos[n + 1]["ini"]) if n + 1 < len(pedacos) else duracao
            fim = max(ini + .25, min(proximo, float(g["palavras"][-1]["fim"]) + .3, duracao))
            texto = " ".join(_natural(p["p"]) for p in g["palavras"]).rstrip(",;:.")
            texto = texto[:1].upper() + texto[1:]
            ancora, py = y_em(ini) if y_em else (2, y)
            linhas.append(f"Dialogue: 2,{tempo(ini)},{tempo(fim)},Legenda,,0,0,0,,{{\\an{ancora}\\pos({cx},{py})\\fscx78\\fscy78\\t(0,90,\\fscx104\\fscy104)\\t(90,150,\\fscx100\\fscy100)}}{texto}")
        return linhas
    if m := modelo_editor(est):
        return _eventos_editor(grupos, duracao, est, m, cx, y, por_linha, tempo, y_em)
    limpar = _natural if modelo in ("classica", "palavra") else _maiusculas
    efeito_extra = "\\blur5" if modelo == "neon" else ""
    linhas: list[str] = []
    for g, grupo in enumerate(grupos):
        palavras = grupo["palavras"]
        if not palavras:
            continue
        textos = [limpar(p["p"]) for p in palavras]
        quebra = quebrar_linhas(textos, por_linha)
        proximo = grupos[g + 1]["ini"] if g + 1 < len(grupos) else duracao
        limite = min(proximo, palavras[-1]["fim"] + 0.35, duracao)
        if modelo == "classica":
            partes = [("\\N" if j == quebra else " " if j else "") + t for j, t in enumerate(textos)]
            linhas.append(f"Dialogue: 2,{tempo(palavras[0]['ini'])},{tempo(max(limite, palavras[0]['ini'] + 0.1))},Legenda,,0,0,0,,"
                          f"{{\\an2\\pos({cx},{y})\\fad(70,70)}}{''.join(partes)}")
            continue
        for i, p in enumerate(palavras):
            fim = palavras[i + 1]["ini"] if i + 1 < len(palavras) else limite
            fim = max(fim, p["ini"] + 0.05)
            if modelo in ("impacto", "palavra"):
                cor = f"\\c{cor_ass(est['cor'])}" if modelo == "palavra" and (FORTES.search(textos[i]) or textos[i][-1:] in "!?") else ""
                linhas.append(f"Dialogue: 2,{tempo(p['ini'])},{tempo(fim)},Legenda,,0,0,0,,"
                              f"{{\\an2\\pos({cx},{y}){cor}\\fscx72\\fscy72\\t(0,80,\\fscx100\\fscy100)}}{textos[i]}")
                continue
            partes = []
            for j, texto in enumerate(textos):
                partes.append("\\N" if j == quebra else " " if j else "")
                partes.append(_palavra(texto, j == i, est, base, j < i, j == 0))
            entrada = "\\fscx92\\fscy92\\t(0,90,\\fscx100\\fscy100)" if i == 0 else ""
            linhas.append(f"Dialogue: 2,{tempo(p['ini'])},{tempo(fim)},Legenda,,0,0,0,,{{\\an2\\pos({cx},{y}){efeito_extra}{entrada}}}{''.join(partes)}")
    return linhas


ENTRADAS = {
    "pop": "\\fscx80\\fscy80\\t(0,110,\\fscx100\\fscy100)",
    "zoom": "\\fscx55\\fscy55\\t(0,140,\\fscx100\\fscy100)",
    "quique": "\\fscx70\\fscy70\\t(0,110,\\fscx112\\fscy112)\\t(110,190,\\fscx100\\fscy100)",
    "carimbo": "\\fscx150\\fscy150\\alpha&H80&\\t(0,120,\\fscx100\\fscy100\\alpha&H00&)",
    "fade": "\\fad(140,0)",
    "digitando": "\\fad(60,0)",
}


def _importante(texto: str) -> bool:
    nucleo = re.sub(r"\W", "", texto)
    return bool(FORTES.search(texto) or texto[-1:] in "!?" or len(nucleo) >= 7)


def _eventos_editor(grupos: list[dict], duracao: float, est: dict, m: dict, cx: int, y: int, por_linha: int, tempo, y_em=None) -> list[str]:
    """Legenda nos modelos do editor: a regra de destaque decide quais palavras mudam de cor."""
    regra, caixa = m.get("destaque", "palavra"), m.get("destaque_caixa")
    destaque, normal = _hex_ass(m.get("cor_destaque", "#FFD400")).replace("&H00", "&H"), _hex_ass(m.get("cor", "#FFFFFF")).replace("&H00", "&H")
    escala = int(m.get("destaque_escala", 100))
    k = LETRA_EDITOR * TAMANHOS[est["tamanho"]]
    contorno = round(m.get("contorno", 0) * k, 1)
    caixa_bord = round(m["tamanho"] * k * .14, 1)
    brilho = "\\blur6" if m.get("sombra") and m.get("sombra_blur", 0) >= 10 and not m.get("sombra_y", 4) else ""
    por_linha = max(8, round(por_linha * 54 / max(30, m["tamanho"] * LETRA_EDITOR) * (1.25 if m["fonte"] in ("Anton", "Bebas-Neue", "Oswald-Bold", "Teko-Bold", "Barlow-Condensed-ExtraBold") else 1)))  # letra maior, menos letras por linha

    def limpar(t: str) -> str:
        t = re.sub(r"[{}\\]", "", t)
        if m.get("sem_pontuacao"):
            t = re.sub(r"[.,;:!?…]+", "", t)
        return t.upper() if m.get("maiusculas") else t

    def marcada(j: int, i: int, textos: list[str]) -> bool:
        if regra == "palavra":
            return j == i
        if regra == "importantes":
            return _importante(textos[j])
        if regra == "primeira":
            return j == 0
        if regra == "falado":
            return j <= i
        if regra == "alternadas":
            return j % 2 == 1
        return False

    def pintar(texto: str, sim: bool, ativa: bool) -> str:
        if not sim:
            return texto
        if caixa and ativa:
            return f"{{\\c&H141414&\\3c{destaque}\\bord{caixa_bord}}}{texto}{{\\c{normal}\\3c&H000000&\\bord{contorno}}}"
        grande = f"\\fscx{escala}\\fscy{escala}" if escala != 100 and (ativa or regra == "primeira") else ""
        volta = "\\fscx100\\fscy100" if grande else ""
        return f"{{\\c{destaque}{grande}}}{texto}{{\\c{normal}{volta}}}"

    linhas: list[str] = []
    for g, grupo in enumerate(grupos):
        palavras = [p for p in grupo.get("palavras") or [] if limpar(p["p"]).strip()]
        if not palavras:
            continue
        textos = [limpar(p["p"]) for p in palavras]
        quebra = quebrar_linhas(textos, por_linha)
        proximo = grupos[g + 1]["ini"] if g + 1 < len(grupos) else duracao
        limite = min(proximo, palavras[-1]["fim"] + 0.35, duracao)
        ancora, py = y_em(float(palavras[0]["ini"])) if y_em else (2, y)
        pos = f"\\an{ancora}\\pos({cx},{py}){brilho}"
        if m.get("palavra_a_palavra"):
            for i, p in enumerate(palavras):
                fim = max(p["ini"] + .05, palavras[i + 1]["ini"] if i + 1 < len(palavras) else limite)
                cor = f"\\c{destaque}" if marcada(i, i, textos) and regra != "palavra" else ""
                linhas.append(f"Dialogue: 2,{tempo(p['ini'])},{tempo(fim)},Legenda,,0,0,0,,{{{pos}{cor}{ENTRADAS.get(m.get('entrada'), ENTRADAS['pop'])}}}{textos[i]}")
            continue
        entrada = ENTRADAS.get(m.get("entrada"), "")
        if regra in ("nenhum", "importantes", "primeira", "alternadas"):  # o destaque não depende de quem está falando
            partes = [("\\N" if j == quebra else " " if j else "") + pintar(t, marcada(j, 0, textos), False) for j, t in enumerate(textos)]
            linhas.append(f"Dialogue: 2,{tempo(palavras[0]['ini'])},{tempo(max(limite, palavras[0]['ini'] + .1))},Legenda,,0,0,0,,{{{pos}{entrada}}}{''.join(partes)}")
            continue
        for i, p in enumerate(palavras):
            fim = max(p["ini"] + .05, palavras[i + 1]["ini"] if i + 1 < len(palavras) else limite)
            partes = []
            for j, t in enumerate(textos):
                partes.append("\\N" if j == quebra else " " if j else "")
                partes.append(pintar(t, marcada(j, i, textos), j == i))
            linhas.append(f"Dialogue: 2,{tempo(p['ini'])},{tempo(fim)},Legenda,,0,0,0,,{{{pos}{entrada if i == 0 else ''}}}{''.join(partes)}")
    return linhas


def copiar_fontes(ass: str, pasta) -> None:
    """Coloca na pasta de trabalho todas as fontes que o arquivo de legenda usa.

    O Windows não tem essas fontes instaladas: sem a cópia, o título sairia com uma fonte comum."""
    import shutil
    from pathlib import Path

    origem = Path(__file__).resolve().parent.parent / "fontes"
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    usadas = {m.strip() for m in re.findall(r"^Style:\s*[^,]*,([^,]+),", ass, re.M)}
    por_nome = {nome: arquivo for arquivo, nome in fontes().items()}
    for nome in usadas:  # fontes dos modelos do editor: o nome não bate com o arquivo (ex.: "Baloo 2 ExtraBold")
        if nome in por_nome:
            shutil.copy(origem / f"{por_nome[nome]}.ttf", pasta / f"{por_nome[nome]}.ttf")
    nomes = {"Poppins-Bold"} | {m.replace(" ", "-") for m in usadas}
    for nome in nomes:
        for candidato in (nome, f"{nome}-Bold", nome.replace("-", "")):
            arquivo = origem / f"{candidato}.ttf"
            if arquivo.exists():
                shutil.copy(arquivo, pasta / arquivo.name)
                break


def estilo_gancho(est: dict, tamanho: float, nome: str = "Gancho", alinhamento: int = 8) -> str:
    destaque = cor_ass(est["cor"])
    preto, branco = "&H00141414", "&H00FFFFFF"
    modelos = {
        "faixa": (preto, _alfa(destaque), 3, tamanho * 0.37, 0),
        "preto": (_alfa(destaque), preto, 3, tamanho * 0.37, 0),
        "alerta": (branco, "&H00462DFF", 3, tamanho * 0.37, 0),
        "branco": (preto, branco, 3, tamanho * 0.37, 0),
        "contorno": (_alfa(destaque), "&H00000000", 1, tamanho * 0.18, tamanho * 0.06),
        "neon": (branco, _alfa(destaque), 1, tamanho * 0.08, 0),
        "nenhum": (preto, _alfa(destaque), 3, tamanho * 0.37, 0),
    }
    if est["gancho"] in TITULOS_EXTRA:
        fonte, fr, co, borda, largura, sombra, fundo, escala, _ = TITULOS_EXTRA[est["gancho"]]
        if est.get("fonte_titulo"):
            de = {v: k for k, v in fontes().items()}.get(fonte, "Poppins-Bold")
            escala *= proporcao(est["fonte_titulo"]) / proporcao(de)
            fonte = fonte_ass(est["fonte_titulo"])
        tons = {"branco": branco, "preto": preto, "destaque": _alfa(destaque), "vermelho": "&H002E20E5", "escuro": "&H00140F0B", "sombra": "&H80000000"}
        return (f"Style: {nome},{fonte},{round(tamanho * escala)},{tons[fr]},&H00FFFFFF,{tons[co]},{tons[fundo]},0,0,0,0,100,100,0,0,"
                f"{borda},{round(tamanho * largura, 1)},{round(tamanho * sombra, 1)},{alinhamento},70,70,0,1")
    frente, contorno, borda, largura, sombra = modelos[est["gancho"]]
    grande = 1.16 if est["gancho"] in ("contorno", "neon") else 1
    fonte = fonte_ass(est["fonte_titulo"]) if est.get("fonte_titulo") else "Poppins"
    if est.get("fonte_titulo"):
        tamanho *= proporcao(est["fonte_titulo"]) / proporcao("Poppins-Bold")
    return (f"Style: {nome},{fonte},{round(tamanho * grande)},{frente},&H00FFFFFF,{contorno},&H00000000,-1,0,0,0,100,100,0,0,"
            f"{borda},{round(largura, 1)},{round(sombra, 1)},{alinhamento},70,70,0,1")


def efeito_gancho(est: dict) -> str:
    if est["gancho"] in TITULOS_EXTRA:
        giro = TITULOS_EXTRA[est["gancho"]][8]
        return f"\\frz{giro}" if giro else ""
    return {"branco": "\\frz-2", "neon": "\\blur6"}.get(est["gancho"], "")
