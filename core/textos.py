"""Strings de interface com o usuário final em português do Brasil.

Centralizadas aqui (regra 9 do AGENTS.md). A máquina de estados referencia
apenas a chave + parâmetros; a renderização ocorre no orquestrador/UI.
"""

from __future__ import annotations

TEXTOS: dict[str, str] = {
    "hora_remedio": "Hora do remédio: {nome} ({dosagem})",
    "abra_gaveta": "Abra a gaveta",
    "retire_medicamento": "Retire o medicamento do slot {slot}",
    "retire_medicamento_sem_slot": "Retire o medicamento",
    "tome_e_ok": "Tome o medicamento e pressione OK",
    "devolva_slot": "Devolva ao slot {slot} e feche a gaveta",
    "devolva_slot_sem_slot": "Devolva o medicamento e feche a gaveta",
    "tudo_certo": "Tudo certo! Próxima dose às {proxima}",
    "tudo_certo_fim": "Tudo certo! Doses do dia concluídas.",
    "aviso_retorno": "Medicamento ainda não devolvido ao slot {slot}",
    "aviso_retorno_sem_slot": "Medicamento ainda não devolvido. Feche a gaveta.",
    "gaveta_fora_de_horario": "Gaveta aberta fora do horário da dose",
    "falha": "Falha {codigo}. Dose não confirmada.",
}


def texto(chave: str, **params: object) -> str:
    """Renderiza uma mensagem centralizada com os parâmetros informados."""
    if chave not in TEXTOS:
        raise KeyError(f"mensagem desconhecida: {chave}")
    return TEXTOS[chave].format(**params)