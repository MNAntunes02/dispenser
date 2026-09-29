"""Confiabilidade do relógio do dispensador (Fase 7, ADR 012).

O Raspberry Pi não tem RTC: sem NTP e sem rede no boot, `datetime.now()` pode
voltar em 1970 e — pior — **pular para frente** quando o NTP sincroniza.
Disparar dose por horário não confiável é risco para o paciente, então o core
classifica a hora antes de usá-la:

- `CONFIVEL`: acima do piso de data e sem salto grande;
- `INVALIDO`: abaixo do piso (típico: 1970 sem NTP);
- `INSTAVEL`: pulou para frente/para trás além da tolerância.

Enquanto não for `CONFIAVEL` o coordenador **não agenda nem dispara** nada
(decisão do usuário na Fase 7) e a tela avisa. A classificação é pura e o
relógio é injetável, o que mantém o comportamento testável sem Pi.

O salto só é detectável com uma referência de tempo monotônico (`relogio_mono`):
comparar a hora de parede com ela é o que separa "passou 5 s" de "o relógio
mudou 3 horas". Em teste/demo, sem referência monotônica, vale só o piso de
data — assim um relógio falso que pula 30 min continua sendo tratado como
tempo que passou.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable

Relogio = Callable[[], datetime]
RelogioMonotonico = Callable[[], float]

#: Abaixo desta data a hora do sistema não é believable: Pi sem RTC e sem NTP
#: reporta epoch. O piso é bem anterior ao projeto, para não custar nada.
DATA_MINIMA_PADRAO = datetime(2024, 1, 1, 0, 0, 0)

#: Salto de relógio (em segundos) aceito sem chamar o horário de instável.
#: Correção de NTP é de milissegundos; minutos já indicam mudança manual.
TOLERANCIA_SALTO_PADRAO = 300.0

#: Fuso do paciente. Explícito na configuração: a agenda do dia não pode
#: depender do fuso do sistema operacional (decisão do usuário na Fase 7).
FUSO_PADRAO = "America/Sao_Paulo"

#: Onde o libc busca as bases de fuso. `TZ` só é confiável com o arquivo lá.
_DIR_FUSOS = Path("/usr/share/zoneinfo")


class EstadoRelogio(str, Enum):
    """Situação do horário, do ponto de vista de disparo de dose."""

    CONFIVEL = "CONFIVEL"
    INVALIDO = "INVALIDO"
    INSTAVEL = "INSTAVEL"


class FusoInvalido(ValueError):
    """Fuso configurado não existe na base do sistema."""


@dataclass(frozen=True)
class Avaliacao:
    """Resultado de uma avaliação do relógio."""

    estado: EstadoRelogio
    agora: datetime
    motivo: str = ""
    #: Verdadeiro quando esta avaliação fechou um período não confiável.
    recuperado: bool = False
    #: Início do período não confiável, quando ele pôde ser datado.
    inicio: datetime | None = None
    #: Duração do período não confiável (0 quando não datável).
    durou_s: float = 0.0

    @property
    def confiavel(self) -> bool:
        return self.estado is EstadoRelogio.CONFIVEL


def fuso_existe(nome: str) -> bool:
    """O sistema tem a base do fuso pedido?"""
    return bool(nome) and (_DIR_FUSOS / nome).is_file()


def aplicar_fuso(nome: str) -> str:
    """Fixa o fuso do processo (`TZ` + `tzset`) e devolve o nome aplicado.

    A agenda ("08:00 do remédio") é sempre interpretada neste fuso, mesmo que
    o SO do Pi esteja em outro (decisão do usuário na Fase 7).
    """
    if not fuso_existe(nome):
        raise FusoInvalido(f"fuso desconhecido: {nome}")
    os.environ["TZ"] = nome
    time.tzset()
    return nome


def ler_data_minima(valor: str | None) -> datetime:
    """Lê o piso de data da configuração; valor inválido cai no padrão."""
    if not valor:
        return DATA_MINIMA_PADRAO
    try:
        return datetime.fromisoformat(valor.strip())
    except ValueError:
        return DATA_MINIMA_PADRAO


def aplicar_fuso_com_padrao(nome: str | None) -> tuple[str, bool]:
    """Aplica o fuso pedido ou, se inválido, o padrão.

    Devolve `(fuso_aplicado, ok)`. Um fuso configurado errado **não** pode
    derrubar o core nem deixá-lo em UTC: o paciente precisa de dose na hora
    certa, então caímos no fuso do Brasil e o entrypoint avisa no log.
    """
    alvo = (nome or "").strip() or FUSO_PADRAO
    try:
        return aplicar_fuso(alvo), True
    except FusoInvalido:
        return aplicar_fuso(FUSO_PADRAO), False


class VerificadorRelogio:
    """Classifica a hora do sistema, lembrando a leitura anterior.

    Puro no sentido importante: só depende dos relógios injetados e guarda o
    mínimo de estado (última leitura, situação atual, início do período não
    confiável). Não escreve em disco nem fala com a UI.
    """

    def __init__(
        self,
        relogio: Relogio | None = None,
        *,
        data_minima: datetime | None = None,
        tolerancia_s: float = TOLERANCIA_SALTO_PADRAO,
        relogio_mono: RelogioMonotonico | None = None,
    ) -> None:
        self._relogio = relogio or datetime.now
        self._relogio_mono = relogio_mono
        self._data_minima = data_minima or DATA_MINIMA_PADRAO
        self._tolerancia_s = float(tolerancia_s)
        self._anterior: datetime | None = None
        self._anterior_mono: float | None = None
        self._estado: EstadoRelogio | None = None
        self._invalido_desde: datetime | None = None

    @property
    def data_minima(self) -> datetime:
        return self._data_minima

    @property
    def estado(self) -> EstadoRelogio | None:
        """Situação da última avaliação (`None` antes da primeira)."""
        return self._estado

    @property
    def confiavel(self) -> bool:
        return self._estado is EstadoRelogio.CONFIVEL

    def avaliar(self) -> Avaliacao:
        """Lê a hora e classifica. Chame uma vez por `tick`."""
        agora = self._relogio()
        estado, motivo = self._classificar(agora)

        inicio: datetime | None = None
        durou = 0.0
        recuperado = False
        if estado is EstadoRelogio.CONFIVEL:
            if self._invalido_desde is not None:
                recuperado = True
                # Só datamos a janela quando a leitura inicial era believable:
                # se começou em 1970, a duração calculada seria fiction.
                if self._invalido_desde >= self._data_minima:
                    inicio = self._invalido_desde
                    durou = max(0.0, (agora - inicio).total_seconds())
                self._invalido_desde = None
        elif self._invalido_desde is None:
            self._invalido_desde = agora

        self._estado = estado
        self._anterior = agora
        self._anterior_mono = self._mono()
        return Avaliacao(
            estado=estado,
            agora=agora,
            motivo=motivo,
            recuperado=recuperado,
            inicio=inicio,
            durou_s=durou,
        )

    def _mono(self) -> float | None:
        return self._relogio_mono() if self._relogio_mono is not None else None

    def _classificar(self, agora: datetime) -> tuple[EstadoRelogio, str]:
        if agora < self._data_minima:
            return EstadoRelogio.INVALIDO, "abaixo_do_piso"
        anterior = self._anterior
        mono = self._mono()
        if (
            anterior is None
            or self._estado is None
            or self._estado is not EstadoRelogio.CONFIVEL
            or mono is None
            or self._anterior_mono is None
        ):
            # Sem base confiável (ou sem referência monotônica para comparar):
            # esta leitura vira a nova base.
            return EstadoRelogio.CONFIVEL, ""
        salto = (agora - anterior).total_seconds()
        esperado = mono - self._anterior_mono
        if abs(salto - esperado) > self._tolerancia_s:
            direcao = "para_frente" if salto > esperado else "para_tras"
            return EstadoRelogio.INSTAVEL, direcao
        return EstadoRelogio.CONFIVEL, ""


def chave_tela(estado: EstadoRelogio) -> str:
    """Chave de `core/textos.py` da tela de aviso do relógio."""
    if estado is EstadoRelogio.INSTAVEL:
        return "relogio_instavel"
    return "relogio_nao_confiavel"


def estado_para_notificacao(estado: EstadoRelogio) -> str:
    """Motivo curto do log (LGPD: sem horário, sem nome de medicamento)."""
    return f"relogio_{estado.value.lower()}"
