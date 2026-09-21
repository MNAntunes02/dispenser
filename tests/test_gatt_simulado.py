"""Testes do GATT simulado: identidade, carga e notificações."""

from __future__ import annotations

import json

import pytest

from core.provisionamento import Provisionador
from hardware.gatt.servico_gatt import ReceptorCarga, ServicoGattSimulado
from hardware.tela import TelaSimulada
from rede.rede import RedeSimulada


def _carga(codigo: str = "123456") -> dict:
    return {
        "codigo": codigo,
        "wifi": {"ssid": "Casa", "senha": "s"},
        "firebase": {"projectId": "p", "apiKey": "a", "usuarioId": "u"},
    }


def _servico(tmp_path):
    prov = Provisionador(
        rede=RedeSimulada(),
        tela=TelaSimulada(),
        caminho_env=tmp_path / "dispenser.env",
        gerar=lambda: "123456",
    )
    gatt = ServicoGattSimulado()
    gatt.iniciar(prov)
    return gatt, prov


def test_iniciar_notifica_aguardando_e_expõe_identidade(tmp_path):
    gatt, prov = _servico(tmp_path)
    assert gatt.ativo
    assert gatt.notificacoes[-1] == {"estado": Provisionador.ESTADO_AGUARDANDO}
    identidade = gatt.ler_identidade()
    assert identidade["uid"] == ""
    assert identidade["nome"]


def test_escrever_carga_provisiona_e_notifica_ok(tmp_path):
    gatt, prov = _servico(tmp_path)
    gatt.escrever_carga(_carga())
    assert prov.provisionado
    assert gatt.notificacoes[-1] == {"estado": Provisionador.ESTADO_OK}


def test_pedacos_fora_de_ordem_remontam(tmp_path):
    gatt, prov = _servico(tmp_path)
    carga = json.dumps(_carga(), ensure_ascii=False)
    partes = [carga[i : i + 120] for i in range(0, len(carga), 120)]
    assert len(partes) >= 2
    gatt.escrever_pedacos([{"seq": 1, "total": len(partes), "dados": partes[1]}])
    assert not prov.provisionado
    gatt.escrever_pedacos([{"seq": 0, "total": len(partes), "dados": partes[0]}])
    assert prov.provisionado


def test_codigo_errado_notifica_erro(tmp_path):
    gatt, prov = _servico(tmp_path)
    gatt.escrever_carga(_carga(codigo="999999"))
    assert gatt.notificacoes[-1]["estado"] == Provisionador.ESTADO_ERRO


def test_parar_encerra_servico(tmp_path):
    gatt, _ = _servico(tmp_path)
    gatt.parar()
    assert not gatt.ativo


def test_receptor_entrega_carga_dict():
    recebido = []
    receptor = ReceptorCarga(recebido.append)
    receptor.empurrar({"seq": 0, "total": 1, "dados": json.dumps({"x": 1})})
    assert recebido == [{"x": 1}]


def test_receptor_json_invalido_lanca():
    receptor = ReceptorCarga(lambda _carga: None)
    with pytest.raises(Exception):
        receptor.empurrar({"seq": 0, "total": 1, "dados": "não-json"})