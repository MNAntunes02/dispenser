"""Interface `HardwareBridge`.

Todo acesso a hardware passa por esta interface (regra 8 do AGENTS.md).
Duas implementações: real (serial USB, ver PROTOCOLO.md) e simulada
(controlável por script/CLI para reproduzir o fluxo sem o dispensador).

Eventos seguem o contrato do PROTOCOLO.md: gaveta_aberta, gaveta_fechada,
slot_presente, slot_ausente, botao, falha.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

EventoHandler = Callable[[dict], None]


class HardwareBridge(ABC):
    """Contrato mínimo da ponte com a placa controladora."""

    @abstractmethod
    def conectar(self) -> None:
        """Abre a conexão e faz o handshake (com reconexão automática)."""

    @abstractmethod
    def desconectar(self) -> None:
        """Fecha a conexão."""

    @abstractmethod
    def status(self) -> dict:
        """Consulta sensores atuais: {"gaveta": 0|1, "slots": {...}}."""

    @abstractmethod
    def acender_led(self, slot: int, estado: str) -> None:
        """Controla LED do slot (`on`/`off`/`pisca`; `-1` = todos)."""

    @abstractmethod
    def buzzer(self, padrao: str) -> None:
        """Aciona o buzzer (`dose`/`retorno`/`falha`/`off`)."""

    def registrar_evento(self, handler: EventoHandler) -> None:
        """Registra callback que recebe eventos da placa (dict do PROTOCOLO)."""