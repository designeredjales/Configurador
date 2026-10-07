"""Limite de tentativas em memória (por processo).

Com vários processos/servidores, troque por um armazenamento compartilhado
(Redis) para o limite valer em todos.
"""
import threading
import time
from collections import defaultdict, deque


class Limitador:
    def __init__(self, maximo: int, janela_s: int):
        self.maximo, self.janela = maximo, janela_s
        self._eventos: dict[str, deque] = defaultdict(deque)
        self._trava = threading.Lock()

    def _limpar(self, chave: str, agora: float) -> deque:
        fila = self._eventos[chave]
        while fila and agora - fila[0] > self.janela:
            fila.popleft()
        return fila

    def bloqueado(self, chave: str) -> int:
        """Segundos até liberar (0 = liberado)."""
        with self._trava:
            agora = time.monotonic()
            fila = self._limpar(chave, agora)
            return int(self.janela - (agora - fila[0])) + 1 if len(fila) >= self.maximo else 0

    def registrar(self, chave: str) -> None:
        with self._trava:
            self._limpar(chave, time.monotonic()).append(time.monotonic())

    def zerar(self, chave: str) -> None:
        with self._trava:
            self._eventos.pop(chave, None)


falhas_login = Limitador(maximo=5, janela_s=15 * 60)
pedidos_redefinicao = Limitador(maximo=3, janela_s=60 * 60)
