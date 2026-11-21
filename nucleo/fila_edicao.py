"""Fila de edição com prioridade.

Com várias lives ao mesmo tempo, os momentos chegam juntos. Em vez de editar na ordem de chegada:
1. o que você pediu na hora (refazer, encurtar, legendar no editor) passa na frente;
2. entre os cortes novos, os de reação mais forte são editados primeiro, para os melhores ficarem prontos antes;
3. empate: quem chegou antes.
"""
from __future__ import annotations

import itertools
import queue
import threading

PEDIDOS = {"refazer": 0, "encurtar": 0, "legendar": 0, "aprender": 5}


class FilaEdicao(queue.PriorityQueue):
    def __init__(self, cortes: dict):
        super().__init__()
        self.cortes = cortes
        self._contador = itertools.count()
        self._trava = threading.Lock()
        self._esperando: dict[str, int] = {}

    def _prioridade(self, item) -> float:
        if item is None:
            return -1.0  # encerrar
        tipo, ident = item
        if tipo in PEDIDOS:
            return float(PEDIDOS[tipo])
        forca = float((self.cortes.get(ident) or {}).get("forca") or 0)
        return 2.0 - min(1.0, forca / 100)  # entre 1 (fortíssimo) e 2 (fraco)

    def put(self, item, block: bool = True, timeout=None) -> None:
        super().put((self._prioridade(item), next(self._contador), item), block, timeout)

    def get(self, block: bool = True, timeout=None):
        return super().get(block, timeout)[2]

    def posicoes(self) -> dict[str, int]:
        """Lugar de cada corte novo na fila (1 = o próximo a ser editado)."""
        with self.mutex:
            itens = sorted(self.queue)
        lugares, n = {}, 0
        for _, _, item in itens:
            if item and item[0] == "novo":
                n += 1
                lugares[item[1]] = n
        return lugares
