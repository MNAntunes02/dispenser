"""Máquina de estados da dose (núcleo puro e testável, sem serial/tela).

Fase 2 implementa a transição completa (ver docs/spec/03-fluxo-dose.md):
espera -> alarme -> abrir -> ingerir -> devolver -> confirmada,
com as saídas perdida/retorno_pendente e repetições de alarme.
"""

from __future__ import annotations

from enum import Enum


class Fase(Enum):
    ESPERA = "espera"
    ALARME = "alarme"
    ABRIR = "abrir"
    INGERIR = "ingerir"
    DEVOLVER = "devolver"
    CONFIRMADA = "confirmada"
    PERDIDA = "perdida"
    RETORNO_PENDENTE = "retorno_pendente"


class MaquinaEstados:
    """Fases e transições da dose."""

    def __init__(self) -> None:
        self.fase: Fase = Fase.ESPERA

    def transicionar(self, evento: str) -> None:
        raise NotImplementedError("Fase 2: definir transições e idempotência por ocorrência")