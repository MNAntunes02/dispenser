"""Ponte real: USB serial /dev/serial/by-id (PROTOCOLO.md).

Fase 1: esqueleto com abertura/fechamento da porta e fila de eventos.
Fase 2/4: handshake ident, ack/timeout/retentativas, heartbeat, debounce
e reconexão devem ser completados aqui (ver docs/PROTOCOLO.md).
"""

from __future__ import annotations

from threading import RLock
from typing import Optional

from hardware.bridge.hardware_bridge import EventoHandler, HardwareBridge


class PonteSerial(HardwareBridge):
    """Ponte real via pyserial."""

    def __init__(self, caminho_porta: str, baud: int = 115200) -> None:
        self._caminho_porta = caminho_porta
        self._baud = baud
        self._lock = RLock()
        self._serial = None
        self._handlers: list[EventoHandler] = []

    def conectar(self) -> None:
        raise NotImplementedError("Fase 2/4: abrir porta, handshake e reconexão")

    def desconectar(self) -> None:
        raise NotImplementedError

    def status(self) -> dict:
        raise NotImplementedError

    def acender_led(self, slot: int, estado: str) -> None:
        raise NotImplementedError

    def buzzer(self, padrao: str) -> None:
        raise NotImplementedError

    def registrar_evento(self, handler: EventoHandler) -> None:
        self._handlers.append(handler)

    def _emitir(self, evento: dict) -> None:
        for h in self._handlers:
            h(evento)