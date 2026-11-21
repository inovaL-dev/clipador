"""Posts de frase: as frases mais fortes de um corte, divididas em prints do rosto, para o feed e os stories.

Ideia do TopClip (MIT), refeita para o Clipador sem depender de IA paga:
- as frases saem da fala já transcrita do corte, escolhidas por regras de post que viraliza
  (funciona sozinha, tem contraste, conselho, número, emoção; nada de "isso", merchan ou palavrão);
- cada frase é dividida em 2 ou 3 partes, com as palavras-chave em negrito;
- cada parte ganha um print do rosto de perto de quando foi dita: o quadro mais nítido, com o rosto maior;
- a arte é branca e centralizada sobre um degradê escuro, no feed (4:5) ou nos stories (9:16).
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import uuid
import zipfile
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from . import camera as cam
from . import contexto as ctx
from .plataformas import sem_janela

PASTA_FONTES = Path(__file__).resolve().parent.parent / "fontes"
FORMATOS = {"feed": (1080, 1350), "stories": (1080, 1920)}
RESPIRO_STORIES = 250  # o Instagram põe a caixa de resposta no pé dos stories
MARGEM = 72
TAMANHO_TEXTO = {("feed", 1): 60, ("feed", 2): 54, ("feed", 3): 46, ("stories", 1): 64, ("stories", 2): 60, ("stories", 3): 54}
FONTES = {
    "dmsans": {"nome": "DM Sans", "arquivo": "posts/DMSans.ttf", "regular": {"Optical size": 32, "Weight": 400}, "negrito": {"Optical size": 32, "Weight": 700}},
    "montserrat": {"nome": "Montserrat", "arquivo": "posts/Montserrat.ttf", "regular": {"Weight": 400}, "negrito": {"Weight": 700}},
    "poppins": {"nome": "Poppins", "arquivo": "Poppins-Regular.ttf", "arquivo_negrito": "Poppins-Bold.ttf"},
    "fraunces": {"nome": "Fraunces (serifa)", "arquivo": "posts/Fraunces.ttf", "regular": {"Optical size": 72, "Weight": 400, "Softness": 50, "Wonky": 0}, "negrito": {"Optical size": 72, "Weight": 700, "Softness": 50, "Wonky": 0}},
    "playfair": {"nome": "Playfair itálico", "arquivo": "posts/PlayfairDisplay-Italic.ttf", "regular": {"Weight": 400}, "negrito": {"Weight": 800}, "escala": 1.06},
}
PADRAO = {"formato": "feed", "prints": 2, "fonte": "dmsans", "pb": False, "assinatura": ""}

# ------------------------------------------------------------ escolher as frases

MULETAS_INICIO = re.compile(r"^(então|entao|tipo|cara|mano|olha|né|ne|aí|ai|bom|enfim|é|e aí|e ai|tá|ta|ó|velho|véi|vei|gente|galera|pessoal|chat)\b[,!.]?\s*", re.I)
MULETAS_MEIO = re.compile(r",?\s\b(né|tipo assim|sabe\?|tá ligado\??|entendeu\??|cara|mano|velho)\b,?(?=\s|$)", re.I)
FORA = re.compile(r"\b(chat|inscrev\w*|sub|subs|pix|link|cupom|desconto|live|stream\w*|doa\w*|sininho|segue|seguir|follow|merch\w*|patrocin\w*|ativa|ativem|clipa\w*|twitch|kick|youtube)\b", re.I)
PALAVRAO = re.compile(r"\b(porra|caralho|merda|foda\w*|fodid\w*|puta|put\w|buceta|cu|viad\w*|desgraç\w*|arromb\w*|vagabund\w*|piranha|otári\w*)\b", re.I)
CONTRASTE = re.compile(r"\b(mas|porém|só que|quanto mais|quanto menos|nunca|sempre|ninguém|todo mundo|o segredo|a verdade|o problema|o que importa|a diferença|não é|se você|quem não|quem quer|o maior|o melhor|o pior)\b", re.I)
CONSELHO = re.compile(r"^(seja|faça|faz|pare|para de|comece|aprenda|nunca|não|confie|acredite|trabalhe|tenha|lembre|esqueça|cuide|foque|escolha|aceite)\b", re.I)
JOGO = re.compile(r"\b(chefe|boss|missão|mapa|arma|kill\w*|partida|round|fase|inimigo|personagem|skin|loot|respawn)\b", re.I)
PESO = re.compile(r"^(ningu|nunca|sempre|tudo|nada|rico|pobre|sucesso|fracass|medo|coragem|deus|senhor|amor|vida|dinheiro|sonho|verdade|mentira|processo|resultado|disciplina|foco|tempo|famíl|famil|felic|liberdade|campe|vitória|vitoria|derrota)")
INTENSOS = {"mais", "menos", "nunca", "sempre", "muito", "tão", "nada", "tudo", "maior", "melhor", "pior", "único", "unica", "única"}


def limpar(texto: str) -> str:
    t = re.sub(r"\s+", " ", texto).strip()
    for _ in range(3):
        t = MULETAS_INICIO.sub("", t).strip()
    t = MULETAS_MEIO.sub("", t)
    t = re.sub(r"\s+([,.!?])", r"\1", re.sub(r"\s+", " ", t)).strip(" ,;")
    if not t:
        return ""
    if t[-1] not in ".!?":
        t += "."
    return t[0].upper() + t[1:]


def _nota(texto: str) -> float | None:
    palavras = texto.split()
    n = len(palavras)
    if n < 7 or n > 26 or FORA.search(texto) or PALAVRAO.search(texto):
        return None
    primeiras = [ctx._nucleo(p) for p in palavras[:3]]
    if primeiras[0] in ctx.CONECTIVOS or any(p in ctx.ANAFORAS for p in primeiras):
        return None  # depende do que veio antes: não funciona sozinha no feed
    nota = 2.0 - abs(n - 14) / 8
    nota += 2.0 if CONTRASTE.search(texto) else 0
    nota += 1.5 if CONSELHO.search(texto) else 0
    nota += 1.0 if re.search(r"\d", texto) else 0
    nota += 1.0 if ctx.FORTES.search(texto) else 0
    nota += 1.0 if re.search(r"\bvocê\b", texto, re.I) else 0
    nota += 1.0 if texto.endswith("!") else .4 if texto.endswith("?") else 0
    nota -= .8 if JOGO.search(texto) else 0
    return nota


def candidatas(palavras: list[dict], limite: int = 4) -> list[dict]:
    """As melhores frases de um trecho, uma ou duas frases faladas juntas, com o tempo de cada palavra."""
    lista = ctx.frases(palavras)
    opcoes = []
    for i, f in enumerate(lista):
        for j in (i, i + 1):
            if j >= len(lista) or (j > i and ctx._fronteira(lista, j) >= .9):
                continue
            if j > i:  # duas frases só quando a primeira é curta ou a segunda vira o jogo ("mas", "porque")
                segunda = ctx._nucleo(lista[j]["texto"].split()[0])
                if len(lista[i]["texto"].split()) >= 10 and segunda not in ("mas", "porque", "então", "entao", "só", "so"):
                    continue
            bruto = " ".join(x["texto"] for x in lista[i:j + 1])
            texto = limpar(bruto)
            nota = _nota(texto) if texto else None
            if nota is None:
                continue
            ini, fim = lista[i]["ini"], lista[j]["fim"]
            opcoes.append({"texto": texto, "original": bruto, "ini": round(ini, 2), "fim": round(fim, 2), "nota": round(nota - 1.0 * (j - i), 2)})
    escolhidas: list[dict] = []
    for o in sorted(opcoes, key=lambda o: -o["nota"]):
        if all(o["fim"] <= e["ini"] or o["ini"] >= e["fim"] for e in escolhidas):
            escolhidas.append(o)
        if len(escolhidas) >= limite:
            break
    return escolhidas


# ------------------------------------------------------------ dividir e destacar

def dividir(texto: str, n: int) -> list[str]:
    """Divide em `n` partes parecidas, de preferência na pontuação ou antes de "mas", "e", "porque"."""
    palavras = texto.split()
    if n <= 1 or len(palavras) < n * 2:
        return [texto]
    total = len(texto)
    melhor, nota_melhor = None, 1e9

    def custo_corte(k: int) -> float:
        antes, depois = palavras[k - 1], ctx._nucleo(palavras[k])
        c = 0.0
        if antes[-1] in ".!?;:":
            c -= 30
        elif antes[-1] == ",":
            c -= 22
        if depois in ("mas", "e", "porque", "quando", "se", "que", "então", "pra", "para"):
            c -= 5
        if ctx._nucleo(antes) in ctx.FRACAS or ctx._nucleo(antes) in INTENSOS:
            c += 12  # não deixa "de", "o", "mais" no fim de uma parte
        return c

    def tamanho(a: int, b: int) -> int:
        return len(" ".join(palavras[a:b]))

    cortes = [(k,) for k in range(2, len(palavras) - 1)] if n == 2 else [(a, b) for a in range(2, len(palavras) - 3) for b in range(a + 2, len(palavras) - 1)]
    for c in cortes:
        pontos = (0, *c, len(palavras))
        tams = [tamanho(a, b) for a, b in zip(pontos, pontos[1:])]
        nota = (max(tams) - min(tams)) * .6 + sum(custo_corte(k) for k in c) + max(0, max(tams) - (64 if n == 2 else 46)) * 2
        if nota < nota_melhor:
            melhor, nota_melhor = pontos, nota
    if not melhor:
        return [texto]
    partes = [" ".join(palavras[a:b]) for a, b in zip(melhor, melhor[1:])]
    return [p[0].upper() + p[1:] if k == 0 else p for k, p in enumerate(partes)] if total else partes


def destacar(parte: str) -> str:
    """Põe em negrito (com **) as palavras que carregam o sentido: o contraste, o número, a palavra forte."""
    palavras = parte.split()
    notas = []
    for k, p in enumerate(palavras):
        n = ctx._nucleo(p)
        if len(n) < 3 or n in ctx.VAZIAS:
            notas.append(-1.0)
            continue
        nota = len(n) / 4
        nota += 3 if ctx.FORTES.search(p) else 0
        nota += 3 if re.search(r"\d", p) else 0
        nota += 2 if k and ctx._nucleo(palavras[k - 1]) in INTENSOS else 0
        nota += 2 if PESO.search(n) else 0
        nota += .5 if k == len(palavras) - 1 else 0
        notas.append(nota)
    quantos = 1 if len(palavras) < 6 else 2
    escolhidas = sorted((i for i in range(len(palavras)) if notas[i] > 0), key=lambda i: -notas[i])[:quantos]
    marcadas = set(escolhidas)
    for i in list(marcadas):
        if i and ctx._nucleo(palavras[i - 1]) in INTENSOS:
            marcadas.add(i - 1)  # "mais barato", "nunca desiste"
    saida, k = [], 0
    while k < len(palavras):
        if k in marcadas:
            fim = k
            while fim + 1 in marcadas:
                fim += 1
            grupo = " ".join(palavras[k:fim + 1])
            pont = re.match(r"^(.*?)([.,!?;:]*)$", grupo)
            saida.append(f"**{pont[1]}**{pont[2]}")
            k = fim + 1
        else:
            saida.append(palavras[k]); k += 1
    return " ".join(saida)


def tokens(texto: str) -> list[tuple[str, bool]]:
    """Palavras e se estão em negrito, a partir da marcação com **."""
    saida, negrito = [], False
    for pedaco in re.split(r"(\*\*)", texto):
        if pedaco == "**":
            negrito = not negrito
            continue
        for k, p in enumerate(pedaco.split()):
            if saida and re.fullmatch(r"[.,!?;:…]+", p) and k == 0 and not pedaco[:1].isspace():
                saida[-1] = (saida[-1][0] + p, saida[-1][1])  # "**clientes**." fica junto, sem espaço antes do ponto
            else:
                saida.append((p, negrito))
    return saida


def partes_de(frase: dict, n: int) -> list[str]:
    salvas = (frase.get("partes") or {}).get(str(n))
    return salvas if salvas and len(salvas) == n else [destacar(p) for p in dividir(frase["texto"], n)]


def tempos_das_partes(frase: dict, n: int) -> list[float]:
    """Quando cada parte foi dita, pelo tamanho dela dentro da frase."""
    partes = [re.sub(r"\*", "", p) for p in partes_de(frase, n)]
    total = sum(len(p) for p in partes) or 1
    ini, fim = float(frase["ini"]), float(frase["fim"])
    tempos, pos = [], 0
    for p in partes:
        tempos.append(ini + (fim - ini) * (pos + len(p) / 2) / total)
        pos += len(p)
    return tempos


# ------------------------------------------------------------ prints

def _quadros(video: Path, ini: float, fim: float, fps: float = 3.0, maximo: int = 14) -> list[tuple[float, np.ndarray]]:
    w, h, dur = cam.dimensoes(video)
    escala = min(1.0, 1920 / max(w, h))
    lw, lh = int(w * escala) // 2 * 2, int(h * escala) // 2 * 2
    ini = max(0.0, ini)
    dur_janela = max(.4, min(fim, dur or fim) - ini)
    fps = min(fps, maximo / dur_janela) if dur_janela * fps > maximo else fps
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{ini:.3f}", "-i", str(video), "-t", f"{dur_janela:.3f}", "-an", "-vf", f"fps={fps:.4f},scale={lw}:{lh}",
                        "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True, **sem_janela())
    tam = lw * lh * 3
    return [(ini + k / fps, np.frombuffer(r.stdout, np.uint8, tam, k * tam).reshape(lh, lw, 3)) for k in range(len(r.stdout) // tam)]


def _nota_quadro(q: np.ndarray) -> tuple[float, list[float] | None]:
    """Rosto grande e nítido ganha. Sem rosto, ainda serve como reserva."""
    h, w = q.shape[:2]
    rostos = cam.detectar_rostos(q, .55)
    cinza = cv2.cvtColor(q, cv2.COLOR_BGR2GRAY)
    if not rostos:
        return float(np.log1p(cv2.Laplacian(cinza, cv2.CV_64F).var())) * .1, None
    x, y, rw, rh = max(rostos, key=lambda r: r[2] * r[3])
    x0, y0, x1, y1 = int(x * w), int(y * h), int((x + rw) * w), int((y + rh) * h)
    face = cinza[max(0, y0):max(1, y1), max(0, x0):max(1, x1)]
    nitidez = float(np.log1p(cv2.Laplacian(face, cv2.CV_64F).var())) if face.size else 0.0
    borda = 1.0 if .06 < x + rw / 2 < .94 and y > .01 else .5
    return 3 + nitidez * .6 + min(3.0, rh * 10) * borda, [x0, y0, x1 - x0, y1 - y0]


def _gravar_print(pasta: Path, q: np.ndarray) -> str:
    pid = "p" + uuid.uuid4().hex[:10]
    cv2.imwrite(str(pasta / f"{pid}.jpg"), q, [cv2.IMWRITE_JPEG_QUALITY, 92])
    mini = cv2.resize(q, (320, max(1, int(320 * q.shape[0] / q.shape[1]))), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(pasta / f"{pid}_mini.jpg"), mini, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return pid


def prints_da_frase(video: Path, pasta: Path, frase: dict, banco: dict) -> list[str]:
    """Os melhores quadros perto da frase, do melhor para o pior, espalhados no tempo."""
    notas = []
    for t, q in _quadros(video, frase["ini"] - 1.2, frase["fim"] + 1.2):
        nota, rosto = _nota_quadro(q)
        notas.append((nota, t, q, rosto))
    escolhidos: list[tuple] = []
    for item in sorted(notas, key=lambda x: -x[0]):
        if all(abs(item[1] - e[1]) >= .6 for e in escolhidos):
            escolhidos.append(item)
        if len(escolhidos) >= 6:
            break
    ids = []
    for nota, t, q, rosto in escolhidos:
        pid = _gravar_print(pasta, q)
        banco[pid] = {"t": round(t, 2), "rosto": rosto, "nota": round(nota, 2), "lar": q.shape[1], "alt": q.shape[0]}
        ids.append(pid)
    return ids


def escolher_prints(frase: dict, banco: dict, n: int, manuais: list | None = None) -> list[str]:
    """Um print por parte: o de nota boa mais perto de quando a parte foi dita, sem repetir."""
    if manuais and len(manuais) == n and all(p in banco for p in manuais):
        return list(manuais)
    opcoes = [p for p in frase.get("prints") or [] if p in banco] or [p for p in banco]
    if not opcoes:
        return []
    saida = []
    for t in tempos_das_partes(frase, n):
        livres = [p for p in opcoes if p not in saida] or opcoes
        saida.append(max(livres, key=lambda p: banco[p]["nota"] - abs(banco[p]["t"] - t) * .8))
    return saida


# ------------------------------------------------------------ arte

_fontes: dict = {}
_imagens: "OrderedDict[str, Image.Image]" = OrderedDict()


def _fonte(chave: str, tamanho: int, negrito: bool) -> ImageFont.FreeTypeFont:
    fam = FONTES.get(chave) or FONTES[PADRAO["fonte"]]
    tamanho = max(8, round(tamanho * fam.get("escala", 1.0)))
    k = (chave, tamanho, negrito)
    if k not in _fontes:
        arquivo = fam.get("arquivo_negrito") if negrito and fam.get("arquivo_negrito") else fam["arquivo"]
        try:
            f = ImageFont.truetype(str(PASTA_FONTES / arquivo), tamanho)
            eixos = fam.get("negrito" if negrito else "regular")
            if eixos:
                try:
                    f.set_variation_by_axes([eixos.get(a["name"].decode() if isinstance(a["name"], bytes) else a["name"], a["default"]) for a in f.get_variation_axes()])
                except (OSError, AttributeError):
                    pass
        except OSError:
            f = ImageFont.truetype(str(PASTA_FONTES / ("Poppins-Bold.ttf" if negrito else "Poppins-Regular.ttf")), tamanho)
        _fontes[k] = f
    return _fontes[k]


def fontes() -> list[dict]:
    return [{"id": k, "nome": v["nome"]} for k, v in FONTES.items() if (PASTA_FONTES / v["arquivo"]).exists()]


def _abrir(caminho: Path) -> Image.Image:
    k = str(caminho)
    if k not in _imagens:
        im = Image.open(caminho); im.load()
        _imagens[k] = im.convert("RGB")
        while len(_imagens) > 40:
            _imagens.popitem(last=False)
    _imagens.move_to_end(k)
    return _imagens[k]


def _recorte(fw: int, fh: int, pw: int, ph: int, rosto: list | None) -> tuple:
    ar = pw / ph
    cw, ch = (fh * ar, fh) if fw / fh > ar else (fw, fw / ar)
    if rosto:
        alvo = .48 if ar >= 1.2 else .3  # o rosto ocupa quase metade do print deitado
        z = max(1.0, min(alvo * ch / max(1.0, rosto[3]), cw / (pw / 1.6)))
        cw, ch = cw / z, ch / z
        cx, cy = rosto[0] + rosto[2] / 2, rosto[1] + rosto[3] / 2
        x0, y0 = cx - cw / 2, cy - .36 * ch
    else:
        x0, y0 = (fw - cw) / 2, (fh - ch) * .4
    x0 = min(max(0.0, x0), fw - cw); y0 = min(max(0.0, y0), fh - ch)
    return (x0, y0, x0 + cw, y0 + ch)


def _linhas(toks, fn_r, fn_b, largura: float, maximo: int) -> list | None:
    esp = fn_r.getlength(" ")
    lw = [(fn_b if b else fn_r).getlength(p) for p, b in toks]
    k = len(toks)
    larg = lambda a, b: sum(lw[a:b]) + esp * max(0, b - a - 1)
    if larg(0, k) <= largura:
        return [toks]
    melhor = None
    for n in range(2, maximo + 1):
        cortes = ([0, i, k] for i in range(1, k)) if n == 2 else ([0, i, j, k] for i in range(1, k - 1) for j in range(i + 1, k))
        for c in cortes:
            ws = [larg(a, b) for a, b in zip(c, c[1:])]
            if max(ws) <= largura:
                nota = max(ws) + (.15 * (ws[-1] - ws[0]) if ws[-1] > ws[0] else 0)
                if melhor is None or nota < melhor[0]:
                    melhor = (nota, c)
        if melhor:
            return [toks[a:b] for a, b in zip(melhor[1], melhor[1][1:])]
    return None


def _texto(desenho: ImageDraw.ImageDraw, texto: str, fonte: str, tamanho: int, base_y: float, largura_total: int) -> float:
    """Desenha centralizado, com a última linha em `base_y`. Devolve o topo do bloco."""
    toks = tokens(texto)
    t = tamanho
    while True:
        fr, fb = _fonte(fonte, t, False), _fonte(fonte, t, True)
        linhas = _linhas(toks, fr, fb, largura_total - 2 * MARGEM, 3)
        if linhas or t <= tamanho * .65:
            break
        t -= 2
    if not linhas:
        linhas = [toks]
    entre, esp = t * 1.22, fr.getlength(" ")
    for i, linha in enumerate(linhas):
        y = base_y - (len(linhas) - 1 - i) * entre
        ws = [(fb if b else fr).getlength(p) for p, b in linha]
        x = (largura_total - (sum(ws) + esp * (len(linha) - 1))) / 2
        for (p, b), w in zip(linha, ws):
            desenho.text((x + 2, y + 3), p, font=fb if b else fr, fill=(0, 0, 0, 110), anchor="ls")  # sombra leve, para ler em fundo claro
            desenho.text((x, y), p, font=fb if b else fr, fill=(255, 255, 255, 255), anchor="ls")
            x += w + esp
    return base_y - (len(linhas) - 1) * entre - t


def montar(itens: list[dict], formato: str = "feed", fonte: str = "dmsans", pb: bool = False, assinatura: str = "") -> Image.Image:
    """`itens`: [{"imagem": caminho, "rosto": [x, y, w, h] ou None, "texto": "parte com **negrito**"}]."""
    W, H = FORMATOS.get(formato, FORMATOS["feed"])
    util = H - (RESPIRO_STORIES if formato == "stories" else 0)
    n = max(1, len(itens))
    tamanho = TAMANHO_TEXTO.get((formato, n), 50)
    tela = Image.new("RGB", (W, H), (10, 10, 10))
    altura = util // n
    for k, item in enumerate(itens):
        ph = altura if k < n - 1 else util - altura * (n - 1)
        foto = _abrir(Path(item["imagem"]))
        caixa = _recorte(foto.width, foto.height, W, ph, item.get("rosto"))
        pedaco = foto.crop(tuple(int(round(v)) for v in caixa)).resize((W, ph), Image.LANCZOS)
        if pb:
            pedaco = ImageOps.grayscale(pedaco).convert("RGB")
        claro = float(np.asarray(pedaco.crop((0, int(ph * .55), W, ph)).convert("L")).mean()) / 255
        degrade = np.linspace(0, 1, ph, dtype=np.float32)
        alfa = np.clip((degrade - .38) / .62, 0, 1) ** 1.3 * (.72 + .2 * claro)  # fundo claro pede um degradê mais forte
        escuro = (np.asarray(pedaco, np.float32) * (1 - alfa[:, None, None])).astype(np.uint8)
        pedaco = Image.fromarray(escuro)
        camada = Image.new("RGBA", (W, ph), (0, 0, 0, 0))
        d = ImageDraw.Draw(camada)
        base = ph - (54 if n > 1 else 80) - (44 if assinatura and k == n - 1 else 0)
        _texto(d, item["texto"], fonte, tamanho, base, W)
        if assinatura and k == n - 1:
            f = _fonte(fonte, 28, True)
            d.text((W / 2, ph - 34), assinatura if assinatura.startswith("@") else f"@{assinatura}", font=f, fill=(255, 255, 255, 190), anchor="ms")
        pedaco = Image.alpha_composite(pedaco.convert("RGBA"), camada).convert("RGB")
        tela.paste(pedaco, (0, altura * k))
        if k:
            ImageDraw.Draw(tela).rectangle((0, altura * k - 1, W, altura * k + 1), fill=(0, 0, 0))
    return tela


# ------------------------------------------------------------ guardar e entregar

class Posts:
    """Os posts de cada corte ficam na pasta dele: posts.json e posts/<print>.jpg."""

    def __init__(self, motor):
        self.motor = motor

    def _pasta(self, corte: str) -> Path:
        if corte not in self.motor.cortes:
            raise KeyError(corte)
        p = self.motor.saida / corte / "posts"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def ler(self, corte: str) -> dict | None:
        arq = self.motor.saida / corte / "posts.json"
        try:
            return json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _gravar(self, corte: str, doc: dict) -> None:
        (self.motor.saida / corte / "posts.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def _palavras(self, meta: dict) -> list[dict]:
        return [p for g in meta.get("grupos") or [] for p in g.get("palavras") or []]

    def listar(self, pasta: str = "") -> dict:
        with self.motor.trava:
            cortes = [m for m in self.motor.cortes.values() if m.get("status") == "pronto" and not m.get("montagem") and (not pasta or m.get("pasta") == pasta)]
        saida, frases = [], []
        for m in sorted(cortes, key=lambda m: -m["criado"]):
            doc = self.ler(m["id"])
            saida.append({"id": m["id"], "gancho": m.get("gancho") or "", "canal": m.get("canal") or "", "pronto": bool(doc), "frases": len((doc or {}).get("frases") or [])})
            for f in (doc or {}).get("frases") or []:
                frases.append({**{k: v for k, v in f.items() if k not in ("prints",)}, "corte": m["id"], "canal": m.get("canal") or "", "credito": m.get("credito") or m.get("canal") or ""})
        return {"cortes": saida, "frases": frases, "fontes": fontes()}

    def gerar(self, corte: str, refazer: bool = False) -> dict:
        """Encontra as frases do corte e já separa os prints de cada uma."""
        meta = self.motor.cortes[corte]
        doc = self.ler(corte)
        if doc and not refazer:
            return doc
        video = self.motor.saida / corte / "fonte.mp4"
        if not video.exists():
            raise ValueError("O vídeo original deste corte não está mais na pasta.")
        pasta = self._pasta(corte)
        for velho in pasta.glob("*.jpg"):
            velho.unlink(missing_ok=True)
        banco: dict = {}
        frases = []
        for c in candidatas(self._palavras(meta)):
            c["id"] = "f" + uuid.uuid4().hex[:8]
            c["prints"] = prints_da_frase(video, pasta, c, banco)
            c["legenda"] = self.legenda(meta, c["texto"])
            frases.append(c)
        doc = {"frases": frases, "banco": banco}
        if not frases:
            doc["aviso"] = "Este corte não tem uma frase que funcione sozinha num post (fala curta, só reação ou assunto do chat)."
        self._gravar(corte, doc)
        return doc

    def legenda(self, meta: dict, texto: str) -> str:
        marca = re.sub(r"[^0-9a-zA-Z]", "", meta.get("canal") or "").lower()
        credito = meta.get("credito") or meta.get("canal") or ""
        return f"{texto}\n\n{'Créditos: ' + credito if credito else ''}\n\n#frases #reflexão #motivação{' #' + marca if marca else ''}".replace("\n\n\n\n", "\n\n")

    def minha_frase(self, corte: str, texto: str) -> dict:
        """Uma frase escrita pela pessoa, com os melhores rostos do corte."""
        texto = limpar(str(texto)[:220])
        if len(texto.split()) < 3:
            raise ValueError("Escreva uma frase com pelo menos três palavras.")
        meta = self.motor.cortes[corte]
        doc = self.ler(corte) or self.gerar(corte)
        if not doc.get("banco"):
            video = self.motor.saida / corte / "fonte.mp4"
            dur = cam.dimensoes(video)[2] or meta.get("duracao") or 20
            doc["banco"] = {}
            prints_da_frase(video, self._pasta(corte), {"ini": 0.0, "fim": float(dur)}, doc["banco"])
        melhores = sorted(doc["banco"], key=lambda p: -doc["banco"][p]["nota"])[:6]
        nova = {"id": "f" + uuid.uuid4().hex[:8], "texto": texto, "original": "", "ini": 0.0, "fim": 0.0, "nota": 0, "propria": True,
                "prints": melhores, "legenda": self.legenda(meta, texto), "escolhida": True}
        doc["frases"].insert(0, nova)
        doc.pop("aviso", None)
        self._gravar(corte, doc)
        return nova

    def salvar(self, corte: str, frase_id: str, dados: dict) -> dict:
        doc = self.ler(corte) or {}
        f = next((x for x in doc.get("frases") or [] if x["id"] == frase_id), None)
        if not f:
            raise KeyError(frase_id)
        if isinstance(dados.get("partes"), list) and dados["partes"]:
            n = len(dados["partes"])
            f.setdefault("partes", {})[str(n)] = [str(p)[:160] for p in dados["partes"]]
        if isinstance(dados.get("prints"), list):
            f.setdefault("manuais", {})[str(len(dados["prints"]))] = [str(p) for p in dados["prints"]]
        if "escolhida" in dados:
            f["escolhida"] = bool(dados["escolhida"])
        if isinstance(dados.get("legenda"), str):
            f["legenda"] = dados["legenda"][:2200]
        if dados.get("apagar"):
            doc["frases"] = [x for x in doc["frases"] if x["id"] != frase_id]
        self._gravar(corte, doc)
        return {k: v for k, v in f.items()}

    def arte(self, corte: str, frase_id: str, opcoes: dict) -> Image.Image:
        doc = self.ler(corte)
        if not doc:
            raise ValueError("Encontre as frases deste corte primeiro.")
        f = next((x for x in doc["frases"] if x["id"] == frase_id), None)
        if not f:
            raise KeyError(frase_id)
        n = int(opcoes.get("prints") or PADRAO["prints"])
        n = n if n in (1, 2, 3) else 2
        partes = opcoes.get("partes") if isinstance(opcoes.get("partes"), list) and len(opcoes["partes"]) == n else partes_de(f, n)
        ids = escolher_prints(f, doc.get("banco") or {}, n, opcoes.get("prints_ids") or (f.get("manuais") or {}).get(str(n)))
        if len(ids) < n:
            raise ValueError("Não achei quadros suficientes neste corte.")
        pasta = self._pasta(corte)
        itens = [{"imagem": pasta / f"{pid}.jpg", "rosto": doc["banco"][pid].get("rosto"), "texto": str(t)} for pid, t in zip(ids, partes)]
        return montar(itens, opcoes.get("formato") if opcoes.get("formato") in FORMATOS else "feed", opcoes.get("fonte") or PADRAO["fonte"], bool(opcoes.get("pb")), str(opcoes.get("assinatura") or "")[:40])

    def detalhes(self, corte: str, frase_id: str, n: int) -> dict:
        doc = self.ler(corte) or {}
        f = next((x for x in doc.get("frases") or [] if x["id"] == frase_id), None)
        if not f:
            raise KeyError(frase_id)
        n = n if n in (1, 2, 3) else 2
        todos = list(dict.fromkeys([*(f.get("prints") or []), *sorted(doc.get("banco") or {}, key=lambda p: -doc["banco"][p]["nota"])]))[:12]
        return {"frase": f, "partes": partes_de(f, n), "prints": escolher_prints(f, doc.get("banco") or {}, n, (f.get("manuais") or {}).get(str(n))), "opcoes": todos}

    def imagem(self, corte: str, pid: str) -> Path | None:
        if not re.fullmatch(r"p[0-9a-f]{10}(_mini)?", pid or ""):
            return None
        alvo = self.motor.saida / corte / "posts" / f"{pid}.jpg"
        return alvo if corte in self.motor.cortes and alvo.exists() else None

    def pacote(self, itens: list[dict]) -> tuple[bytes, str]:
        """Um .zip com os PNG (na ordem pedida: vira carrossel) e as legendas prontas para copiar."""
        if not itens:
            raise ValueError("Escolha pelo menos uma frase.")
        saida = io.BytesIO()
        legendas = []
        with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
            for k, it in enumerate(itens[:30], 1):
                img = self.arte(str(it["corte"]), str(it["frase"]), it)
                buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
                z.writestr(f"{k:02d}.png", buf.getvalue())
                f = next((x for x in (self.ler(str(it["corte"])) or {}).get("frases") or [] if x["id"] == it["frase"]), {})
                legendas.append(f"--- {k:02d}.png ---\n{f.get('legenda') or f.get('texto') or ''}")
            z.writestr("legendas.txt", "\n\n".join(legendas))
        return saida.getvalue(), "posts-de-frase.zip"
