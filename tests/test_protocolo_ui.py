"""Testes do contrato de mensagens core <-> UI (core/protocolo_ui.py)."""

from datetime import datetime

import pytest

from core.protocolo_ui import (
    ACOES_DE_ENTRADA,
    EVENTOS_SIMULAVEIS,
    EVENTOS_SIMULAVEIS_COM_SLOT,
    TIPOS_DA_UI,
    TIPOS_DO_CORE,
    VERSAO,
    ProtocoloInvalido,
    CHAVES_REGISTRO,
    COMANDOS_REGISTRO,
    FLUXO_REGISTRO,
    codificar,
    comando_confirmar_registro,
    comando_iniciar_registro,
    comando_liberar_proximo,
    comando_registrar_leitura,
    comando_registrar_manual,
    comando_simular,
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


def test_chaves_de_registro_nao_tem_passo_de_dose():
    assert set(CHAVES_REGISTRO) == {
        "registro_posicionar",
        "registro_slot",
        "registro_invalido",
        "registro_sem_slot",
    }
    assert all(passo_de(chave) is None for chave in CHAVES_REGISTRO)


def test_estoque_e_comandos_de_registro_seguem_o_contrato():
    assert FLUXO_REGISTRO == "registro"
    assert set(COMANDOS_REGISTRO) == {
        "iniciar_registro",
        "registrar_leitura",
        "registrar_manual",
        "confirmar_registro",
        "cancelar_registro",
    }
    mensagem = envelope("estoque", lambda: RELOGIO, itens=[])
    assert decodificar(codificar(mensagem), tipos=TIPOS_DO_CORE) == mensagem


def test_apenas_confirma_e_aceita_como_acao_de_entrada():
    # Política aprovada: sem soneca. A UI não pode pedir "silenciar"/"pular".
    assert ACOES_DE_ENTRADA == ("confirma",)


def test_tipos_declarados_sao_disjuntos_e_conhecidos():
    assert set(TIPOS_DO_CORE) & set(TIPOS_DA_UI) == {"health"}
    assert "estado" in TIPOS_DO_CORE
    assert "input" in TIPOS_DA_UI


def test_rotulos_e_agenda_sao_publicados_pelo_core():
    """O retrato da UI começa por `rotulos` (idioma) e `agenda` (dia)."""
    assert set(TIPOS_DO_CORE) == {
        "rotulos",
        "agenda",
        "estado",
        "alerta",
        "health",
        "estoque",
    }


def test_passo_do_fluxo_guiado():
    assert passo_de("abra_gaveta") == 1
    assert passo_de("consuma_e_detectar") == 2
    assert passo_de("devolva_slot") == 3
    assert passo_de("aviso_retorno") == 3
    assert passo_de("tudo_certo") == 4


def test_passo_none_fora_do_fluxo():
    assert passo_de("falha") is None
    assert passo_de("gaveta_fora_de_horario") is None
    assert passo_de("chave_desconhecida") is None
    assert passo_de(None) is None


# --- comando `liberar_proximo` (painel/CLI) ---------------------------------


def test_comando_liberar_proximo_monta_envelope_do_contrato():
    msg = comando_liberar_proximo()
    assert msg["type"] == "comando"
    assert msg["cmd"] == "liberar_proximo"
    assert "args" not in msg
    assert decodificar(codificar(msg), tipos=TIPOS_DA_UI) == msg


# --- comandos de registro de cartela ---------------------------------------


def test_comandos_de_registro_montam_envelopes_do_contrato():
    mensagens = (
        comando_iniciar_registro("Losartana"),
        comando_registrar_leitura("abc123", 8),
        comando_registrar_manual("abc123", 6),
        comando_confirmar_registro("abc123"),
    )
    for msg in mensagens:
        assert msg["type"] == "comando"
        assert msg["cmd"] in COMANDOS_REGISTRO
        assert decodificar(codificar(msg), tipos=TIPOS_DA_UI) == msg

    assert mensagens[0]["args"] == {"medicamento": "Losartana"}
    assert mensagens[1]["args"] == {"registroId": "abc123", "quantidade": 8}
    assert mensagens[3]["args"] == {"registroId": "abc123"}


def test_iniciar_registro_sem_medicamento_nao_envia_args():
    assert "args" not in comando_iniciar_registro()


# --- comando `simular` (ADR 015, painel de desenvolvimento) ------------------


def test_comando_simular_monta_envelope_do_contrato():
    msg = comando_simular("gaveta_aberta")
    assert msg["type"] == "comando"
    assert msg["cmd"] == "simular"
    assert msg["args"] == {"evento": "gaveta_aberta"}
    # a linha produzida é aceita pelo contrato da UI -> core
    assert decodificar(codificar(msg), tipos=TIPOS_DA_UI) == msg


def test_comando_simular_inclui_slot_quando_recebido():
    msg = comando_simular("slot_ausente", 0)
    assert msg["args"] == {"evento": "slot_ausente", "slot": 0}


@pytest.mark.parametrize(
    "evento", ["ok", "botao", "falha", "horario_chegou", "retorno_ok", ""]
)
def test_comando_simular_rejeita_evento_fora_da_whitelist(evento):
    with pytest.raises(ValueError):
        comando_simular(evento)


def test_comando_simular_rejeita_slot_em_evento_sem_slot():
    with pytest.raises(ValueError):
        comando_simular("gaveta_aberta", 0)


def test_eventos_simulaveis_so_cobrem_sensores_de_gaveta_e_slot():
    # Regra de segurança do paciente: simular sensor, nunca confirmar dose
    # (`ok`/`botao` do paciente) nem fabricar falha de sensor.
    assert set(EVENTOS_SIMULAVEIS) == {
        "gaveta_aberta",
        "gaveta_fechada",
        "slot_presente",
        "slot_ausente",
    }
    assert set(EVENTOS_SIMULAVEIS_COM_SLOT) <= set(EVENTOS_SIMULAVEIS)
