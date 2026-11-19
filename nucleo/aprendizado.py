"""Faz o sistema melhorar com o uso: vídeos de referência, edições do usuário e resultados do canal."""
from __future__ import annotations

import json
import statistics
import subprocess
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from . import camera as cam
from . import edicao, estilos
from .plataformas import sem_janela

CHAVES_LEGENDA = ("tamanho", "cor", "cor_destaque", "y", "maiusculas", "palavra_a_palavra", "destaque", "fonte", "entrada", "saida", "contorno")
CHAVES_GLOBAIS = ("zoom_forca", "volume_efeitos", "volume_fala", "volume_musica")
REPETICOES = 2      # uma escolha vira preferência depois de aparecer em 2 vídeos
MINIMO_VIDEOS = 5   # menos que isso não diz nada sobre o que funciona no canal
IDADE_MINIMA = 48 * 3600
INTERVALO_CANAL = 6 * 3600
LIMITE_EXEMPLOS = 200
PARECIDO = 1.0      # abaixo dessa distância, dois exemplos pertencem ao mesmo modelo
ANALISE_MAX = 180  # segundos analisados de cada vídeo de exemplo


def _amostras(video: Path, quantidade: int = 60) -> tuple[list[np.ndarray], float]:
    v = cv2.VideoCapture(str(video))
    total = int(v.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    fps = v.get(cv2.CAP_PROP_FPS) or 30
    saida = []
    for n in np.linspace(0, max(0, total - 2), quantidade).astype(int):
        v.set(cv2.CAP_PROP_POS_FRAMES, int(n))
        ok, q = v.read()
        if ok:
            saida.append(cv2.resize(q, (360, 640), interpolation=cv2.INTER_AREA))
    v.release()
    return saida, total / fps


def _cortes_por_minuto(video: Path) -> float:
    v = cv2.VideoCapture(str(video))
    fps = v.get(cv2.CAP_PROP_FPS) or 30
    passo, n, antes, marcas = max(1, round(fps / 15)), 0, None, []
    while v.grab():
        if n % passo == 0:
            ok, q = v.retrieve()
            if not ok:
                break
            g = cv2.resize(cv2.cvtColor(q, cv2.COLOR_BGR2GRAY), (54, 96)).astype(np.float32)[20:80]
            if antes is not None and float(np.abs(g - antes).mean()) > 28 and (not marcas or n / fps - marcas[-1] > .4):
                marcas.append(n / fps)
            antes = g
        n += 1
    v.release()
    return len(marcas) / max(1.0, n / fps) * 60


def _achar_webcam(quadros: list[np.ndarray]) -> dict | None:
    """A webcam é a moldura que continua parada no topo enquanto o jogo muda."""
    cinzas = np.stack([cv2.cvtColor(q, cv2.COLOR_BGR2GRAY) for q in quadros]).astype(np.float32)
    H, W = cinzas.shape[1:]
    vx = np.mean([np.abs(cv2.Sobel(c[:int(H * .3)], cv2.CV_32F, 1, 0, ksize=3)).mean(axis=0) for c in cinzas], axis=0)
    fundo = float(np.median(vx)) + 1e-3
    meio = W // 2
    esq, dir_ = int(np.argmax(vx[8:meio - 20])) + 8, int(np.argmax(vx[meio + 20:W - 8])) + meio + 20
    if vx[esq] < fundo * 2 or vx[dir_] < fundo * 2:
        return None
    vy = np.mean([np.abs(cv2.Sobel(c[:, esq + 4:dir_ - 4], cv2.CV_32F, 0, 1, ksize=3)).mean(axis=1) for c in cinzas], axis=0)
    a, b = int(H * .08), int(H * .42)
    baixo = int(np.argmax(vy[a:b])) + a
    w, h = (dir_ - esq) / W, baixo / H
    if not (.25 <= w <= .85 and .08 <= h <= .4):
        return None
    return {"x": round(esq / W, 4), "y": 0.0, "w": round(w, 4), "h": round(h, 4)}


def _achar_legenda(quadros: list[np.ndarray]) -> dict | None:
    """Mede a legenda: letras claras com contorno escuro no centro da parte de baixo."""
    H, W = quadros[0].shape[:2]
    centros, larguras, alturas, amarelas = [], [], [], 0
    for q in quadros:
        faixa = q[int(H * .45):int(H * .86)]
        branco = cv2.inRange(faixa, (225, 225, 225), (255, 255, 255))
        amarelo = cv2.inRange(faixa, (0, 175, 200), (110, 255, 255))
        escuro = cv2.dilate(cv2.inRange(faixa, (0, 0, 0), (45, 45, 45)), np.ones((3, 3), np.uint8))
        for mascara, cor in ((branco, False), (amarelo, True)):
            letras = cv2.bitwise_and(cv2.dilate(mascara, np.ones((3, 3), np.uint8)), escuro)
            junto = cv2.morphologyEx(letras, cv2.MORPH_CLOSE, np.ones((5, 13), np.uint8))
            n, _, st, _ = cv2.connectedComponentsWithStats(junto)
            blocos = [s for s in st[1:] if 12 <= s[3] <= 70 and s[2] >= 24 and abs(s[0] + s[2] / 2 - W / 2) < W * .16 and s[4] > 90]
            if blocos:
                s = max(blocos, key=lambda x: x[4])
                centros.append((s[1] + s[3] / 2 + H * .45) / H); larguras.append(s[2] / W); alturas.append(s[3] / H); amarelas += int(cor)
                break
    if len(centros) < len(quadros) * .25:
        return None
    return {"y": round(statistics.median(centros), 4), "largura": round(statistics.median(larguras), 3), "altura": round(statistics.median(alturas), 4), "amarelo": amarelas / len(centros)}


def _achar_barra(quadros: list[np.ndarray]) -> bool:
    H = quadros[0].shape[0]
    parte = np.stack([cv2.cvtColor(q[int(H * .86):int(H * .97)], cv2.COLOR_BGR2GRAY) for q in quadros]).astype(np.float32)
    return float((parte.std(axis=0) < 14).mean()) > .3


def _picos_de_som(video: Path) -> tuple[list[float], list[str]]:
    """Encontra golpes de som agudos e separa os que crescem (whoosh) dos secos (impacto)."""
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-t", str(ANALISE_MAX), "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True, **sem_janela()).stdout
    audio = np.frombuffer(pcm[: len(pcm) // 2 * 2], np.int16).astype(np.float32) / 32768
    if len(audio) < 16000:
        return [], []
    tam, passo = 512, 256
    janelas = np.lib.stride_tricks.sliding_window_view(audio, tam)[::passo] * np.hanning(tam)
    agudo = np.abs(np.fft.rfft(janelas, axis=1))[:, 48:].sum(axis=1)
    fluxo = np.maximum(0, np.diff(agudo, prepend=agudo[0]))
    corte = max(float(np.median(fluxo) + 8 * (np.median(np.abs(fluxo - np.median(fluxo))) + 1e-6)), float(np.median(agudo)) * 3, 1.5)
    tempos, tipos, ultimo = [], [], -9
    for n in np.flatnonzero(fluxo > corte):
        if n - ultimo < 16:
            continue
        ultimo = int(n)
        topo = float(agudo[n:n + 8].max()) + 1e-6
        tempos.append(n * passo / 16000); tipos.append("whoosh" if float(agudo[max(0, n - 10)]) > topo * .3 else "impacto")
    return tempos, tipos


def medir_edicao(video: Path) -> dict:
    """Mede como o vídeo foi editado: trocas de cena, transições, zooms e efeitos sonoros."""
    v = cv2.VideoCapture(str(video))
    fps = v.get(cv2.CAP_PROP_FPS) or 30
    passo, n, cinzas = max(1, round(fps / 15)), 0, []
    while v.grab() and n / fps < ANALISE_MAX:
        if n % passo == 0:
            ok, q = v.retrieve()
            if not ok:
                break
            cinzas.append(cv2.cvtColor(cv2.resize(q, (135, 240), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY))
        n += 1
    v.release()
    dt = passo / fps
    if len(cinzas) < 20:
        return {}
    area = [c[50:205].astype(np.float32) for c in cinzas]  # ignora legenda fixa e barra do canal
    dif = np.array([0.0, *[float(np.abs(a - b).mean()) for a, b in zip(area, area[1:])]])
    borrado = [cv2.resize(a, (27, 31), interpolation=cv2.INTER_AREA).flatten() for a in area]
    parecido = lambda i: float(np.corrcoef(borrado[i - 1], borrado[i])[0, 1]) if borrado[i - 1].std() > 1 and borrado[i].std() > 1 else 0.0
    def continua(i: int) -> bool:
        """Em zoom e movimento os mesmos pontos seguem visíveis no quadro seguinte."""
        pts = cv2.goodFeaturesToTrack(cinzas[i - 1], 60, .02, 6)
        if pts is None or len(pts) < 10:
            return False
        novos, ok, erro = cv2.calcOpticalFlowPyrLK(cinzas[i - 1], cinzas[i], pts, None, winSize=(21, 21), maxLevel=3)
        bons = (ok.flatten() == 1) & (erro.flatten() < 14)
        if int(bons.sum()) < 10:
            return False
        _, dentro = cv2.estimateAffinePartial2D(pts[bons].reshape(-1, 2), novos[bons].reshape(-1, 2), ransacReprojThreshold=2.5)
        return dentro is not None and float(dentro.sum()) / len(pts) >= .5

    cortes: list[int] = []
    for i in np.flatnonzero(dif > 26):  # zoom e movimento mantêm a imagem parecida; troca de cena não
        if (not cortes or i - cortes[-1] > 5) and parecido(int(i)) < .62 and not continua(int(i)):
            cortes.append(int(i))
    tipos: Counter = Counter()
    for i in cortes:
        a, b = max(0, i - 3), min(len(area) - 1, i + 3)
        largura = int((dif[a:b + 1] > 11).sum())
        claro = max(float(area[j].mean()) for j in range(a, b + 1)) - max(float(area[a].mean()), float(area[b].mean()))
        if claro > 30:
            tipos["clarao"] += 1
        elif largura <= 2:
            tipos["corte"] += 1
        else:
            desl, _ = cv2.phaseCorrelate(area[max(0, i - 1)], area[min(len(area) - 1, i + 1)])
            tipos["chicote" if float(np.hypot(*desl)) > 7 else "suave"] += 1
    escalas = np.ones(len(cinzas))
    separados = set(j for i in cortes for j in range(i - 1, i + 2))
    for i in range(1, len(cinzas)):
        if i in separados:
            continue
        pts = cv2.goodFeaturesToTrack(cinzas[i - 1], 40, .02, 8)
        if pts is None or len(pts) < 8:
            continue
        novos, ok, _ = cv2.calcOpticalFlowPyrLK(cinzas[i - 1], cinzas[i], pts, None, winSize=(15, 15), maxLevel=2)
        bons = ok.flatten() == 1
        if int(bons.sum()) < 8:
            continue
        m, _ = cv2.estimateAffinePartial2D(pts[bons].reshape(-1, 2), novos[bons].reshape(-1, 2))
        if m is not None:
            escalas[i] = float(np.hypot(m[0, 0], m[1, 0]))
    zooms: list[float] = []
    i, janela = 0, 8
    while i + janela < len(escalas):
        z = float(np.prod(escalas[i:i + janela]))
        if 1.07 <= z <= 1.9:
            zooms.append(z); i += 15
        else:
            i += 1
    picos, sons = _picos_de_som(video)
    marcas = [c * dt for c in cortes]
    com_som = sum(any(abs(p - t) <= .2 for p in picos) for t in marcas)
    dur = max(1.0, len(cinzas) * dt)
    return {"zooms_min": round(len(zooms) / dur * 60, 1), "zoom_escala": round(float(np.median(zooms)), 3) if zooms else None, "cena_s": round(dur / (len(cortes) + 1), 1),
            "transicoes": {k: round(v / max(1, len(cortes)), 2) for k, v in tipos.items()}, "sfx_cortes": round(com_som / len(marcas), 2) if marcas else None, "sfx_min": round(len(picos) / dur * 60, 1),
            "whoosh": round(sons.count("whoosh") / len(sons), 2) if sons else None}


def medir_video(video: Path, palavras: list[dict] | None = None) -> dict:
    quadros, dur = _amostras(video)
    if len(quadros) < 8:
        raise ValueError("Não consegui ler este vídeo.")
    leg = _achar_legenda(quadros)
    edicao_medida = medir_edicao(video)
    return {"duracao": round(dur, 1), "vertical": True, "cortes_min": round(60 / edicao_medida["cena_s"], 1) if edicao_medida.get("cena_s") else round(_cortes_por_minuto(video), 1), "webcam": _achar_webcam(quadros), "legenda": leg,
            "palavra_a_palavra": bool(leg and leg["largura"] < .3), "barra": _achar_barra(quadros), "palavras_s": round(len(palavras) / max(1.0, dur), 2) if palavras is not None else None, **edicao_medida}


def distancia(a: dict, b: dict) -> float:
    """Compara o jeito de editar de dois vídeos. Quanto menor, mais parecidos."""
    d = float(bool(a.get("webcam")) != bool(b.get("webcam"))) + .6 * float(bool(a.get("palavra_a_palavra")) != bool(b.get("palavra_a_palavra")))
    if a.get("cena_s") and b.get("cena_s"):
        d += abs(float(np.log2(a["cena_s"] / b["cena_s"])))
    if a.get("zooms_min") is not None and b.get("zooms_min") is not None:
        d += min(1.0, abs(a["zooms_min"] - b["zooms_min"]) / 15) * .5
    if a.get("sfx_cortes") is not None and b.get("sfx_cortes") is not None:
        d += abs(a["sfx_cortes"] - b["sfx_cortes"]) * .8
    ta, tb = a.get("transicoes") or {}, b.get("transicoes") or {}
    if ta and tb and max(ta, key=ta.get) != max(tb, key=tb.get):
        d += .7
    if (a.get("legenda") or {}).get("y") and (b.get("legenda") or {}).get("y"):
        d += min(1.0, abs(a["legenda"]["y"] - b["legenda"]["y"]) / .15) * .5
    return d


def nome_do_estilo(p: dict) -> str:
    cena = p.get("cena_s") or 60 / max(1.0, p.get("cortes_min") or 10)
    partes = ["Ritmo rápido" if cena < 3 else "Ritmo dinâmico" if cena < 6 else "Ritmo calmo"]
    if p.get("webcam"):
        partes.append("câmera em cima")
    troca = (p.get("transicoes") or [None])[0]
    if troca in ("clarao", "chicote"):
        partes.append("com clarão" if troca == "clarao" else "com chicote")
    if (p.get("zooms_min") or 0) >= 8:
        partes.append("muito zoom")
    return ", ".join(partes)


def _par(v: float) -> int:
    return int(round(v / 2) * 2)


def plano_pip(plano: dict, pip: dict, vw: int, vh: int) -> dict:
    """Jogo em tela cheia com a webcam em cima, no lugar visto nos vídeos de referência."""
    px, py, pw, ph = _par(pip["x"] * 1080), _par(pip["y"] * 1920), _par(pip["w"] * 1080), _par(pip["h"] * 1920)
    c = plano["camera"]
    aspecto = pw / ph
    w, h = c["w"], c["h"]
    if w / h > aspecto:
        w = h * aspecto
    else:
        h = w / aspecto
    camera = {"x": _par(c["x"] + (c["w"] - w) / 2), "y": _par(c["y"] + (c["h"] - h) / 2), "w": _par(w), "h": _par(h)}
    j = plano["jogo"]
    jw = min(vw, _par(vh * 9 / 16))
    jx = _par(float(np.clip(j["x"] + j["w"] / 2 - jw / 2, 0, vw - jw)))
    return {**plano, "layout": "pip", "camera": camera, "jogo": {"x": jx, "y": 0, "w": jw, "h": _par(vh)}, "pip": {"x": px, "y": py, "w": pw, "h": ph}}


class Aprendizado:
    def __init__(self, motor):
        self.motor = motor
        self.pasta = motor.dados / "aprendizado"; self.pasta.mkdir(parents=True, exist_ok=True)
        self.arquivo = self.pasta / "memoria.json"
        self.trava = threading.RLock()
        self.m = {"ativo": {"referencias": True, "edicoes": True, "resultados": True}, "referencias": [], "edicoes": {}, "videos_editados": 0, "desempenho": {}, "pesos": {}, "canal_em": 0, "estilo_antes": None}
        try:
            self.m.update(json.loads(self.arquivo.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self.m.setdefault("modelos", {}); self.m.setdefault("uso_modelos", {}); self.m.setdefault("pesos_modelos", {})
        for r in self.m["referencias"]:
            if r.get("modelo") not in self.m["modelos"]:
                self._agrupar(r)
        self.trabalho: dict = {"estado": "parado"}
        self.fila_refs: list[dict] = []
        threading.Thread(target=self._vigiar_canal, daemon=True).start()

    def _salvar(self) -> None:
        temp = self.arquivo.with_suffix(".tmp")
        temp.write_text(json.dumps(self.m, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.arquivo)

    # ------------------------------------------------------------ modelos aprendidos

    def _exemplos(self, modelo: str) -> list[dict]:
        return [r for r in self.m["referencias"] if r.get("modelo") == modelo]

    def _agrupar(self, ref: dict) -> None:
        """Coloca o exemplo no modelo mais parecido ou cria um modelo novo."""
        melhor, menor = None, PARECIDO
        for ident in self.m["modelos"]:
            exemplos = self._exemplos(ident)
            d = sum(distancia(ref["medidas"], e["medidas"]) for e in exemplos) / len(exemplos) if exemplos else PARECIDO
            if d < menor:
                melhor, menor = ident, d
        if melhor is None:
            melhor = uuid.uuid4().hex[:8]
            self.m["modelos"][melhor] = {"nome": "", "manual": False, "ativo": True}
        ref["modelo"] = melhor
        self._nomear()

    def _nomear(self) -> None:
        usados: Counter = Counter()
        for ident, modelo in self.m["modelos"].items():
            if modelo.get("manual") or not self._exemplos(ident):
                continue
            base = nome_do_estilo(self.perfil(ident, sem_filtro=True) or {})
            usados[base] += 1
            modelo["nome"] = base if usados[base] == 1 else f"{base} {usados[base]}"

    def ativos(self) -> list[str]:
        if not self.m["ativo"]["referencias"]:
            return []
        return [i for i, m in self.m["modelos"].items() if m.get("ativo", True) and self._exemplos(i)]

    def escolher_modelo(self, meta: dict | None = None) -> str | None:
        """Reveza entre todos os modelos e usa mais os que trazem melhor resultado."""
        lista = self.ativos()
        if not lista:
            return None
        rapido = (meta or {}).get("reacao") in ("jogo", "hype", "choque", "streamer")
        with self.trava:
            uso = self.m["uso_modelos"]
            total = sum(uso.get(i, 0) for i in lista) + 1
            def prioridade(i: str) -> float:
                p = self.perfil(i) or {}
                cena = p.get("cena_s") or 6.0
                encaixe = 1.2 if rapido == (cena < 5) else 1.0
                alvo = float(self.m["pesos_modelos"].get(i, 1.0)) * float(np.sqrt(len(self._exemplos(i)))) * encaixe
                return alvo / (uso.get(i, 0) / total + .02) if len(lista) > 1 else alvo
            escolhido = max(lista, key=prioridade)
            uso[escolhido] = uso.get(escolhido, 0) + 1
            self._salvar()
        return escolhido

    def estilo_do_modelo(self, modelo: str | None) -> dict:
        """O que muda no vídeo para seguir o modelo. O que você ajustou à mão continua valendo."""
        p = self.perfil(modelo) if modelo else None
        if not p:
            return {}
        novo: dict = {}
        if p["palavra_a_palavra"]:
            novo["legenda"] = "palavra"
        if p["legenda"]:
            novo["legenda_y"], novo["legenda_x"] = round(min(.9, p["legenda"]["y"] + p["legenda"]["altura"] / 2), 4), .5
        if p["cortes_min"] >= 8:
            novo["ritmo"] = round(float(np.clip(60 / p["cortes_min"] * 1.4, 2.5, 6.0)), 1)
        if p.get("zoom_escala"):
            novo["zoom_forca"] = int(np.clip(round((p["zoom_escala"] - 1) / .15 * 100), 60, 160))
        pref = self.preferencias()
        if "y" in pref["legenda"]:
            novo.pop("legenda_y", None); novo.pop("legenda_x", None)
        if "zoom_forca" in pref["global"]:
            novo.pop("zoom_forca", None)
        return novo

    def definir_modelo(self, ident: str, dados: dict) -> dict:
        modelo = self.m["modelos"][ident]
        if isinstance(dados.get("nome"), str) and dados["nome"].strip():
            modelo.update(nome=dados["nome"].strip()[:50], manual=True)
        if "ativo" in dados:
            modelo["ativo"] = bool(dados["ativo"])
        self._salvar(); self.aplicar_estilo()
        return self.resumo()

    def remover_modelo(self, ident: str) -> dict:
        del self.m["modelos"][ident]
        self.m["referencias"] = [r for r in self.m["referencias"] if r.get("modelo") != ident]
        self.m["uso_modelos"].pop(ident, None); self.m["pesos_modelos"].pop(ident, None)
        self._nomear(); self._salvar(); self.aplicar_estilo()
        return self.resumo()

    # ------------------------------------------------------------ vídeos de referência

    def receber(self, nome: str, corpo, tamanho: int) -> dict:
        if Path(nome).suffix.lower() not in (".mp4", ".mov", ".mkv", ".webm", ".m4v"):
            raise ValueError("Envie um vídeo MP4, MOV, MKV ou WEBM.")
        arq = self.pasta / f"analise_{uuid.uuid4().hex[:10]}{Path(nome).suffix.lower()}"
        with open(arq, "wb") as f:
            restante = tamanho
            while restante > 0:
                bloco = corpo.read(min(restante, 1024 * 1024))
                if not bloco:
                    break
                f.write(bloco); restante -= len(bloco)
        if restante > 0:
            arq.unlink(missing_ok=True)
            raise ValueError("O envio foi interrompido. Tente de novo.")
        self.fila_refs.append({"nome": Path(nome).stem[:60], "arquivo": str(arq)})
        if self.trabalho.get("estado") != "analisando":
            self.trabalho = {"estado": "fila", "nome": Path(nome).stem[:60], "restantes": len(self.fila_refs)}
        self.motor.fila.put(("aprender", "referencia"))
        return self.resumo()

    def executar(self) -> None:
        if not self.fila_refs:
            return
        t = self.fila_refs.pop(0)
        arq = Path(t["arquivo"])
        self.trabalho = {"estado": "analisando", "nome": t["nome"], "restantes": len(self.fila_refs) + 1}
        try:
            palavras = None
            try:
                modelo = self.motor._modelo_whisper()
                palavras = edicao.transcrever(modelo, arq, self.motor.config["idioma"]) if modelo else None
            except Exception:
                palavras = None
            medidas = medir_video(arq, palavras)
            with self.trava:
                ref = {"id": uuid.uuid4().hex[:10], "nome": t["nome"], "criado": time.time(), "medidas": medidas}
                self.m["referencias"].append(ref)
                self.m["referencias"] = self.m["referencias"][-LIMITE_EXEMPLOS:]
                self._agrupar(ref)
                self._salvar()
            self.aplicar_estilo()
            self.trabalho = {"estado": "fila", "restantes": len(self.fila_refs)} if self.fila_refs else {"estado": "pronto", "nome": t["nome"]}
        except Exception as e:
            self.trabalho = {"estado": "fila", "restantes": len(self.fila_refs), "erro": f"{t['nome']}: {str(e)[:160]}"} if self.fila_refs else {"estado": "erro", "erro": f"{t['nome']}: {str(e)[:160]}"}
        finally:
            arq.unlink(missing_ok=True)  # guarda só as medidas, nunca o vídeo de outra pessoa

    def perfil(self, modelo: str | None = None, sem_filtro: bool = False) -> dict | None:
        """Junta os exemplos de um modelo: vale o que aparece na maioria deles."""
        refs = [r["medidas"] for r in self.m["referencias"] if modelo is None or r.get("modelo") == modelo]
        if not refs or not (sem_filtro or self.m["ativo"]["referencias"]):
            return None
        webcams = [r["webcam"] for r in refs if r.get("webcam")]
        legendas = [r["legenda"] for r in refs if r.get("legenda")]
        mediana = lambda l, k: round(statistics.median(x[k] for x in l), 4)
        meio = lambda k: (lambda l: round(statistics.median(l), 3) if l else None)([r[k] for r in refs if r.get(k) is not None])
        trocas: Counter = Counter()
        for r in refs:
            trocas.update(r.get("transicoes") or {})
        return {"webcam": {k: mediana(webcams, k) for k in ("x", "y", "w", "h")} if len(webcams) * 2 >= len(refs) else None,
                "legenda": {k: mediana(legendas, k) for k in ("y", "altura", "amarelo")} if legendas else None,
                "palavra_a_palavra": sum(bool(r.get("palavra_a_palavra")) for r in refs) * 2 >= len(refs), "barra": sum(bool(r.get("barra")) for r in refs) * 2 >= len(refs),
                "cortes_min": round(statistics.median(r["cortes_min"] for r in refs), 1), "duracao": round(statistics.median(r["duracao"] for r in refs)), "referencias": len(refs),
                "zooms_min": meio("zooms_min"), "zoom_escala": meio("zoom_escala"), "cena_s": meio("cena_s"), "sfx_cortes": meio("sfx_cortes"), "sfx_min": meio("sfx_min"), "whoosh": meio("whoosh"),
                "transicoes": [k for k, _ in trocas.most_common()]}

    def aplicar_estilo(self) -> None:
        """Atualiza o estilo dos próximos vídeos, guardando o anterior para poder voltar."""
        lista = self.ativos()
        # Com vários modelos, cada vídeo recebe o seu; o padrão geral não vira uma mistura deles.
        p, pref = (self.perfil(lista[0]) if len(lista) == 1 else None), self.preferencias()
        novo: dict = {}
        if p:
            if p["palavra_a_palavra"]:
                novo["legenda"] = "palavra"
            if p["legenda"]:
                novo["legenda_y"], novo["legenda_x"] = round(min(.9, p["legenda"]["y"] + p["legenda"]["altura"] / 2), 4), .5
            if p["cortes_min"] >= 8:
                novo["ritmo"] = round(float(np.clip(60 / p["cortes_min"] * 1.4, 2.5, 6.0)), 1)
            if p.get("zoom_escala"):
                novo["zoom_forca"] = int(np.clip(round((p["zoom_escala"] - 1) / .15 * 100), 60, 160))
        leg = pref.get("legenda", {})
        if "y" in leg:
            novo["legenda_y"], novo["legenda_x"] = round(leg["y"] / 1920, 4), .5
        if "zoom_forca" in pref.get("global", {}):
            novo["zoom_forca"] = pref["global"]["zoom_forca"]
        if leg.get("palavra_a_palavra") is True:
            novo["legenda"] = "palavra"
        atual = dict(self.motor.config["estilo"])
        antes, aplicado = self.m["estilo_antes"] or {}, self.m.setdefault("estilo_aplicado", {})
        final = dict(atual)
        for k in set(aplicado) - set(novo):  # o que deixou de valer volta a ser como era
            if atual.get(k) == aplicado[k]:
                final[k] = antes.get(k)
            antes.pop(k, None); aplicado.pop(k, None)
        for k, v in novo.items():
            if k in aplicado and atual.get(k) != aplicado[k]:
                continue  # o usuário mudou isto à mão depois: a escolha dele vale mais
            antes.setdefault(k, atual.get(k))
            final[k] = aplicado[k] = v
        self.m["estilo_antes"] = antes
        if final != atual:
            self.motor.salvar_config({"estilo": final})
        self._salvar()

    def ajustar_plano(self, plano: dict, fonte: Path, modelo: str | None = None) -> dict:
        lista = self.ativos()
        p = self.perfil(modelo) if modelo else self.perfil(lista[0]) if len(lista) == 1 else None
        if not p or not p["webcam"] or plano.get("layout") != "dividido" or plano.get("origem") == "manual":
            return plano
        vw, vh, _ = cam.dimensoes(fonte)
        return plano_pip(plano, p["webcam"], vw, vh)

    # ------------------------------------------------------------ edições do usuário

    def registrar_edicao(self, proj: dict, ia: dict | None) -> None:
        if not ia or not self.m["ativo"]["edicoes"]:
            return
        g0, g1 = ia.get("global", {}), proj.get("global", {})
        with self.trava:
            for grupo, chaves, a, b in (("legenda", CHAVES_LEGENDA, g0.get("legenda", {}), g1.get("legenda", {})), ("global", CHAVES_GLOBAIS, g0, g1)):
                for k in chaves:
                    if k in b and b.get(k) != a.get(k):
                        ids = self.m["edicoes"].setdefault(f"{grupo}.{k}", {}).setdefault(json.dumps(b[k]), [])
                        if proj.get("id") not in ids:
                            ids.append(proj.get("id"))  # exportar o mesmo vídeo de novo não conta duas vezes
                            del ids[:-50]
            self.m["ids_editados"] = list(dict.fromkeys([*self.m.get("ids_editados", []), proj.get("id")]))[-500:]
            self.m["videos_editados"] = len(self.m["ids_editados"])
            self._salvar()
        self.aplicar_estilo()

    def preferencias(self) -> dict:
        saida: dict = {"legenda": {}, "global": {}}
        if not self.m["ativo"]["edicoes"]:
            return saida
        for chave, valores in self.m["edicoes"].items():
            valor, n = Counter({v: len(ids) for v, ids in valores.items()}).most_common(1)[0]
            if n >= REPETICOES:
                grupo, k = chave.split(".", 1)
                saida[grupo][k] = json.loads(valor)
        return saida

    def aplicar_em_projeto(self, proj: dict) -> None:
        pref = self.preferencias()
        proj["global"]["legenda"].update(pref["legenda"])
        proj["global"].update(pref["global"])

    # ------------------------------------------------------------ resultados do canal

    def atualizar_canal(self) -> None:
        postagem = self.motor.postagem
        if not self.m["ativo"]["resultados"] or not postagem.conta.conectada:
            return
        itens = {i["video_id"]: i for i in list(postagem.itens.values()) if i.get("video_id") and i["id"] in self.motor.cortes and time.time() - (i.get("quando") or time.time()) >= IDADE_MINIMA}
        ids, views = list(itens), {}
        for n in range(0, len(ids), 50):
            for v in postagem.conta._consultar_api("videos?part=statistics,status&id=" + ",".join(ids[n:n + 50])).get("items") or []:
                if (v.get("status") or {}).get("privacyStatus") == "public":  # vídeo privado não diz nada sobre o público
                    views[v["id"]] = int((v.get("statistics") or {}).get("viewCount") or 0)
        self.calcular_pesos([(self.motor.cortes[itens[k]["id"]], v) for k, v in views.items()])

    def calcular_pesos(self, dados: list[tuple[dict, int]]) -> None:
        """Compara cada tipo de corte com a média do próprio canal."""
        media = sum(v for _, v in dados) / max(1, len(dados))
        if not dados or media <= 0:
            return
        por_tipo: dict[str, list[int]] = {}
        por_tempo: dict[str, list[int]] = {}
        por_modelo: dict[str, list[int]] = {}
        for meta, v in dados:
            if meta.get("modelo"):
                por_modelo.setdefault(meta["modelo"], []).append(v)
            por_tipo.setdefault(meta.get("reacao") or "destaque", []).append(v)
            d = float(meta.get("duracao") or 0)
            por_tempo.setdefault("até 30 s" if d <= 30 else "30 a 45 s" if d <= 45 else "mais de 45 s", []).append(v)
        with self.trava:
            self.m["desempenho"] = {"videos": len(dados), "media": round(media), "tipos": {k: {"n": len(l), "media": round(sum(l) / len(l))} for k, l in por_tipo.items()},
                                    "duracoes": {k: {"n": len(l), "media": round(sum(l) / len(l))} for k, l in por_tempo.items()}}
            self.m["pesos"] = {k: round(float(np.clip((sum(l) / len(l)) / media, .7, 1.3)), 2) for k, l in por_tipo.items() if len(l) >= MINIMO_VIDEOS}
            self.m["desempenho"]["modelos"] = {k: {"n": len(l), "media": round(sum(l) / len(l))} for k, l in por_modelo.items()}
            self.m["pesos_modelos"] = {k: round(float(np.clip((sum(l) / len(l)) / media, .5, 1.6)), 2) for k, l in por_modelo.items() if len(l) >= MINIMO_VIDEOS}
            self.m["canal_em"] = time.time()
            self._salvar()

    def peso(self, reacao: str | None) -> float:
        return float(self.m["pesos"].get(reacao or "", 1.0)) if self.m["ativo"]["resultados"] else 1.0

    def _vigiar_canal(self) -> None:
        while not self.motor.fim.wait(120):
            if time.time() - self.m.get("canal_em", 0) >= INTERVALO_CANAL:
                try:
                    self.atualizar_canal()
                except Exception:
                    pass
                self.m["canal_em"] = time.time()

    # ------------------------------------------------------------ painel

    def definir(self, dados: dict) -> dict:
        for k in ("referencias", "edicoes", "resultados"):
            if k in dados:
                self.m["ativo"][k] = bool(dados[k])
        self._salvar(); self.aplicar_estilo()
        return self.resumo()

    def remover(self, ident: str) -> dict:
        self.m["referencias"] = [r for r in self.m["referencias"] if r["id"] != ident]
        for vazio in [i for i in self.m["modelos"] if not self._exemplos(i)]:
            del self.m["modelos"][vazio]
        self._nomear(); self._salvar(); self.aplicar_estilo()
        return self.resumo()

    def esquecer(self) -> dict:
        antes = self.m.get("estilo_antes")
        aplicado = self.m.get("estilo_aplicado") or {}
        self.m.update(modelos={}, uso_modelos={}, pesos_modelos={}, referencias=[], edicoes={}, videos_editados=0, ids_editados=[], desempenho={}, pesos={}, estilo_antes=None, estilo_aplicado={})
        self._salvar()
        atual = dict(self.motor.config["estilo"])
        volta = {k: (antes or {}).get(k) for k, v in aplicado.items() if atual.get(k) == v}
        if volta:
            self.motor.salvar_config({"estilo": {**atual, **volta}})
        return self.resumo()

    def resumo(self) -> dict:
        pref = self.preferencias()
        dados_modelos = (self.m["desempenho"] or {}).get("modelos") or {}
        modelos = [{"id": i, "nome": m.get("nome") or "Modelo", "ativo": m.get("ativo", True), "uso": self.m["uso_modelos"].get(i, 0), "perfil": self.perfil(i, sem_filtro=True), "resultado": dados_modelos.get(i),
                    "exemplos": [{"id": r["id"], "nome": r["nome"]} for r in self._exemplos(i)]} for i, m in self.m["modelos"].items() if self._exemplos(i)]
        return {"modelos": modelos, "ativo": self.m["ativo"], "trabalho": {k: v for k, v in self.trabalho.items() if k != "arquivo"}, "perfil": self.perfil(), "preferencias": pref, "videos_editados": self.m["videos_editados"],
                "referencias": [{"id": r["id"], "nome": r["nome"], "medidas": r["medidas"]} for r in self.m["referencias"]], "desempenho": self.m["desempenho"], "pesos": self.m["pesos"], "minimo": MINIMO_VIDEOS}
