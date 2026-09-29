"""Testes do contrato de mensagens core <-> UI (core/protocolo_ui.py)."""

from datetime import datetime

import pytest

from core.protocolo_ui import (
    ACOES_DE_ENTRADA,
    TIPOS_DA_UI,
    TIPOS_DO_CORE,
    VERSAO,
    ProtocoloInvalido,
    codificar,
    decodificar,
    envelope,
    passo_de,
)

RELOGIO = datetime(2026, 9, 29, 8, 0, 0)


def test_envelope_tem_versao_tipo_e_timestamp():
    msg = envelope("estado", lambda: RELOGIO, fase="ALARME", passo=1)
    assert msg["v"] == VERSAO
    assert msg["type"] == "estado"
    assert msg["ts"] == "2026-09-29T08:00:00"
    assert msg["fase"] == "ALARME"


def test_envelope_omite_campos_vazios():
    msg = envelope("estado", lambda: RELOGIO, slot=None, proxima="")
    assert "slot" not in msg
    assert msg["proxima"] == ""


def test_codificar_e_uma_linha_utf8():
    linha = codificar(envelope("alerta", lambda: RELOGIO, mensagem="Falha F003"))
    assert linha.endswith("\n")
    assert linha.count("\n") == 1
    assert "Falha F003" in linha


def test_decodificar_aceita_mensagens_do_contrato():
    msg = decodificar(codificar(envelope("health", lambda: RELOGIO)), tipos=TIPOS_DA_UI)
    assert msg["type"] == "health"


@pytest.mark.parametrize(
    "linha",
    [
        "",
        "   ",
        "não é json",
        "[1, 2, 3]",
        '{"v": 99, "type": "health"}',
        '{"v": 1, "ts": "x"}',
        '{"type": "health"}',
    ],
)
def test_decodificar_rejeita_linha_invalida(linha):
    with pytest.raises(ProtocoloInvalido):
        decodificar(linha)


def test_decodificar_rejeita_tipo_fora_do_contrato():
    with pytest.raises(ProtocoloInvalido):
        decodificar('{"v": 1, "type": "doses"}', tipos=TIPOS_DA_UI)


def test_decodificar_rejeita_linha_acima_do_limite():
    with pytest.raises(ProtocoloInvalido):
        decodificar('{"v": 1, "type": "health", "x": "' + "a" * 70000 + '"}')


def test_apenas_confirma_e_aceita_como_acao_de_entrada():
    # Política aprovada: sem soneca. A UI não pode pedir "silenciar"/"pular".
    assert ACOES_DE_ENTRADA == ("confirma",)


def test_tipos_declarados_sao_disjuntos_e_conhecidos():
    assert set(TIPOS_DO_CORE) & set(TIPOS_DA_UI) == {"health"}
    assert "estado" in TIPOS_DO_CORE
    assert "input" in TIPOS_DA_UI


def test_rotulos_e_agenda_sao_publicados_pelo_core():
    """O retrato da UI começa por `rotulos` (idioma) e `agenda` (dia)."""
    assert set(TIPOS_DO_CORE) == {"rotulos", "agenda", "estado", "alerta", "health"}


def test_passo_do_fluxo_guiado():
    assert passo_de("hora_remedio") == 1
    assert passo_de("abra_gaveta") == 2
    assert passo_de("retire_medicamento") == 3
    assert passo_de("tome_e_ok") == 4
    assert passo_de("devolva_slot") == 5
    assert passo_de("tudo_certo") == 6


def test_passo_none_fora_do_fluxo():
    assert passo_de("falha") is None
    assert passo_de("gaveta_fora_de_horario") is None
    assert passo_de("chave_desconhecida") is None
    assert passo_de(None) is None
