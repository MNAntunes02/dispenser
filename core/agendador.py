"""Agendador: converte a agenda em ocorrências de dose.

Equivalência com o app: recorrência semanal por dia da semana abreviado
pt_BR ("seg", "ter", ..., "sáb" com acento, "dom") + horário "HH:mm",
no relógio local (Fase 2 implementa; ver docs/DESCOBERTA.md e ADR 005).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ocorrencia:
    id: str
    medicamento: str
    dosagem: str
    slot: int | None
    dia_semana: str
    horario: str


class Agendador:
    """Produz as ocorrências do dia a partir da agenda sincronizada."""

    def ocorrencias_do_dia(self, medicamentos: list[dict], dia_semana: str) -> list[Ocorrencia]:
        raise NotImplementedError("Fase 2: gerar ocorrências idênticas à regra do app")