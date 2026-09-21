"""Notificador: escalonamento de avisos para cuidador/app.

Mecanismo do app é local (sem push ainda); avaliação de push na Fase 6.
Registrar evento de dose perdida/retorno pendente no backend e expor à
interface do app conforme decisão da Fase 6.
"""

from __future__ import annotations


class Notificador:
    """Emite notificações para o cuidador/app."""

    def notificar_dose_perdida(self, ocorrencia_id: str) -> None:
        raise NotImplementedError("Fase 6: notificar dose perdida")

    def notificar_retorno_pendente(self, ocorrencia_id: str) -> None:
        raise NotImplementedError("Fase 6: notificar retorno pendente")

    def notificar_falha(self, codigo: str, info: str = "") -> None:
        raise NotImplementedError("Fase 6: notificar falha/estado incoerente")