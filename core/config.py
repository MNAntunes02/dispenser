"""Configuração temporal do fluxo de dose, lida de variáveis de ambiente.

Todos os parâmetros são configuráveis (spec 03). Valores padrão aprovados:
alarme a cada 2 min, até 5 tentativas, sem soneca; gaveta 2 min; retorno
2 min -> RETORNO_PENDENTE; limite de "não devolvido" 30 min.

A Fase 7 (ADR 012) soma o bloco de boot/robustez: fuso do paciente, piso de
data do relógio (Pi sem RTC), tolerância a salto, janela de atraso da dose e
retenção da trilha local.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.relogio import FUSO_PADRAO, TOLERANCIA_SALTO_PADRAO


def _int(nome: str, padrao: int) -> int:
    valor = os.environ.get(nome)
    if valor is None:
        return padrao
    try:
        return int(valor)
    except ValueError:
        return padrao


def _float(nome: str, padrao: float) -> float:
    valor = os.environ.get(nome)
    if valor is None:
        return padrao
    try:
        return float(valor)
    except ValueError:
        return padrao


@dataclass(frozen=True)
class Config:
    tick_s: float = 5.0
    intervalo_alarme_s: int = 120
    max_tentativas: int = 5
    timeout_gaveta_s: int = 120
    timeout_retorno_s: int = 120
    limite_retorno_s: int = 1800
    intervalo_sync_s: int = 15
    #: Fase 7 (ADR 012): fuso do paciente. Explícito para a agenda não depender
    #: do fuso do SO; `core/relogio.py` aplica com `tzset` no boot.
    fuso: str = FUSO_PADRAO
    #: Piso de data do relógio: abaixo disso a hora não é confiável (sem RTC).
    data_minima: str = "2024-01-01"
    #: Salto de relógio aceito antes de chamar o horário de instável.
    tolerancia_salto_s: int = int(TOLERANCIA_SALTO_PADRAO)
    #: Dose mais atrasada que isso ainda dispara ao voltar (recuperação do
    #: relógio, ou aparelho que só ligou depois do horário).
    janela_atraso_s: int = 900
    #: Fase 7: retenção da trilha local (log_eventos). A fila `outbox` nunca é
    #: purgada: é o que garante não perder evento na falta de rede.
    retencao_log_dias: int = 90

    @classmethod
    def de_env(cls) -> "Config":
        return cls(
            tick_s=_float("DISPENSER_TICK_S", 5.0),
            intervalo_alarme_s=_int("DISPENSER_ALARME_INTERVALO_S", 120),
            max_tentativas=_int("DISPENSER_MAX_TENTATIVAS", 5),
            timeout_gaveta_s=_int("DISPENSER_TIMEOUT_GAVETA_S", 120),
            timeout_retorno_s=_int("DISPENSER_TIMEOUT_RETORNO_S", 120),
            limite_retorno_s=_int("DISPENSER_LIMITE_RETORNO_S", 1800),
            intervalo_sync_s=_int("SYNC_INTERVAL_S", 15),
            fuso=(os.environ.get("DISPENSER_TZ") or "").strip() or FUSO_PADRAO,
            data_minima=(
                os.environ.get("DISPENSER_DATA_MINIMA") or "2024-01-01"
            ).strip(),
            tolerancia_salto_s=_int(
                "DISPENSER_TOLERANCIA_SALTO_S", int(TOLERANCIA_SALTO_PADRAO)
            ),
            janela_atraso_s=_int("DISPENSER_JANELA_ATRASO_S", 900),
            retencao_log_dias=_int("DISPENSER_RETENCAO_LOG_DIAS", 90),
        )