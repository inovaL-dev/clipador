"""Analisa um vídeo de exemplo em outro processo, sem pesar na janela e nas lives."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TEMPO_MAXIMO = 15 * 60


def comando(arquivo: Path, saida: Path, modelo: str = "", idioma: str = "") -> list[str]:
    inicio = [sys.executable, "--medir-referencia"] if getattr(sys, "frozen", False) else [sys.executable, "-m", "nucleo.medir_referencia"]
    return [*inicio, str(arquivo), str(saida), modelo, idioma]


def opcoes() -> dict:
    if os.name != "nt":
        return {}
    return {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS | subprocess.CREATE_NO_WINDOW}


def principal(arquivo: str, saida: str, modelo: str = "", idioma: str = "") -> int:
    for nome in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[nome] = "2"
    if hasattr(os, "nice"):
        os.nice(10)
    destino = Path(saida)
    try:
        import cv2

        cv2.setNumThreads(2)
        from nucleo.aprendizado import _amostras, medir_video
        from nucleo.raiox import desmontar

        medidas = medir_video(Path(arquivo))
        try:
            voz = None
            if modelo:
                try:
                    from faster_whisper import WhisperModel

                    voz = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=2)
                except Exception:
                    voz = None
            medidas["raiox"] = desmontar(Path(arquivo), medidas, _amostras(Path(arquivo), 40)[0], voz, idioma)
        except Exception:
            medidas["raiox"] = None
        resultado = {"medidas": medidas}
    except Exception as e:
        resultado = {"erro": str(e)[:200] or "Não consegui ler este vídeo."}
    temp = destino.with_suffix(".tmp")
    temp.write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")
    temp.replace(destino)
    return 0 if "medidas" in resultado else 1


if __name__ == "__main__":
    sys.exit(principal(*sys.argv[1:5]))
