"""Agendador: converte a agenda em ocorrências de dose.

Equivalência com o app: recorrência semanal por dia da semana abreviado
pt_BR ("seg", "ter", ..., "sáb" com acento, "dom") + horários "HH:mm"
(aceita "H:mm" e normaliza), no relógio local. Ocorrências com ID
determinístico e ordenadas por horário (política: uma por vez).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

_ABREV: tuple[str, ...] = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def abrev_dia_semana(dia: date) -> str:
    """Abreviação pt_BR do dia (mesma regra do `DateFormat('EEE','pt_BR')`)."""
    return _ABREV[dia.weekday()]


@dataclass(frozen=True)
class Ocorrencia:
    id: str
    medicamento: str
    medicamento_nome: str
    dosagem: str
    slot: int | None
    dia: str
    horario: str


def _normalizar_horario(valor: str) -> str | None:
    try:
        hh, mm = (p.strip() for p in valor.split(":"))
        hora, minuto = int(hh), int(mm)
    except ValueError:
        return None
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None
    return f"{hora:02d}:{minuto:02d}"


class Agendador:
    """Produz as ocorrências do dia a partir da agenda sincronizada."""

    def ocorrencias_do_dia(
        self, medicamentos: list[dict], dia: date
    ) -> list[Ocorrencia]:
        abrev = abrev_dia_semana(dia)
        resultado: list[Ocorrencia] = []
        for med in medicamentos:
            mid: str = med["id"]
            dias: list[dict] = med.get("dias", [])
            for item in dias:
                if item.get("dia_semana") != abrev:
                    continue
                for horario in item.get("horario", []):
                    h = _normalizar_horario(horario)
                    if h is None:
                        continue
                    resultado.append(
                        Ocorrencia(
                            id=f"{mid}|{dia.isoformat()}|{h}",
                            medicamento=mid,
                            medicamento_nome=med.get("nome", ""),
                            dosagem=med.get("dosagem", ""),
                            slot=None,
                            dia=dia.isoformat(),
                            horario=h,
                        )
                    )
        resultado.sort(key=lambda o: (o.horario, o.medicamento))
        return resultado