"""Observa a live: expressão do streamer, agitação na imagem do jogo e exclamações curtas."""
from __future__ import annotations

import re
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from .camera import detectar_rostos
from .momentos import medir_pcm
from .plataformas import sem_janela

MODELO_EXPRESSAO = Path(__file__).resolve().parent.parent / "modelos" / "expressao.onnx"
ALEGRIA, SURPRESA = 3, 5
LARGURA, ALTURA = 960, 540
EXCLAMACOES = re.compile(
    r"\b(uau+|wow|nossa+|caraca|caramba|carai|caralho|meu deus|olha isso|olha só|olha o tamanho|olha aquilo|"
    r"que isso|que lindo|que linda|que absurdo|absurdo|surreal|incrível|inacreditável|não acredito|"
    r"mentira|socorro|perfeito|insano|lindo demais|mano do céu|que loucura|que coisa)\b",
    re.I,
)

_sessao = None
_trava = threading.Lock()


def classificar_expressoes(rostos: np.ndarray) -> np.ndarray:
    """Recebe rostos em tons de cinza 64x64 e devolve a chance de cada expressão."""
    global _sessao
    with _trava:
        if _sessao is None:
            import onnxruntime as ort

            opcoes = ort.SessionOptions()
            opcoes.intra_op_num_threads = 2
            _sessao = ort.InferenceSession(str(MODELO_EXPRESSAO), opcoes, providers=["CPUExecutionProvider"])
    entrada = (rostos.astype(np.float32) / 255 - 0.5) * 2
    return _sessao.run(None, {"entrada": entrada[:, None, :, :]})[0]


def contar_exclamacoes(texto: str | None) -> int:
    return len({m.casefold() for m in EXCLAMACOES.findall(texto or "")})


class RastreadorRosto:
    """Segue só o rosto que fica parado no mesmo lugar: personagens do jogo são ignorados."""

    def __init__(self):
        self.vistos: deque[tuple] = deque(maxlen=24)
        self.fixo: tuple | None = None

    def atualizar(self, rostos: list[tuple], area: list[float] | None) -> tuple | None:
        if area:
            x, y, w, h = area
            rostos = [r for r in rostos if x <= r[0] + r[2] / 2 <= x + w and y <= r[1] + r[3] / 2 <= y + h]
        self.vistos.extend(rostos)
        melhor, votos = None, 0
        for r in self.vistos:
            perto = [o for o in self.vistos if _perto(r, o)]
            if len(perto) > votos:
                melhor, votos = perto, len(perto)
        self.fixo = tuple(np.median(np.array(melhor), axis=0)) if melhor and votos >= 4 else None
        if self.fixo is None:
            return None
        atuais = [r for r in rostos if _perto(r, self.fixo)]
        return max(atuais, key=lambda r: r[2] * r[3]) if atuais else None


def _perto(a: tuple, b: tuple) -> bool:
    limite = max(0.05, max(a[3], b[3]) * 0.6)
    return abs(a[0] + a[2] / 2 - b[0] - b[2] / 2) < limite and abs(a[1] + a[3] / 2 - b[1] - b[3] / 2) < limite


def _quadros(arquivos: list[Path]) -> np.ndarray:
    tamanho = LARGURA * ALTURA * 3
    blocos = []
    for arq in arquivos:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-threads", "2", "-i", str(arq), "-an", "-vf",
             f"fps=3,scale={LARGURA}:{ALTURA}:flags=fast_bilinear", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
            capture_output=True, **sem_janela(),
        )
        n = len(r.stdout) // tamanho
        if n:
            blocos.append(np.frombuffer(r.stdout, np.uint8, n * tamanho).reshape(n, ALTURA, LARGURA, 3))
    return np.concatenate(blocos) if blocos else np.empty((0, ALTURA, LARGURA, 3), np.uint8)


