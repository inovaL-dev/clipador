"""Modelos de legenda e de título usados nos Shorts e nos vídeos longos."""
from __future__ import annotations

import re

from . import filtros
from .contexto import FORTES, quebrar_linhas

CORES = {"amarelo": "FFC933", "verde": "39FF88", "vermelho": "FF4B5C", "azul": "38BDF8", "rosa": "FF5FCF", "laranja": "FF8A1F", "branco": "FFFFFF"}
LEGENDAS = ("destaque", "caixa", "impacto", "palavra", "neon", "faixa", "classica")
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
          "sons_auto": True, "zoom_forca": 100, "ritmo": 5.0, **{p: None for p in POSICOES}}


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
            elif chave == "sons_auto":
                final[chave] = valor in (True, "true", "True", 1, "1")
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
        elif chave in ("sons_auto", "zoom_forca", "ritmo"):
            continue
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


def _estilo(nome: str, tamanho: float, frente: str, contorno: str, fundo: str, borda: int, largura: float, sombra: float) -> str:
    return (f"Style: {nome},Poppins,{round(tamanho)},{frente},&H00FFFFFF,{contorno},{fundo},-1,0,0,0,100,100,0,0,"
            f"{borda},{round(largura, 1)},{round(sombra, 1)},2,60,60,0,1")


def estilo_legenda(est: dict, base: float) -> str:
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
    }
    frente, contorno, fundo, borda, largura, sombra = modelos[est["legenda"]]
    return _estilo("Legenda", t * {"impacto": 1.45, "palavra": 1.25}.get(est["legenda"], 1), frente, contorno, fundo, borda, largura, sombra)


def _palavra(texto: str, ativa: bool, est: dict, base: float) -> str:
    destaque = cor_ass(est["cor"])
    modelo = est["legenda"]
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


def eventos_legenda(grupos: list[dict], duracao: float, est: dict, cx: int, y: int, base: float, por_linha: int, tempo) -> list[str]:
    """Cria a legenda no modelo escolhido; `tempo` converte segundos para o formato do arquivo."""
    modelo = est["legenda"]
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
                partes.append(_palavra(texto, j == i, est, base))
            entrada = "\\fscx92\\fscy92\\t(0,90,\\fscx100\\fscy100)" if i == 0 else ""
            linhas.append(f"Dialogue: 2,{tempo(p['ini'])},{tempo(fim)},Legenda,,0,0,0,,{{\\an2\\pos({cx},{y}){efeito_extra}{entrada}}}{''.join(partes)}")
    return linhas


def copiar_fontes(ass: str, pasta) -> None:
    """Coloca na pasta de trabalho todas as fontes que o arquivo de legenda usa.

    O Windows não tem essas fontes instaladas: sem a cópia, o título sairia com uma fonte comum."""
    import shutil
    from pathlib import Path

    origem = Path(__file__).resolve().parent.parent / "fontes"
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    nomes = {"Poppins-Bold"} | {m.strip().replace(" ", "-") for m in re.findall(r"^Style:\s*[^,]*,([^,]+),", ass, re.M)}
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
        tons = {"branco": branco, "preto": preto, "destaque": _alfa(destaque), "vermelho": "&H002E20E5", "escuro": "&H00140F0B", "sombra": "&H80000000"}
        return (f"Style: {nome},{fonte},{round(tamanho * escala)},{tons[fr]},&H00FFFFFF,{tons[co]},{tons[fundo]},0,0,0,0,100,100,0,0,"
                f"{borda},{round(tamanho * largura, 1)},{round(tamanho * sombra, 1)},{alinhamento},70,70,0,1")
    frente, contorno, borda, largura, sombra = modelos[est["gancho"]]
    grande = 1.16 if est["gancho"] in ("contorno", "neon") else 1
    return (f"Style: {nome},Poppins,{round(tamanho * grande)},{frente},&H00FFFFFF,{contorno},&H00000000,-1,0,0,0,100,100,0,0,"
            f"{borda},{round(largura, 1)},{round(sombra, 1)},{alinhamento},70,70,0,1")


def efeito_gancho(est: dict) -> str:
    if est["gancho"] in TITULOS_EXTRA:
        giro = TITULOS_EXTRA[est["gancho"]][8]
        return f"\\frz{giro}" if giro else ""
    return {"branco": "\\frz-2", "neon": "\\blur6"}.get(est["gancho"], "")
