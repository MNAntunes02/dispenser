"""Ponte simulada: reproduz o hardware sem o dispensador.

Permite injetar eventos (gaveta, slots, botões, falhas) para exercitar o
fluxo completo nos testes. A Fase 2 define o driver de comandos/script.
"""

from __future__ import annotations

from threading import RLock
from typing import Optional

from hardware.bridge.hardware_bridge import EventoHandler, HardwareBridge

_SLOTS = 4


class PonteSimulada(HardwareBridge):
    """Implementação simulada controlável por código (e depois por CLI)."""

    def __init__(self, slots: int = _SLOTS) -> None:
        self._lock = RLock()
        self._slots = slots
        self._gaveta: int = 0
        self._presente: list[int] = [0] * slots
        self._handlers: list[EventoHandler] = []
        self._conectado = False

    def conectar(self) -> None:
        self._conectado = True

    def desconectar(self) -> None:
        self._conectado = False

    def status(self) -> dict:
        return {
            "gaveta": self._gaveta,
            "slots": {str(i): {"presente": self._presente[i]} for i in range(self._slots)},
        }

    def acender_led(self, slot: int, estado: str) -> None:
        return None

    def buzzer(self, padrao: str) -> None:
        return None

    def registrar_evento(self, handler: EventoHandler) -> None:
        self._handlers.append(handler)

    def simular(self, evento: dict) -> None:
        """Injeta um evento externo (ex.: gaveta_aberta, botao)."""
        if evento.get("e") == "gaveta_aberta":
            self._gaveta = 1
        elif evento.get("e") == "gaveta_fechada":
            self._gaveta = 0
        elif evento.get("e") == "slot_presente":
            self._presente[int(evento["slot"])] = 1
        elif evento.get("e") == "slot_ausente":
            self._presente[int(evento["slot"])] = 0
        self._emitir(evento)

    def _emitir(self, evento: dict) -> None:
        for h in self._handlers:
            h(evento)