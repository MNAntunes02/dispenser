"""Fluxo de registro de cartela e baixa do estoque no coordenador."""

from __future__ import annotations

from datetime import datetime

import pytest

from core.agendador import Ocorrencia
from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador, PublicadorLog
from core.estoque import ServicoEstoque
from core.protocolo_ui import (
    comando_confirmar_registro,
    comando_iniciar_registro,
    comando_liberar_proximo,
    comando_registrar_leitura,
    comando_registrar_manual,
)
from hardware.bridge.bridge_simulada import PonteSimulada


@pytest.fixture
def montagem(tmp_path):
    db = Database(tmp_path / "registro.db")
    db.conectar()
    publicador = PublicadorLog()
    coord = Coordenador(
        Config(),
        db,
        AgendaMemo([]),
        PonteSimulada(slots=12),
        publicador_ui=publicador,
    )
    coord.conectar()
    yield coord, db, publicador
    coord.finalizar()


def _ultima_tela(publicador: PublicadorLog) -> dict:
    return [msg for msg in publicador.mensagens if msg["type"] == "estado"][-1]


def _ultimo_estoque(publicador: PublicadorLog) -> dict:
    return [msg for msg in publicador.mensagens if msg["type"] == "estoque"][-1]


def test_registro_por_leitura_escolhe_slot_12_e_confirma(montagem):
    coord, _db, publicador = montagem

    assert coord.entrada_ui(comando_iniciar_registro("Losartana 50 mg")) is True
    posicionar = _ultima_tela(publicador)
    assert posicionar["chave"] == "registro_posicionar"
    assert posicionar["fluxo"] == "registro"
    registro_id = posicionar["registroId"]

    assert coord.entrada_ui(comando_registrar_leitura(registro_id, 7)) is True
    escolhido = _ultima_tela(publicador)
    assert escolhido["chave"] == "registro_slot"
    assert escolhido["slot"] == 12
    assert escolhido["quantidade"] == 7
    assert "12" in escolhido["mensagem"]

    assert coord.entrada_ui(comando_confirmar_registro(registro_id)) is True
    itens = {item["slot"]: item for item in _ultimo_estoque(publicador)["itens"]}
    assert itens[12]["quantidade"] == 7
    assert itens[12]["medicamento"] == "Losartana 50 mg"
    assert itens[12]["vazio"] is False
    assert _ultima_tela(publicador)["chave"].startswith("reposo")


def test_registro_manual_sem_id_funciona_como_fallback(montagem):
    coord, _db, publicador = montagem

    coord.entrada_ui(comando_iniciar_registro())
    assert coord.entrada_ui(comando_registrar_manual("", 5)) is True
    assert _ultima_tela(publicador)["slot"] == 12
    assert coord.entrada_ui(comando_confirmar_registro("")) is True

    itens = {item["slot"]: item for item in _ultimo_estoque(publicador)["itens"]}
    assert itens[12]["quantidade"] == 5


def test_novos_registros_preferem_o_maior_slot_vazio(montagem):
    coord, _db, publicador = montagem

    for slot, quantidade in ((12, 10), (11, 8)):
        coord.entrada_ui(comando_iniciar_registro())
        coord.entrada_ui(comando_registrar_manual("", quantidade))
        coord.entrada_ui(comando_confirmar_registro(""))

    coord.entrada_ui(comando_iniciar_registro())
    coord.entrada_ui(comando_registrar_manual("", 3))
    assert _ultima_tela(publicador)["slot"] == 10


def test_leitura_invalida_nao_escolhe_slot_e_pode_ser_refeita(montagem):
    coord, _db, publicador = montagem

    coord.entrada_ui(comando_iniciar_registro())
    registro_id = _ultima_tela(publicador)["registroId"]

    assert coord.entrada_ui(comando_registrar_leitura(registro_id, 0)) is False
    assert _ultima_tela(publicador)["chave"] == "registro_invalido"

    assert coord.entrada_ui(comando_registrar_leitura(registro_id, 9)) is True
    assert _ultima_tela(publicador)["chave"] == "registro_slot"


def test_sem_slot_vazio_aborta_o_registro(montagem):
    coord, db, publicador = montagem
    servico = ServicoEstoque(db)
    for slot in range(1, 13):
        servico.registrar(slot, 1)

    coord.entrada_ui(comando_iniciar_registro())
    assert coord.entrada_ui(comando_registrar_manual("", 4)) is False
    assert _ultima_tela(publicador)["chave"] == "registro_sem_slot"
    assert coord.entrada_ui(comando_confirmar_registro("")) is False


def test_baixa_acontece_na_liberacao_da_dose(montagem):
    coord, db, publicador = montagem
    servico = ServicoEstoque(db)
    servico.registrar(12, 7)

    occ = Ocorrencia(
        id="occ-1",
        medicamento="med-1",
        medicamento_nome="Losartana",
        dosagem="1 comprimido",
        slot=12,
        dia=datetime.now().date().isoformat(),
        horario="08:00",
    )
    db.inserir_ocorrencia_se_nova(occ)
    db.atualizar_ocorrencia("occ-1", estado="AGUARDANDO_DETECCAO")
    coord._carregar_ativa()

    assert coord.entrada_ui(comando_liberar_proximo()) is True
    itens = {item["slot"]: item for item in _ultimo_estoque(publicador)["itens"]}
    assert itens[12]["quantidade"] == 6

    assert coord.entrada_ui(comando_liberar_proximo()) is False
    itens = {item["slot"]: item for item in _ultimo_estoque(publicador)["itens"]}
    assert itens[12]["quantidade"] == 6


def test_retrato_inclui_estoque(montagem):
    coord, _db, _publicador = montagem

    mensagens = coord.retrato()
    assert [msg["type"] for msg in mensagens] == [
        "rotulos",
        "agenda",
        "estoque",
    ]
    assert len(mensagens[-1]["itens"]) == 12
