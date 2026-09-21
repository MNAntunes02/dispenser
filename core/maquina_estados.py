"""Máquina de estados da dose (núcleo puro e testável, sem serial/tela).

Implementa a transição completa de docs/spec/03-fluxo-dose.md:
AGUARDANDO -> ALARME -> AGUARDANDO_GAVETA -> GAVETA_ABERTA ->
MEDICAMENTO_RETIRADO -> AGUARDANDO_RETORNO -> CONCLUIDA, com
NAO_ATENDIDA, RETORNO_PENDENTE e FALHA como desvios.

Regras de projeto (AGENTS.md):
- Máquina pura: entrada = eventos, saída = ações (sem hardware/rede).
- Nunca marcar dose como tomada sem confirmação do usuário (evento `ok`)
  e o sensor correspondente (slot_ausente) já terem ocorrido no fluxo.
- Falha/estado incoerente vai a FALHA e a dose NÃO é considerada tomada.
- Idempotência: estado terminal (CONCLUIDA/NAO_ATENDIDA) não reabre.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.config import Config


class Fase(str, Enum):
    AGUARDANDO = "AGUARDANDO"
    ALARME = "ALARME"
    AGUARDANDO_GAVETA = "AGUARDANDO_GAVETA"
    GAVETA_ABERTA = "GAVETA_ABERTA"
    MEDICAMENTO_RETIRADO = "MEDICAMENTO_RETIRADO"
    AGUARDANDO_RETORNO = "AGUARDANDO_RETORNO"
    RETORNO_PENDENTE = "RETORNO_PENDENTE"
    CONCLUIDA = "CONCLUIDA"
    NAO_ATENDIDA = "NAO_ATENDIDA"
    FALHA = "FALHA"


@dataclass(frozen=True)
class Contexto:
    nome: str = ""
    dosagem: str = ""
    slot: int | None = None
    proxima_dose: str = ""
    tentativas: int = 0


@dataclass(frozen=True)
class Acao:
    tipo: str
    dados: dict = field(default_factory=dict)


def _alarme_tentativa(ctx: Contexto, config: Config, tent: int) -> tuple[Fase, list[Acao]]:
    """Lógica compartilhada de nova tentativa de alarme (timeout/sem resposta)."""
    tent += 1
    if tent >= config.max_tentativas:
        return Fase.NAO_ATENDIDA, [
            Acao("parar_buzzer"),
            Acao("registrar", {"tipo": "dose_perdida"}),
            Acao("notificar", {"motivo": "dose_perdida"}),
        ]
    return Fase.ALARME, [
        Acao("buzzer", {"padrao": "dose"}),
        Acao(
            "tela",
            {"chave": "hora_remedio", "nome": ctx.nome, "dosagem": ctx.dosagem},
        ),
    ]


def processar(
    fase: Fase,
    ctx: Contexto,
    config: Config,
    evento: str,
    dados: dict | None = None,
) -> tuple[Fase, list[Acao], int]:
    """Transição pura. Retorna (nova fase, ações, tentativas após o evento).

    Eventos não previstos para a fase atual são ignorados (estado inalterado,
    sem ações), o que garante idempotência na reentrega.
    """
    dados = dados or {}
    tent = ctx.tentativas

    if evento == "falha":
        if fase == Fase.FALHA:
            return fase, [], tent
        return Fase.FALHA, [
            Acao("parar_buzzer"),
            Acao("tela", {"chave": "falha", "codigo": dados.get("codigo", "?")}),
            Acao("registrar", {"tipo": "falha", "codigo": dados.get("codigo", "?")}),
            Acao("notificar", {"motivo": "falha", "codigo": dados.get("codigo", "?")}),
        ], tent

    if fase == Fase.AGUARDANDO:
        if evento == "horario_chegou":
            return Fase.ALARME, [
                Acao("buzzer", {"padrao": "dose"}),
                Acao("led", {"slot": ctx.slot, "estado": "on"}),
                Acao(
                    "tela",
                    {"chave": "hora_remedio", "nome": ctx.nome, "dosagem": ctx.dosagem},
                ),
            ], tent
        if evento == "gaveta_aberta":
            return Fase.AGUARDANDO, [
                Acao("led", {"slot": -1, "estado": "pisca"}),
                Acao("tela", {"chave": "gaveta_fora_de_horario"}),
                Acao("registrar", {"tipo": "gaveta_fora_de_horario"}),
            ], tent
        return fase, [], tent

    if fase == Fase.ALARME:
        if evento == "ok":
            return Fase.AGUARDANDO_GAVETA, [
                Acao("parar_buzzer"),
                Acao("tela", {"chave": "abra_gaveta"}),
            ], tent
        if evento == "timeout_alarme":
            nova_fase, acoes = _alarme_tentativa(ctx, config, tent)
            return nova_fase, acoes, tent + 1
        return fase, [], tent

    if fase == Fase.AGUARDANDO_GAVETA:
        if evento == "gaveta_aberta":
            return Fase.GAVETA_ABERTA, [
                Acao("tela", {"chave": "retire_medicamento", "slot": ctx.slot}),
            ], tent
        if evento == "timeout_gaveta":
            nova_fase, acoes = _alarme_tentativa(ctx, config, tent)
            return nova_fase, acoes, tent + 1
        return fase, [], tent

    if fase == Fase.GAVETA_ABERTA:
        if evento == "slot_ausente":
            return Fase.MEDICAMENTO_RETIRADO, [
                Acao("tela", {"chave": "tome_e_ok"}),
            ], tent
        return fase, [], tent

    if fase == Fase.MEDICAMENTO_RETIRADO:
        if evento == "ok":
            return Fase.AGUARDANDO_RETORNO, [
                Acao("registrar", {"tipo": "dose_tomada"}),
                Acao("tela", {"chave": "devolva_slot", "slot": ctx.slot}),
            ], tent
        return fase, [], tent

    if fase in (Fase.AGUARDANDO_RETORNO, Fase.RETORNO_PENDENTE):
        if evento == "retorno_ok":
            return Fase.CONCLUIDA, [
                Acao("registrar", {"tipo": "dose_concluida"}),
                Acao("tela", {"chave": "tudo_certo", "proxima": ctx.proxima_dose}),
                Acao("apagar_led", {"slot": ctx.slot}),
            ], tent
        if fase == Fase.AGUARDANDO_RETORNO and evento == "timeout_retorno":
            return Fase.RETORNO_PENDENTE, [
                Acao("buzzer", {"padrao": "retorno"}),
                Acao("led", {"slot": ctx.slot, "estado": "on"}),
                Acao("tela", {"chave": "aviso_retorno", "slot": ctx.slot}),
            ], tent
        if fase == Fase.RETORNO_PENDENTE and evento == "limite_retorno_excedido":
            return Fase.RETORNO_PENDENTE, [
                Acao("notificar", {"motivo": "nao_devolvido"}),
            ], tent
        return fase, [], tent

    return fase, [], tent