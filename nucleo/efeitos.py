"""Movimento de câmera, efeitos sonoros e montagem do vídeo quadro a quadro."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Callable, Iterable, Iterator

import cv2
import numpy as np

from .plataformas import sem_janela

FPS = 30
TAXA_AUDIO = 48000
FONTE = Path(__file__).resolve().parent.parent / "fontes" / "Poppins-Bold.ttf"


def _opcoes(baixa_prioridade: bool = False) -> dict:
    opcoes = sem_janela()
    if baixa_prioridade and os.name == "nt":
        opcoes["creationflags"] = opcoes.get("creationflags", 0) | subprocess.BELOW_NORMAL_PRIORITY_CLASS
    return opcoes


def tem_audio(video: Path) -> bool:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, **sem_janela(),
    )
    return bool(r.stdout.strip())


def ler_pcm(video: Path, ini: float = 0.0, duracao: float | None = None, taxa: int = 16000) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error"]
    if ini > 0:
        cmd += ["-ss", f"{ini:.3f}"]
    cmd += ["-i", str(video)]
    if duracao:
        cmd += ["-t", f"{duracao:.3f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(taxa), "-f", "s16le", "-"]
    saida = subprocess.run(cmd, capture_output=True, **sem_janela()).stdout
    return np.frombuffer(saida[: len(saida) // 2 * 2], dtype=np.int16)


def batidas(video: Path, ini: float = 0.0, duracao: float | None = None, espaco: float = 5.0) -> list[tuple[float, float]]:
    """Picos da voz e do jogo, do mais antigo ao mais novo, como (segundo, força)."""
    pcm = ler_pcm(video, ini, duracao)
    tamanho = 800  # 50 ms
    n = len(pcm) // tamanho
    if n < 40:
        return []
    quadros = pcm[: n * tamanho].reshape(n, tamanho).astype(np.float32) / 32768
    db = 10 * np.log10(np.mean(quadros**2, axis=1) + 1e-10)
    db = np.convolve(db, np.ones(3) / 3, "same")
    com_som = db[db > -55]
    if len(com_som) < 20:
        return []
    fundo = float(np.median(com_som))
    desvio = max(float(np.median(np.abs(com_som - fundo))) * 1.4826, 1.5)
    forca = (db - fundo) / desvio
    candidatos = [i for i in range(5, n - 5) if forca[i] >= 1.5 and forca[i] == forca[i - 5:i + 6].max()]
    escolhidos: list[int] = []
    for i in sorted(candidatos, key=lambda c: -forca[c]):
        if all(abs(i - e) * 0.05 >= espaco for e in escolhidos):
            escolhidos.append(i)
    return [(round(i * 0.05, 2), round(float(forca[i]), 2)) for i in sorted(escolhidos)]


def _suave(x: np.ndarray) -> np.ndarray:
    return x * x * (3 - 2 * x)


class Movimento:
    """Linha do tempo de zoom e posição, calculada com precisão menor que um pixel."""

    def __init__(self, quadros: int, zoom_ini: float = 1.0, zoom_fim: float = 1.0, centro: tuple[float, float] = (0.5, 0.5)):
        self.n = max(1, quadros)
        self.t = np.arange(self.n) / FPS
        self.z = np.linspace(zoom_ini, zoom_fim, self.n)
        self.cx = np.full(self.n, centro[0], dtype=np.float64)
        self.cy = np.full(self.n, centro[1], dtype=np.float64)
        self.clarao = np.zeros(self.n, dtype=np.float32)
        self.tremor = np.zeros(self.n, dtype=np.float32)
        self.vinheta = np.zeros(self.n, dtype=np.float32)

    def plano(self, ini: float, fim: float, cx: float, cy: float, zoom: float, entrada: float = 0.2, saida: float = 0.32) -> None:
        peso = _suave(np.minimum(np.clip((self.t - ini) / entrada, 0, 1), np.clip((fim - self.t) / saida, 0, 1)))
        self.z += (zoom - self.z) * peso
        self.cx += (cx - self.cx) * peso
        self.cy += (cy - self.cy) * peso

    def foco(self, ini: float, fim: float) -> None:
        peso = _suave(np.minimum(np.clip((self.t - ini) / 0.2, 0, 1), np.clip((fim - self.t) / 0.3, 0, 1)))
        self.vinheta = np.maximum(self.vinheta, peso.astype(np.float32))

    def impacto(self, t: float, clarao: float = 0.7, tremor: float = 9.0) -> None:
        depois = np.clip(self.t - t, 0, None)
        ativo = self.t >= t
        self.clarao = np.maximum(self.clarao, (clarao * np.exp(-depois * 13) * ativo).astype(np.float32))
        self.tremor = np.maximum(self.tremor, (tremor * np.exp(-depois * 8) * ativo).astype(np.float32))

    def matriz(self, i: int, largura: int, altura: int) -> np.ndarray | None:
        z = max(1.0, float(self.z[i]))
        cx = float(np.clip(self.cx[i], 0.5 / z, 1 - 0.5 / z))
        cy = float(np.clip(self.cy[i], 0.5 / z, 1 - 0.5 / z))
        dx, dy = 0.0, 0.0
        if self.tremor[i] > 0.3:
            dx = float(self.tremor[i] * np.sin(i * 2.4))
            dy = float(self.tremor[i] * np.cos(i * 3.1))
        if z <= 1.0005 and abs(dx) + abs(dy) < 0.01:
            return None
        return np.array([[z, 0, largura / 2 - z * cx * largura + dx], [0, z, altura / 2 - z * cy * altura + dy]], dtype=np.float64)


def aplicar(quadro: np.ndarray, matriz: np.ndarray | None) -> np.ndarray:
    if matriz is None:
        return quadro
    altura, largura = quadro.shape[:2]
    filtro = cv2.INTER_CUBIC if matriz[0, 0] >= 1.6 else cv2.INTER_LINEAR
    return cv2.warpAffine(quadro, matriz, (largura, altura), flags=filtro, borderMode=cv2.BORDER_REPLICATE)


def clarear(quadro: np.ndarray, forca: float) -> np.ndarray:
    if forca < 0.01:
        return quadro
    return cv2.addWeighted(quadro, 1 - forca, np.full_like(quadro, 255), forca, 0)


def mascara_vinheta(largura: int, altura: int, escuro: float = 0.42) -> np.ndarray:
    x = np.linspace(-1, 1, largura)[None, :]
    y = np.linspace(-1, 1, altura)[:, None]
    d = np.clip((np.sqrt(x**2 + y**2) - 0.62) / 0.75, 0, 1)
    valor = ((1 - _suave(d) * escuro) * 255).astype(np.uint8)
    return cv2.merge([valor, valor, valor])


def escurecer(quadro: np.ndarray, mascara: np.ndarray, forca: float) -> np.ndarray:
    if forca < 0.02:
        return quadro
    escuro = cv2.multiply(quadro, mascara, scale=1 / 255)
    return escuro if forca >= 0.98 else cv2.addWeighted(quadro, 1 - forca, escuro, forca, 0)


# ------------------------------------------------------------ sons criados aqui, sem direitos de terceiros

def _whoosh(duracao: float = 0.5) -> np.ndarray:
    n = int(TAXA_AUDIO * duracao)
    ruido = np.random.default_rng(7).normal(0, 1, n)
    espectro = np.fft.rfft(ruido)
    freqs = np.fft.rfftfreq(n, 1 / TAXA_AUDIO)
    espectro *= np.exp(-(((np.log(freqs + 1) - np.log(1400)) / 0.9) ** 2))
    som = np.fft.irfft(espectro, n)
    som = som / (np.abs(som).max() + 1e-9) * np.sin(np.linspace(0, np.pi, n)) ** 2
    lado = np.linspace(0.25, 0.75, n)
    return np.stack([som * (1 - lado), som * lado], axis=1) * 1.3


def _impacto(duracao: float = 0.8) -> np.ndarray:
    n = int(TAXA_AUDIO * duracao)
    t = np.arange(n) / TAXA_AUDIO
    freq = 42 + 85 * np.exp(-t * 11)
    grave = np.sin(2 * np.pi * np.cumsum(freq) / TAXA_AUDIO) * np.exp(-t * 6.5)
    estalo = np.random.default_rng(11).normal(0, 0.45, n) * np.exp(-t * 70)
    som = grave + estalo
    return np.stack([som, som], axis=1) * 0.8


def trilha_efeitos(duracao: float, destino: Path, whoosh: Iterable[float] = (), impacto: Iterable[float] = (), volume: float = 0.3) -> None:
    n = int(TAXA_AUDIO * duracao) + 1
    trilha = np.zeros((n, 2), dtype=np.float32)
    for sons, tempos in ((_whoosh(), whoosh), (_impacto(), impacto)):
        for t in tempos:
            ini = int(max(0.0, t) * TAXA_AUDIO)
            parte = sons[: max(0, n - ini)]
            trilha[ini:ini + len(parte)] += parte.astype(np.float32)
    dados = (np.clip(trilha * volume, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(TAXA_AUDIO)
        w.writeframes(dados.tobytes())


# ------------------------------------------------------------ leitura e gravação quadro a quadro

def ler_quadros(fonte: Path, filtro: str, largura: int, altura: int, quadros: int, ini: float = 0.0,
                baixa_prioridade: bool = False) -> Iterator[np.ndarray]:
    """Entrega exatamente a quantidade pedida; se a fonte acabar antes, repete o último quadro."""
    cmd = ["ffmpeg", "-v", "error"]
    if ini > 0:
        cmd += ["-ss", f"{ini:.3f}"]
    cmd += ["-i", str(fonte), "-t", f"{quadros / FPS + 0.2:.3f}", "-filter_complex", filtro, "-map", "[v]", "-an",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **_opcoes(baixa_prioridade))
    tamanho = largura * altura * 3
    ultimo: np.ndarray | None = None
    try:
        for _ in range(quadros):
            atual = np.empty((altura, largura, 3), np.uint8)
            visao = memoryview(atual).cast("B")
            lidos = 0
            while lidos < tamanho:
                parte = proc.stdout.readinto(visao[lidos:])
                if not parte:
                    break
                lidos += parte
            if lidos == tamanho:
                ultimo = atual
            elif ultimo is None:
                ultimo = np.zeros((altura, largura, 3), np.uint8)
            yield ultimo.copy()
    finally:
        proc.stdout.close()
        proc.kill()
        proc.wait()


def gravar(destino: Path, quadros: Iterable[np.ndarray], total: int, largura: int, altura: int, ass: str,
           fonte_audio: Path | None = None, ini_audio: float = 0.0, whoosh: Iterable[float] = (),
           impacto: Iterable[float] = (), volume_efeitos: float = 0.3, sonoridade: float = -14.0,
           filtro_extra: str = "", crf: int = 17, maxrate: str = "20M", baixa_prioridade: bool = False,
           progresso: Callable[[int], None] = lambda n: None, trilha: Path | None = None, volume_fala: float = 1.0) -> None:
    """Grava os quadros com legenda, som normalizado e efeitos sonoros."""
    duracao = total / FPS
    fim = max(0.0, duracao - 0.2)
    with tempfile.TemporaryDirectory(prefix="clipador_") as tmp:
        tmp = Path(tmp)
        (tmp / "legenda.ass").write_text(ass, encoding="utf-8")
        (tmp / "fontes").mkdir()
        shutil.copy(FONTE, tmp / "fontes")
        if trilha is not None:
            shutil.copy(trilha, tmp / "efeitos.wav")
        else:
            trilha_efeitos(duracao, tmp / "efeitos.wav", whoosh, impacto, volume_efeitos)
        entrada = ["-f", "lavfi", "-i", f"anullsrc=r={TAXA_AUDIO}:cl=stereo"]
        fala = "anull"
        if fonte_audio is not None and tem_audio(fonte_audio):
            entrada = (["-ss", f"{ini_audio:.3f}"] if ini_audio > 0 else []) + ["-i", str(Path(fonte_audio).resolve())]
            fala = f"loudnorm=I={sonoridade}:TP=-1.5:LRA=11"
        video = f"{filtro_extra}," if filtro_extra else ""
        filtro = (
            f"[0:v]{video}ass=legenda.ass:fontsdir=fontes,format=yuv420p[v];"
            f"[1:a]{fala},volume={volume_fala:.3f},aresample={TAXA_AUDIO},aformat=channel_layouts=stereo,atrim=0:{duracao:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:d=0.05,afade=t=out:st={fim:.3f}:d=0.2[fala];"
            f"[fala][2:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]"
        )
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{largura}x{altura}",
               "-r", str(FPS), "-i", "pipe:0", *entrada, "-i", "efeitos.wav", "-filter_complex", filtro,
               "-map", "[v]", "-map", "[a]", "-t", f"{duracao:.3f}", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", str(crf), "-maxrate", maxrate, "-bufsize", "40M", "-profile:v", "high", "-g", str(FPS * 2),
               "-c:a", "aac", "-b:a", "192k", "-ar", str(TAXA_AUDIO), "-ac", "2", "-video_track_timescale", "30000",
               "-movflags", "+faststart", "saida.mp4"]
        with open(tmp / "erro.txt", "wb") as erro:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=erro, cwd=tmp, **_opcoes(baixa_prioridade))
            try:
                for n, quadro in enumerate(quadros, 1):
                    proc.stdin.write(quadro.data)
                    if n % 15 == 0:
                        progresso(n)
            except (BrokenPipeError, OSError):
                pass
            finally:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
                codigo = proc.wait()
        if codigo != 0 or not (tmp / "saida.mp4").exists():
            detalhe = (tmp / "erro.txt").read_text(encoding="utf-8", errors="replace").strip()[-300:]
            raise RuntimeError(detalhe or "falha ao gravar o vídeo")
        shutil.move(str(tmp / "saida.mp4"), destino)
