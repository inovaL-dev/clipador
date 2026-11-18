"""Garante que só um Clipador use a mesma pasta de dados por vez."""
from __future__ import annotations

import os
from pathlib import Path


class Trava:
    def __init__(self, dados: Path):
        self.dados = Path(dados)
        self.dados.mkdir(parents=True, exist_ok=True)
        self.arquivo_porta = self.dados / ".porta"
        self.arquivo = open(self.dados / ".em_uso", "a+b")

    def pegar(self) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                self.arquivo.seek(0)
                msvcrt.locking(self.arquivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def guardar_porta(self, porta: int) -> None:
        self.arquivo_porta.write_text(str(porta), encoding="ascii")

    def porta_aberta(self) -> int | None:
        try:
            return int(self.arquivo_porta.read_text(encoding="ascii"))
        except (OSError, ValueError):
            return None
