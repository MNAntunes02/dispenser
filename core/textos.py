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
    "falha_sensor": "Falha {codigo} no sensor. Avise o cuidador.",
    "relogio_nao_confiavel": (
        "Relógio sem hora certa. As doses voltam a tocar assim que a hora "
        "for ajustada."
    ),
    "relogio_instavel": (
        "O relógio mudou de hora. As doses voltam a tocar assim que ele se "
        "estabilizar."
    ),
    "reposo": "Tudo em dia. Próxima dose às {proxima}",
    "reposo_sem_dose": "Nenhuma dose programada para hoje",
}

#: Rótulos fixos que a UI exibe fora do fluxo da dose. Moram aqui (e não na
#: UI) para existir um único arquivo de textos em pt-BR (regra 9 do AGENTS.md).
ROTULOS_UI: dict[str, str] = {
    "pressione_ok": "Pressione OK",
    "passo": "Passo {atual} de {total}",
    "reposo": "Aguardando a próxima dose",
    "proxima_dose": "Próxima dose",
    "sem_dose_hoje": "Nenhuma dose programada para hoje",
    "conectando": "Conectando ao dispensador…",
    "sem_conexao": "Sem conexão com o dispensador",
    "sem_core_orientacao": (
        "Tente novamente em instantes. Não tome o medicamento sem a orientação "
        "do dispensador."
    ),
    "dispensador": "Dispensador de medicamentos",
    "aviso_falha": "Falha no sensor",
    "slot": "Slot {slot}",
}

#: Avisos gravados para cuidador/app (Fase 6, ADR 010). São lidos no
#: backend, não na tela do paciente; mesmo arquivo por causa da regra 9.
AVISOS_CUIDADOR: dict[str, str] = {
    "dose_perdida": "Dose não tomada: {nome} ({dosagem}), prevista para {horario}.",
    "nao_devolvido": "Medicamento não devolvido ao slot: {nome} ({dosagem}), dose das {horario}.",
    "falha": "Falha {codigo} no sensor do dispensador. Confira a dose manualmente.",
    "relogio": (
        "Relógio do dispensador incorreto no dia {dia}. Sem lembrete: {doses}. "
        "Confira o que foi tomado."
    ),
}

#: Concordância de "dose" em pt-BR fica aqui (regra 9): as frases acima não
#: carregam o número para não repetir "1 dose"/"2 doses" em cada texto.
_DOSE = "1 dose"
_DOSES = "{n} doses"


def plural_doses(n: int) -> str:
    """'1 dose' ou 'N doses' — usado no aviso de relógio incorreto."""
    return _DOSE if n == 1 else _DOSES.format(n=n)

#: Total de passos do fluxo guiado (spec 05).
TOTAL_PASSOS = 6


def texto(chave: str, **params: object) -> str:
    """Renderiza uma mensagem centralizada com os parâmetros informados."""
    if chave not in TEXTOS:
        raise KeyError(f"mensagem desconhecida: {chave}")
    return TEXTOS[chave].format(**params)


def aviso_cuidador(motivo: str, **params: object) -> str:
    """Frase pt-BR do aviso que o cuidador recebe no backend (ADR 010)."""
    if motivo not in AVISOS_CUIDADOR:
        raise KeyError(f"aviso desconhecido: {motivo}")
    return AVISOS_CUIDADOR[motivo].format(**params)