"""Testes do estoque de cartelas (core/estoque.py e core/slots.py)."""

from __future__ import annotations

from datetime import datetime

import pytest

from core.armazenamento import Database
from core.estoque import ItemEstoque, ServicoEstoque, validar_quantidade
from core.slots import (
    SLOTS,
    TOTAL_SLOTS,
    coluna_slot,
    linha_slot,
    posicoes_slots,
    validar_slot,
)


def test_slots_sao_1_a_12():
    assert TOTAL_SLOTS == 12
    assert SLOTS == tuple(range(1, 13))


def test_layout_em_duas_colunas_crescente():
    assert [item["slot"] for item in posicoes_slots()] == [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
    ]
    assert [item["coluna"] for item in posicoes_slots()] == [
        "esquerda", "direita",
    ] * 6
    assert [item["linha"] for item in posicoes_slots()] == [
        linha for linha in range(6) for _ in range(2)
    ]
    assert [slot for slot in SLOTS if coluna_slot(slot) == "esquerda"] == [
        1, 3, 5, 7, 9, 11,
    ]
    assert [slot for slot in SLOTS if coluna_slot(slot) == "direita"] == [
        2, 4, 6, 8, 10, 12,
    ]


@pytest.mark.parametrize("valor", [0, 13, -1, "x", None])
def test_slot_fora_da_faixa_e_rejeitado(valor):
    with pytest.raises(ValueError):
        validar_slot(valor)


@pytest.mark.parametrize("valor", [0, -1, 1000, "x", None])
def test_quantidade_fora_da_faixa_e_rejeitada(valor):
    with pytest.raises(ValueError):
        validar_quantidade(valor)


def test_mensagem_tem_12_slots_com_posicao_e_quantidade(db: Database):
    servico = ServicoEstoque(db)
    servico.registrar(3, 8, "Losartana")

    mensagem = servico.mensagem()

    assert len(mensagem) == 12
    slot3 = mensagem[2]
    assert slot3 == {
        "slot": 3,
        "rotulo": "Slot 3",
        "linha": 1,
        "coluna": "esquerda",
        "medicamento": "Losartana",
        "quantidade": 8,
        "vazio": False,
    }
    assert mensagem[11]["vazio"] is True


def test_registro_escolhe_o_maior_slot_vazio(db: Database):
    servico = ServicoEstoque(db)
    assert servico.slot_vazio_maior() == 12

    servico.registrar(12, 10)
    assert servico.slot_vazio_maior() == 11
    servico.registrar(11, 4)
    assert servico.slot_vazio_maior() == 10


def test_registro_substitui_cartela_do_mesmo_slot(db: Database):
    servico = ServicoEstoque(db)
    servico.registrar(5, 3, "Antigo")
    servico.registrar(5, 20, "Novo")

    itens = {item.slot: item for item in servico.itens()}
    assert itens[5] == ItemEstoque(5, "Novo", 20, itens[5].atualizado_em)


def test_baixa_e_idempotente_por_ocorrencia(db: Database):
    servico = ServicoEstoque(db)
    servico.registrar(12, 2)

    assert servico.baixar(12, "occ-1") is True
    assert servico.baixar(12, "occ-1") is False
    assert servico.baixar(12, "occ-2") is True
    assert servico.baixar(12, "occ-3") is True
    assert {item.slot: item.quantidade for item in servico.itens()}[12] == 0


def test_relogio_injetavel_usa_mesma_trilha(tmp_path):
    relogio = datetime(2026, 11, 17, 8, 0, 0)
    banco = Database(tmp_path / "outro.db", relogio=lambda: relogio)
    banco.conectar()
    try:
        servico = ServicoEstoque(banco)
        servico.registrar(1, 4)
        assert servico.itens()[0].atualizado_em == "2026-11-17T08:00:00"
    finally:
        banco.fechar()
