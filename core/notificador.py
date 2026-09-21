"""Notificador: escalonamento de avisos para cuidador/app.

Mecanismo do app é local (sem push ainda); avaliação de push na Fase 6.
Nesta fase os avisos são apenas registrados na trilha local (log), de
modo que o orquestrador não precise de rede para avançar o fluxo.
"""

from __future__ import annotations

from core.armazenamento import Database


class Notificador:
    """Emite notificações para o cuidador/app (stub até a Fase 6)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def notificar_dose_perdida(self, ocorrencia_id: str) -> None:
        self._db.registrar_log("notificar_dose_perdida", ocorrencia_id)

    def notificar_retorno_pendente(self, ocorrencia_id: str) -> None:
        self._db.registrar_log("notificar_retorno_pendente", ocorrencia_id)

    def notificar_falha(self, codigo: str, info: str = "") -> None:
        self._db.registrar_log("notificar_falha", detalhe=f"{codigo} {info}")