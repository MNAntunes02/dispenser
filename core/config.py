"""Configuração temporal do fluxo de dose, lida de variáveis de ambiente.

Todos os parâmetros são configuráveis (spec 03). Valores padrão aprovados:
alarme a cada 2 min, até 5 tentativas, sem soneca; gaveta 2 min; retorno
2 min -> RETORNO_PENDENTE; limite de "não devolvido" 30 min.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


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
        )