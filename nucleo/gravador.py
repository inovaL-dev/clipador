"""Grava a live em pedaços curtos, com uma linha do tempo contínua."""
from __future__ import annotations

import csv
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .plataformas import cmd_streamlink, sem_janela

SEGUNDOS_SEGMENTO = 4
RETENCAO_SEGUNDOS = 15 * 60


class Gravador:
    def __init__(self, fonte: str, pasta: Path):
        self.fonte = fonte
        self.pasta = pasta
        self.parte = 0
        self.t0: float | None = None
        self.sl = self.ff = None

    def iniciar(self):
        extra = ["--twitch-disable-ads"] if "twitch.tv" in self.fonte else []
        self.sl = subprocess.Popen(
            [*cmd_streamlink(), "--stdout", "--loglevel", "error", *extra, self.fonte, "best"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **sem_janela(),
        )
        self.ff = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "fatal", "-fflags", "+genpts", "-i", "pipe:0",
             "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy", "-f", "segment",
             "-segment_time", str(SEGUNDOS_SEGMENTO), "-segment_format", "mpegts",
             "-segment_list", f"lista_{self.parte:02d}.csv", "-segment_list_type", "csv",
             "-segment_list_flags", "+live", f"seg_{self.parte:02d}_%06d.ts"],
            stdin=self.sl.stdout, cwd=self.pasta, stderr=subprocess.DEVNULL, **sem_janela(),
        )
        self.sl.stdout.close()

    def reiniciar(self, fonte: str) -> None:
        """Reabre a transmissão e continua a mesma linha do tempo."""
        for p in (self.sl, self.ff):
            if p and p.poll() is None:
                p.kill()
        for p in (self.sl, self.ff):
            if p:
                p.wait()
        self.fonte = fonte
        self.parte += 1
        self.iniciar()

    def vivo(self) -> bool:
        return self.ff.poll() is None and self.sl.poll() is None

    def aguardar_inicio(self, parar: threading.Event, limite=90) -> bool:
        fim = time.time() + limite
        while time.time() < fim and not parar.is_set():
            if next(self.pasta.glob(f"seg_{self.parte:02d}_*.ts"), None):
                self.t0 = time.time() - self.gravado()
                return True
            if not self.vivo():
                return False
            time.sleep(0.1)
        return False

    def segmentos(self) -> list[tuple[Path, float, float]]:
        """Pedaços prontos, como (arquivo, início, fim) na linha do tempo da gravação."""
        linhas, pos = [], 0.0
        for parte in range(self.parte + 1):
            try:
                with open(self.pasta / f"lista_{parte:02d}.csv", newline="") as f:
                    for nome, ini, fim in (l for l in csv.reader(f) if len(l) == 3):
                        dur = float(fim) - float(ini)
                        linhas.append((self.pasta / nome, pos, pos + dur))
                        pos += dur
            except (OSError, ValueError):
                continue
        return linhas

    def gravado(self) -> float:
        segs = self.segmentos()
        return segs[-1][2] if segs else 0.0

    def limpar_antigos(self):
        segs = self.segmentos()
        if not segs:
            return
        limite = segs[-1][2] - RETENCAO_SEGUNDOS
        for arq, _, fim in segs:
            if fim < limite:
                arq.unlink(missing_ok=True)

    def juntar(self, ini: float, fim: float, destino: Path) -> float | None:
        """Copia o trecho para um arquivo e devolve onde esse arquivo começa na gravação."""
        usados = [s for s in self.segmentos() if s[2] > ini and s[1] < fim and s[0].exists()]
        if not usados:
            return None
        # Depois de uma reconexão, usa só o trecho contínuo para o vídeo não pular.
        parte = usados[-1][0].name.split("_")[1]
        usados = [u for u in usados if u[0].name.split("_")[1] == parte]
        with open(destino, "wb") as saida:
            for arq, _, _ in usados:
                with open(arq, "rb") as f:
                    shutil.copyfileobj(f, saida)
        return usados[0][1]

    def quadro(self, destino: Path) -> bool:
        segs = [s for s in self.segmentos() if s[0].exists()]
        if not segs:
            return False
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(segs[-1][0]), "-frames:v", "1", "-q:v", "3", str(destino)],
            capture_output=True, **sem_janela(),
        )
        return r.returncode == 0 and destino.exists()

    def encerrar(self):
        for p in (self.sl, self.ff):
            if p and p.poll() is None:
                p.terminate()
        for p in (self.sl, self.ff):
            if p:
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()


def volume_medio(arquivo: Path) -> float | None:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(arquivo), "-vn", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", **sem_janela(),
    )
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    return 10 ** (float(m[1]) / 10) if m else None
