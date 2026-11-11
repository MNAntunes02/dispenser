"""Ponte simulada: reproduz o hardware sem o dispensador.

Permite injetar eventos (gaveta, slots, botões, falhas) para exercitar o
fluxo completo nos testes. A Fase 2 define o driver de comandos/script.
"""

from __future__ import annotations

from threading import RLock
from typing import Optional

from hardware.bridge.hardware_bridge import EventoHandler, HardwareBridge

#: Slots da ponte simulada (padrão usado pela demo e pelo painel de dev).
SLOTS_PADRAO = 4


class PonteSimulada(HardwareBridge):
    """Implementação simulada controlável por código (e depois por CLI)."""

    def __init__(self, slots: int = SLOTS_PADRAO) -> None:
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

    def simular(self, evento: dict) -> bool:
        """Injeta um evento externo (ex.: gaveta_aberta, botao).

        Devolve `True` quando o evento foi aplicado e repassado aos
        handlers; `False` quando não pôde ser simulado — slot ausente ou
        fora da faixa, por exemplo (nunca levanta exceção: quem injeta é
        ferramenta de teste/desenvolvimento).
        """
        tipo = evento.get("e")
        if tipo in ("slot_presente", "slot_ausente"):
            try:
                slot = int(evento["slot"])
            except (KeyError, TypeError, ValueError):
                return False
            if not 0 <= slot < self._slots:
                return False
            self._presente[slot] = 1 if tipo == "slot_presente" else 0
        elif tipo == "gaveta_aberta":
            self._gaveta = 1
        elif tipo == "gaveta_fechada":
            self._gaveta = 0
        self._emitir(evento)
        return True

    def _emitir(self, evento: dict) -> None:
        for h in self._handlers:
            h(evento)