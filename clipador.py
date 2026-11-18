#!/usr/bin/env python3
"""Clipador ao vivo: abre o painel e corta lives enquanto elas estão no ar."""
from __future__ import annotations

import argparse
import shutil
import signal
import sys
import threading
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description="Corta lives do Kick, X, Twitch e YouTube enquanto estão no ar.")
    ap.add_argument("links", nargs="*", help="links das lives para já começar a acompanhar")
    ap.add_argument("--porta", type=int, default=8420, help="porta do painel (padrão: 8420)")
    ap.add_argument("--saida", default=str(RAIZ / "cortes"), help="pasta dos cortes")
    ap.add_argument("--dados", default=str(RAIZ / "dados"), help="pasta das configurações")
    ap.add_argument("--modelo", help="modelo do Whisper; substitui o escolhido no painel")
    ap.add_argument("--sem-navegador", action="store_true", help="não abre o navegador automaticamente")
    args = ap.parse_args()

    faltando = [p for p in ("ffmpeg", "ffprobe") if not shutil.which(p)]
    if faltando:
        print(f"Instale antes de continuar: {', '.join(faltando)}")
        return 2

    from nucleo.instancia import Trava

    trava = Trava(Path(args.dados))
    if not trava.pegar():
        print("O Clipador já está aberto com estes dados.")
        return 1

    from nucleo.motor import Motor
    from nucleo.painel import iniciar_servidor

    motor = Motor(Path(args.dados), Path(args.saida), args.modelo)
    for link in args.links:
        try:
            motor.adicionar(link)
        except ValueError as e:
            print(e)

    servidor, porta = iniciar_servidor(motor, args.porta)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    endereco = f"http://127.0.0.1:{porta}"
    print(f"\nPainel aberto em {endereco}", flush=True)
    print("Deixe esta janela aberta. Para encerrar, aperte Ctrl+C.\n", flush=True)
    if not args.sem_navegador:
        webbrowser.open(endereco)

    parar = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: parar.set())
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    while not parar.wait(0.5):
        pass
    print("Encerrando...", flush=True)
    servidor.shutdown()
    motor.encerrar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