def medir_jogo(quadros: np.ndarray, excluir: list[float] | None) -> dict:
    """Movimento, trocas de cena e clarões, sem contar a área da webcam."""
    pequenos = np.stack([cv2.resize(cv2.cvtColor(q, cv2.COLOR_BGR2GRAY), (160, 90)) for q in quadros]).astype(np.float32)
    mascara = np.ones((90, 160), bool)
    if excluir:
        x, y, w, h = excluir
        mascara[max(0, int(y * 90)):int((y + h) * 90) + 1, max(0, int(x * 160)):int((x + w) * 160) + 1] = False
    valores = pequenos[:, mascara]
    dif = np.abs(np.diff(valores, axis=0)).mean(axis=1)
    brilho = valores.mean(axis=1)
    referencia = max(14.0, float(np.median(dif)) * 3)
    return {
        "movimento": float(np.percentile(dif, 80)),
        "cenas": int(np.sum(dif > referencia)),
        "clarao": float(np.max(np.abs(np.diff(brilho)))),
    }


class Sentidos:
    def __init__(self, ouvir, ajuste_camera):
        self.ouvir = ouvir
        self.ajuste_camera = ajuste_camera
        self.rastreador = RastreadorRosto()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sentidos")
        self.pular_fala = 0
        self.ultimo_tempo = 0.0

    def encerrar(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def ler(self, arquivos: list[Path]) -> dict:
        inicio = time.time()
        pcm = self._audio(arquivos)
        audio = medir_pcm(pcm) if pcm is not None else None
        ver = self.executor.submit(self._ver, arquivos)
        ouvir = None
        if pcm is not None and self.pular_fala == 0:
            ouvir = self.executor.submit(self.ouvir, pcm)
        else:
            self.pular_fala = max(0, self.pular_fala - 1)
        try:
            visao = ver.result(timeout=25)
        except Exception:
            visao = None
        try:
            fala = ouvir.result(timeout=25) if ouvir else None
        except Exception:
            fala = None
        self.ultimo_tempo = time.time() - inicio
        if self.ultimo_tempo > 7:  # em PCs mais lentos, ouve menos para não atrasar a live
            self.pular_fala = 3
        return {"audio": audio, "visao": visao, "fala": fala}

    @staticmethod
    def _audio(arquivos: list[Path]) -> np.ndarray | None:
        blocos = []
        for arq in arquivos:
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(arq), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                capture_output=True, **sem_janela(),
            )
            if r.stdout:
                blocos.append(np.frombuffer(r.stdout, dtype=np.int16))
        return np.concatenate(blocos) if blocos else None

    def _ver(self, arquivos: list[Path]) -> dict | None:
        return self.ver_quadros(_quadros(arquivos))

    def ver_quadros(self, quadros: np.ndarray) -> dict | None:
        if len(quadros) < 4:
            return None
        ajuste = self.ajuste_camera() or {}
        area = ajuste.get("rect") if ajuste.get("modo") in ("dividido", "tela_cheia") else None
        amostras = quadros[np.linspace(0, len(quadros) - 1, 3).astype(int)]
        rosto = None
        for q in amostras:
            rosto = self.rastreador.atualizar(detectar_rostos(q), area) or rosto
        fixo = self.rastreador.fixo
        excluir = area
        if not excluir and fixo and fixo[3] < 0.2:
            excluir = [fixo[0] - fixo[2] * 1.6, fixo[1] - fixo[3] * 1.2, fixo[2] * 4.2, fixo[3] * 3.4]
        resultado = medir_jogo(quadros, excluir)
        resultado.update({"surpresa": None, "alegria": None})
        if rosto:
            resultado.update(self._expressao(quadros[::3], rosto))
        return resultado

    @staticmethod
    def _expressao(quadros: np.ndarray, rosto: tuple) -> dict:
        x, y, w, h = rosto
        x0, x1 = max(0, int((x - w * 0.08) * LARGURA)), min(LARGURA, int((x + w * 1.08) * LARGURA))
        y0, y1 = max(0, int((y - h * 0.08) * ALTURA)), min(ALTURA, int((y + h * 1.08) * ALTURA))
        if x1 - x0 < 16 or y1 - y0 < 16:
            return {}
        rostos = np.stack([cv2.resize(cv2.cvtColor(q[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), (64, 64)) for q in quadros])
        chances = classificar_expressoes(rostos)
        topo = max(1, min(3, len(chances)))
        return {
            "surpresa": float(np.sort(chances[:, SURPRESA])[-topo:].mean()),
            "alegria": float(np.sort(chances[:, ALEGRIA])[-topo:].mean()),
        }
