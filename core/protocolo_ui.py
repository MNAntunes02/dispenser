"""Contrato de mensagens entre `dispenser-core` e `dispenser-ui`.

Ref.: ADR 003 (Unix socket + JSON, PROTOCOLO.md §2) e ADR 009 (a UI nunca
decide o estado da dose: exibe o que o core renderiza e devolve botões).

Princípios (regra de segurança do paciente):
- **Toda** frase exibida ao paciente é renderizada aqui no core a partir de
  `core/textos.py` e chega pronta à UI no campo `mensagem`. A UI não monta
  texto de domínio, não traduz e não decide o passo do fluxo.
- A UI só envia intenção de botão (`input`) e comandos de depuração
  (`comando`); ela nunca confirma uma dose por conta própria.
- `passo` (1..6) é calculado no core para que a UI não precise conhecer a
  máquina de estados.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, Iterable

VERSAO = 1

#: Limite de bytes por linha (folgado; a UI recebe frases longas da agenda).
LIMITE_LINHA = 65536

#: Tipos que o core publica.
TIPOS_DO_CORE = ("rotulos", "agenda", "estado", "alerta", "health")

#: Tipos que a UI envia.
TIPOS_DA_UI = ("input", "comando", "health")

#: Ações de botão aceitas. A política aprovada não tem soneca: só "confirma".
ACOES_DE_ENTRADA = ("confirma",)

#: Passo do fluxo guiado (spec 05) por chave de texto. `None` = fora do fluxo.
PASSO_POR_CHAVE: dict[str, int | None] = {
    "hora_remedio": 1,
    "abra_gaveta": 2,
    "retire_medicamento": 3,
    "retire_medicamento_sem_slot": 3,
    "tome_e_ok": 4,
    "devolva_slot": 5,
    "devolva_slot_sem_slot": 5,
    "aviso_retorno": 5,
    "aviso_retorno_sem_slot": 5,
    "tudo_certo": 6,
    "tudo_certo_fim": 6,
    "gaveta_fora_de_horario": None,
    "falha": None,
    "relogio_nao_confiavel": None,
    "relogio_instavel": None,
    "reposo": None,
    "reposo_sem_dose": None,
}

#: Fases em que há uma dose em andamento exibida na tela (retrato da UI).
FASES_COM_DOSE = (
    "ALARME",
    "AGUARDANDO_GAVETA",
    "GAVETA_ABERTA",
    "MEDICAMENTO_RETIRADO",
    "AGUARDANDO_RETORNO",
    "RETORNO_PENDENTE",
    "CONCLUIDA",
    "NAO_ATENDIDA",
    "FALHA",
)


class ProtocoloInvalido(ValueError):
    """Linha malformada, versão desconhecida ou tipo fora do contrato."""


def envelope(
    tipo: str, relogio: Callable[[], datetime] | None = None, **campos: object
) -> dict:
    """Monta um envelope `{"v":1,"type":...,"ts":...}` com os campos extras."""
    agora = (relogio or datetime.now)()
    msg: dict = {"v": VERSAO, "type": tipo, "ts": agora.isoformat(timespec="seconds")}
    for chave, valor in campos.items():
        if valor is not None:
            msg[chave] = valor
    return msg


def codificar(msg: dict) -> str:
    """Serializa uma mensagem em uma linha (newline-delimited JSON)."""
    return json.dumps(msg, ensure_ascii=False) + "\n"


def decodificar(linha: str, *, tipos: Iterable[str] | None = None) -> dict:
    """Lê uma linha JSON e valida versão/tipo. Levanta `ProtocoloInvalido`."""
    bruto = linha.strip()
    if not bruto:
        raise ProtocoloInvalido("linha vazia")
    if len(bruto.encode("utf-8")) > LIMITE_LINHA:
        raise ProtocoloInvalido("linha acima do limite")
    try:
        msg = json.loads(bruto)
    except ValueError as erro:
        raise ProtocoloInvalido(f"json inválido: {erro}") from erro
    if not isinstance(msg, dict):
        raise ProtocoloInvalido("mensagem não é um objeto")
    if msg.get("v") != VERSAO:
        raise ProtocoloInvalido(f"versão não suportada: {msg.get('v')!r}")
    tipo = msg.get("type")
    if not isinstance(tipo, str):
        raise ProtocoloInvalido("mensagem sem type")
    if tipos is not None and tipo not in tipos:
        raise ProtocoloInvalido(f"tipo fora do contrato: {tipo}")
    return msg


def passo_de(chave: str | None) -> int | None:
    """Passo 1..6 do fluxo guiado a partir da chave de texto (ou `None`)."""
    return PASSO_POR_CHAVE.get(chave) if chave else None
