"""Faz o sistema melhorar com o uso: vídeos de referência, edições do usuário e resultados do canal."""
from __future__ import annotations

import json
import statistics
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from . import camera as cam
from . import edicao, estilos

CHAVES_LEGENDA = ("tamanho", "cor", "cor_destaque", "y", "maiusculas", "palavra_a_palavra", "destaque", "fonte", "entrada", "saida", "contorno")
CHAVES_GLOBAIS = ("zoom_forca", "volume_efeitos", "volume_fala", "volume_musica")
REPETICOES = 2      # uma escolha vira preferência depois de aparecer em 2 vídeos
MINIMO_VIDEOS = 5   # menos que isso não diz nada sobre o que funciona no canal
IDADE_MINIMA = 48 * 3600
INTERVALO_CANAL = 6 * 3600


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


def medir_video(video: Path, palavras: list[dict] | None = None) -> dict:
    quadros, dur = _amostras(video)
    if len(quadros) < 8:
        raise ValueError("Não consegui ler este vídeo.")
    leg = _achar_legenda(quadros)
    return {"duracao": round(dur, 1), "vertical": True, "cortes_min": round(_cortes_por_minuto(video), 1), "webcam": _achar_webcam(quadros), "legenda": leg,
            "palavra_a_palavra": bool(leg and leg["largura"] < .3), "barra": _achar_barra(quadros), "palavras_s": round(len(palavras) / max(1.0, dur), 2) if palavras is not None else None}


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
        self.trabalho: dict = {"estado": "parado"}
        threading.Thread(target=self._vigiar_canal, daemon=True).start()

    def _salvar(self) -> None:
        temp = self.arquivo.with_suffix(".tmp")
        temp.write_text(json.dumps(self.m, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.arquivo)

    # ------------------------------------------------------------ vídeos de referência

    def receber(self, nome: str, corpo, tamanho: int) -> dict:
        if self.trabalho.get("estado") in ("fila", "analisando"):
            raise ValueError("Aguarde terminar a análise do vídeo anterior.")
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
        self.trabalho = {"estado": "fila", "nome": Path(nome).stem[:60], "arquivo": str(arq)}
        self.motor.fila.put(("aprender", "referencia"))
        return self.resumo()

    def executar(self) -> None:
        t = self.trabalho
        arq = Path(t["arquivo"])
        t["estado"] = "analisando"
        try:
            palavras = None
            try:
                modelo = self.motor._modelo_whisper()
                palavras = edicao.transcrever(modelo, arq, self.motor.config["idioma"]) if modelo else None
            except Exception:
                palavras = None
            medidas = medir_video(arq, palavras)
            with self.trava:
                self.m["referencias"].append({"id": uuid.uuid4().hex[:10], "nome": t["nome"], "criado": time.time(), "medidas": medidas})
                self.m["referencias"] = self.m["referencias"][-20:]
                self._salvar()
            self.aplicar_estilo()
            self.trabalho = {"estado": "pronto", "nome": t["nome"]}
        except Exception as e:
            self.trabalho = {"estado": "erro", "erro": str(e)[:200]}
        finally:
            arq.unlink(missing_ok=True)  # guarda só as medidas, nunca o vídeo de outra pessoa

    def perfil(self) -> dict | None:
        """Junta todas as referências: vale o que aparece na maioria delas."""
        refs = [r["medidas"] for r in self.m["referencias"]]
        if not refs or not self.m["ativo"]["referencias"]:
            return None
        webcams = [r["webcam"] for r in refs if r.get("webcam")]
        legendas = [r["legenda"] for r in refs if r.get("legenda")]
        mediana = lambda l, k: round(statistics.median(x[k] for x in l), 4)
        return {"webcam": {k: mediana(webcams, k) for k in ("x", "y", "w", "h")} if len(webcams) * 2 >= len(refs) else None,
                "legenda": {k: mediana(legendas, k) for k in ("y", "altura", "amarelo")} if legendas else None,
                "palavra_a_palavra": sum(bool(r.get("palavra_a_palavra")) for r in refs) * 2 >= len(refs), "barra": sum(bool(r.get("barra")) for r in refs) * 2 >= len(refs),
                "cortes_min": round(statistics.median(r["cortes_min"] for r in refs), 1), "duracao": round(statistics.median(r["duracao"] for r in refs)), "referencias": len(refs)}

    def aplicar_estilo(self) -> None:
        """Atualiza o estilo dos próximos vídeos, guardando o anterior para poder voltar."""
        p, pref = self.perfil(), self.preferencias()
        novo: dict = {}
        if p:
            if p["palavra_a_palavra"]:
                novo["legenda"] = "palavra"
            if p["legenda"]:
                novo["legenda_y"], novo["legenda_x"] = round(min(.9, p["legenda"]["y"] + p["legenda"]["altura"] / 2), 4), .5
            if p["cortes_min"] >= 8:
                novo["ritmo"] = round(float(np.clip(60 / p["cortes_min"] * 1.4, 2.5, 6.0)), 1)
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

    def ajustar_plano(self, plano: dict, fonte: Path) -> dict:
        p = self.perfil()
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
        for meta, v in dados:
            por_tipo.setdefault(meta.get("reacao") or "destaque", []).append(v)
            d = float(meta.get("duracao") or 0)
            por_tempo.setdefault("até 30 s" if d <= 30 else "30 a 45 s" if d <= 45 else "mais de 45 s", []).append(v)
        with self.trava:
            self.m["desempenho"] = {"videos": len(dados), "media": round(media), "tipos": {k: {"n": len(l), "media": round(sum(l) / len(l))} for k, l in por_tipo.items()},
                                    "duracoes": {k: {"n": len(l), "media": round(sum(l) / len(l))} for k, l in por_tempo.items()}}
            self.m["pesos"] = {k: round(float(np.clip((sum(l) / len(l)) / media, .7, 1.3)), 2) for k, l in por_tipo.items() if len(l) >= MINIMO_VIDEOS}
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
        self._salvar(); self.aplicar_estilo()
        return self.resumo()

    def esquecer(self) -> dict:
        antes = self.m.get("estilo_antes")
        aplicado = self.m.get("estilo_aplicado") or {}
        self.m.update(referencias=[], edicoes={}, videos_editados=0, ids_editados=[], desempenho={}, pesos={}, estilo_antes=None, estilo_aplicado={})
        self._salvar()
        atual = dict(self.motor.config["estilo"])
        volta = {k: (antes or {}).get(k) for k, v in aplicado.items() if atual.get(k) == v}
        if volta:
            self.motor.salvar_config({"estilo": {**atual, **volta}})
        return self.resumo()

    def resumo(self) -> dict:
        pref = self.preferencias()
        return {"ativo": self.m["ativo"], "trabalho": {k: v for k, v in self.trabalho.items() if k != "arquivo"}, "perfil": self.perfil(), "preferencias": pref, "videos_editados": self.m["videos_editados"],
                "referencias": [{"id": r["id"], "nome": r["nome"], "medidas": r["medidas"]} for r in self.m["referencias"]], "desempenho": self.m["desempenho"], "pesos": self.m["pesos"], "minimo": MINIMO_VIDEOS}
