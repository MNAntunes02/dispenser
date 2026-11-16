"""Testes das mensagens centralizadas (regra 9 do AGENTS.md)."""

import pytest

from core.textos import texto


def test_renderiza_mensagem_com_parametros():
    assert texto("abra_gaveta") == "Abra a gaveta"
    assert texto("tudo_certo", proxima="08:00") == "Tudo certo! Próxima dose às 08:00"


def test_texto_do_passo_de_deteccao():
    assert texto("consuma_e_detectar") == (
        "Consuma o medicamento e coloque a cartela na posição de detecção"
    )


def test_variantes_sem_slot():
    assert texto("devolva_slot_sem_slot") == "Devolva o medicamento e feche a gaveta"
    assert texto("tudo_certo_fim") == "Tudo certo! Doses do dia concluídas."


def test_chave_desconhecida_erro():
    with pytest.raises(KeyError):
        texto("nao_existe")