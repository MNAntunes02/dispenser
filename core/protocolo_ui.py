"""Contrato de mensagens entre `dispenser-core` e `dispenser-ui`.

Ref.: ADR 003 (Unix socket + JSON, PROTOCOLO.md §2) e ADR 009 (a UI nunca
decide o estado da dose: exibe o que o core renderiza e devolve botões).

Princípios (regra de segurança do paciente):
- **Toda** frase exibida ao paciente é renderizada aqui no core a partir de
  `core/textos.py` e chega pronta à UI no campo `mensagem`. A UI não monta
  texto de domínio, não traduz e não decide o passo do fluxo.
- A UI só envia intenção de botão (`input`) e comandos de depuração
  (`comando`); ela nunca confirma uma dose por conta própria.
- `passo` (1..4) é calculado no core para que a UI não precise conhecer a
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
TIPOS_DO_CORE = ("rotulos", "agenda", "estado", "alerta", "health", "estoque")

#: Tipos que a UI envia.
TIPOS_DA_UI = ("input", "comando", "health")

#: Fluxo de registro de cartela (a câmera lê, o painel/script confirma).
FLUXO_REGISTRO = "registro"
CHAVES_REGISTRO = (
    "registro_posicionar",
    "registro_slot",
    "registro_invalido",
    "registro_sem_slot",
)

#: Comandos de registro aceitos no `cmd` de `comando`.
COMANDOS_REGISTRO = (
    "iniciar_registro",
    "registrar_leitura",
    "registrar_manual",
    "confirmar_registro",
)

#: Ações de botão aceitas. A política aprovada não tem soneca: só "confirma".
ACOES_DE_ENTRADA = ("confirma",)

#: Eventos de sensor que o comando `simular` aceita (whitelist, ADR 015).
#: De propósito **não** inclui `ok`/`botao` (confirmar dose é só do paciente)
#: nem `falha` (falha vem da placa/core, não de quem clica no painel).
EVENTOS_SIMULAVEIS = (
    "gaveta_aberta",
    "gaveta_fechada",
    "slot_presente",
    "slot_ausente",
)

#: Eventos simuláveis que exigem `slot` nos `args` do comando.
EVENTOS_SIMULAVEIS_COM_SLOT = ("slot_presente", "slot_ausente")

#: Passo do fluxo guiado (spec 05) por chave de texto. `None` = fora do fluxo.
PASSO_POR_CHAVE: dict[str, int | None] = {
    "abra_gaveta": 1,
    "consuma_e_detectar": 2,
    "devolva_slot": 3,
    "devolva_slot_sem_slot": 3,
    "aviso_retorno": 3,
    "aviso_retorno_sem_slot": 3,
    "tudo_certo": 4,
    "tudo_certo_fim": 4,
    "gaveta_fora_de_horario": None,
    "falha": None,
    "relogio_nao_confiavel": None,
    "relogio_instavel": None,
    "reposo": None,
    "reposo_sem_dose": None,
    **{chave: None for chave in CHAVES_REGISTRO},
}

#: Fases em que há uma dose em andamento exibida na tela (retrato da UI).
FASES_COM_DOSE = (
    "ALARME",
    "AGUARDANDO_DETECCAO",
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
    """Passo 1..4 do fluxo guiado a partir da chave de texto (ou `None`)."""
    return PASSO_POR_CHAVE.get(chave) if chave else None


def comando_liberar_proximo() -> dict:
    """Monta o comando que libera o passo de detecção (painel/CLI).

    O core só aceita em `AGUARDANDO_DETECCAO`; a câmera é apoio visual e a
    confirmação do consumo é a ação explícita do operador.
    """
    return envelope("comando", cmd="liberar_proximo")


def comando_iniciar_registro(medicamento: str | None = None) -> dict:
    """Inicia o registro: a cartela vai para a posição de detecção."""
    args = {"medicamento": str(medicamento).strip()} if medicamento else None
    return envelope("comando", cmd="iniciar_registro", args=args)


def comando_registrar_leitura(registro_id: str, quantidade: int) -> dict:
    """Envia a contagem estável da câmera para o registro em andamento."""
    return envelope(
        "comando",
        cmd="registrar_leitura",
        args={"registroId": str(registro_id), "quantidade": int(quantidade)},
    )


def comando_registrar_manual(registro_id: str, quantidade: int) -> dict:
    """Fallback: quantidade informada no painel/CLI (sem leitura estável)."""
    return envelope(
        "comando",
        cmd="registrar_manual",
        args={"registroId": str(registro_id), "quantidade": int(quantidade)},
    )


def comando_confirmar_registro(registro_id: str) -> dict:
    """Confirma que a cartela foi colocada no slot indicado pelo core."""
    return envelope(
        "comando",
        cmd="confirmar_registro",
        args={"registroId": str(registro_id)},
    )


def comando_simular(evento: str, slot: int | None = None) -> dict:
    """Monta a mensagem `comando/simular` (painel de desenvolvimento, ADR 015).

    Injeta um evento de sensor **na ponte simulada**; com ponte real o core
    recusa (ver `HardwareBridge.simular`). Usada pelo painel e pelos testes —
    fonte única do formato da mensagem. Levanta `ValueError` em uso indevido
    (evento fora da whitelist, slot em evento sem slot): quem chama passa
    constantes, então erro aqui é erro de programação.
    """
    if evento not in EVENTOS_SIMULAVEIS:
        raise ValueError(f"evento não simulável: {evento!r}")
    args: dict[str, int | str] = {"evento": evento}
    if slot is not None:
        if evento not in EVENTOS_SIMULAVEIS_COM_SLOT:
            raise ValueError(f"evento não recebe slot: {evento!r}")
        args["slot"] = slot
    return envelope("comando", cmd="simular", args=args)
