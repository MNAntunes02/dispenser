"""Testes das mensagens centralizadas (regra 9 do AGENTS.md)."""

import pytest

from core.textos import texto


def test_renderiza_mensagem_com_parametros():
    assert texto("hora_remedio", nome="Losartana", dosagem="50mg") == (
        "Hora do remédio: Losartana (50mg)"
    )
    assert texto("tudo_certo", proxima="08:00") == "Tudo certo! Próxima dose às 08:00"


def test_variantes_sem_slot():
    assert texto("retire_medicamento_sem_slot") == "Retire o medicamento"
    assert texto("devolva_slot_sem_slot") == "Devolva o medicamento e feche a gaveta"
    assert texto("tudo_certo_fim") == "Tudo certo! Doses do dia concluídas."


def test_chave_desconhecida_erro():
    with pytest.raises(KeyError):
        texto("nao_existe")