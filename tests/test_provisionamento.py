"""Testes do provisionamento de primeiro uso (Fase 3b).

Usa RedeSimulada/TelaSimulada + relógio/gerador fixos: nada de hardware, rede
ou sistema é exercitado.
"""

from __future__ import annotations

import json
import os

import pytest

from core.provisionamento import (
    CargaInvalida,
    MontadorChunks,
    Provisionador,
    validar_carga,
)
from hardware.tela import TelaSimulada
from rede.rede import RedeSimulada

CODIGO = "123456"


def _exemplo_carga(codigo: str = CODIGO) -> dict:
    return {
        "codigo": codigo,
        "wifi": {"ssid": "MinhaRede", "senha": "segredo"},
        "firebase": {
            "projectId": "app-saude-8fba1",
            "apiKey": "AIza...",
            "usuarioId": "paciente-123",
        },
    }


@pytest.fixture
def ambiente(tmp_path):
    rede = RedeSimulada()
    tela = TelaSimulada()
    env = tmp_path / "dispenser.env"
    relogio = {"agora": 1000.0}

    def _relogio() -> float:
        return relogio["agora"]

    prov = Provisionador(
        rede=rede,
        tela=tela,
        caminho_env=env,
        uid="uid-dispenser-9",
        nome="disp-test",
        relogio=_relogio,
        gerar=lambda: CODIGO,
    )
    return {"rede": rede, "tela": tela, "env": env, "relogio": relogio, "prov": prov}


def test_inicio_gera_codigo_de_seis_digitos_e_exibe(ambiente):
    prov = ambiente["prov"]
    exibido = " ".join(ambiente["tela"].exibido)
    assert CODIGO in exibido
    assert prov.status()["estado"] == Provisionador.ESTADO_AGUARDANDO
    assert not prov.provisionado


def test_receber_carga_ok_aplica_rede_e_grava_env(ambiente):
    prov = ambiente["prov"]
    assert prov.receber_carga(_exemplo_carga()) is True

    rede = ambiente["rede"]
    assert rede.conexoes == [("MinhaRede", "segredo")]
    assert prov.provisionado
    assert prov.status()["estado"] == Provisionador.ESTADO_OK
    assert "Provisionado" in " ".join(ambiente["tela"].exibido)

    texto = ambiente["env"].read_text(encoding="utf-8")
    assert "FIREBASE_PROJECT_ID=app-saude-8fba1" in texto
    assert "DISPENSER_FIREBASE_API_KEY=AIza..." in texto
    assert "DISPENSER_USER_ID=paciente-123" in texto
    modo = os.stat(ambiente["env"]).st_mode & 0o777
    assert modo == 0o600


def test_codigo_errado_nega(ambiente):
    prov = ambiente["prov"]
    assert prov.receber_carga(_exemplo_carga(codigo="000000")) is False
    assert prov.status()["estado"] == Provisionador.ESTADO_ERRO
    assert not ambiente["rede"].conexoes


def test_codigo_expirado_nega(ambiente):
    prov, relogio = ambiente["prov"], ambiente["relogio"]
    relogio["agora"] += 601
    assert prov.codigo_valido(CODIGO) is False
    assert prov.receber_carga(_exemplo_carga()) is False


def test_carga_malformada_vira_erro_sem_tocar_na_rede(tmp_path):
    rede = RedeSimulada()
    prov = Provisionador(
        rede=rede,
        tela=TelaSimulada(),
        caminho_env=tmp_path / "dispenser.env",
        gerar=lambda: CODIGO,
    )
    assert prov.receber_carga({"codigo": CODIGO}) is False
    status = prov.status()
    assert status["estado"] == Provisionador.ESTADO_ERRO
    assert "invá" in status["erro"]
    assert not rede.conexoes


def test_ja_provisionado_recusa(ambiente):
    prov = ambiente["prov"]
    prov.receber_carga(_exemplo_carga())
    codigo_rise = _exemplo_carga()
    codigo_rise["wifi"] = {"ssid": "Outra", "senha": "x"}
    assert prov.receber_carga(codigo_rise) is False
    assert ambiente["rede"].conexoes == [("MinhaRede", "segredo")]


def test_reiniciar_entra_de_novo_no_modo(ambiente):
    prov = ambiente["prov"]
    prov.receber_carga(_exemplo_carga())
    prov.reiniciar()
    assert not prov.provisionado
    assert prov.status()["estado"] == Provisionador.ESTADO_AGUARDANDO
    assert prov.codigo_valido(CODIGO)


def test_falha_de_rede_gera_erro(tmp_path):
    rede = RedeSimulada(sucesso=False)
    prov = Provisionador(
        rede=rede,
        tela=TelaSimulada(),
        caminho_env=tmp_path / "dispenser.env",
        gerar=lambda: CODIGO,
    )
    assert prov.receber_carga(_exemplo_carga()) is False
    assert prov.status()["erro"] == "falha no Wi-Fi"
    assert not (tmp_path / "dispenser.env").exists()


def test_identidade_tem_uid_e_nome(ambiente):
    assert ambiente["prov"].identidade() == {"uid": "uid-dispenser-9", "nome": "disp-test"}


def test_validar_carga():
    with pytest.raises(CargaInvalida):
        validar_carga(_exemplo_carga(codigo="abc"))
    with pytest.raises(CargaInvalida):
        validar_carga(_exemplo_carga()["wifi"])
    sem_senha = _exemplo_carga()
    sem_senha["wifi"].pop("senha")
    with pytest.raises(CargaInvalida):
        validar_carga(sem_senha)
    sem_projeto = _exemplo_carga()
    sem_projeto["firebase"].pop("projectId")
    with pytest.raises(CargaInvalida):
        validar_carga(sem_projeto)
    assert validar_carga(_exemplo_carga()).ssid == "MinhaRede"


def test_montador_chunks_fora_de_ordem():
    montador = MontadorChunks()
    carga = json.dumps(_exemplo_carga(), ensure_ascii=False)
    partes = [carga[i : i + 60] for i in range(0, len(carga), 60)]
    assert len(partes) >= 3
    pecas = [{"seq": i, "total": len(partes), "dados": p} for i, p in enumerate(partes)]
    resultado = None
    for seq in range(len(partes) - 1, -1, -1):
        resultado = montador.adicionar(pecas[seq])
    assert json.loads(resultado) == _exemplo_carga()


def test_montador_chunks_rejeita_pedacos_invalidos():
    montador = MontadorChunks()
    with pytest.raises(CargaInvalida):
        montador.adicionar({"seq": 0, "total": 2, "dados": "x" * 241})
    with pytest.raises(CargaInvalida):
        montador.adicionar({"seq": 0, "total": 0, "dados": "x"})
    with pytest.raises(CargaInvalida):
        montador.adicionar({"seq": 9, "total": 3, "dados": "x"})
    with pytest.raises(CargaInvalida):
        montador.adicionar({"seq": 0, "total": 1, "dados": 123})
    montador2 = MontadorChunks()
    montador2.adicionar({"seq": 0, "total": 2, "dados": "x"})
    with pytest.raises(CargaInvalida):
        montador2.adicionar({"seq": 0, "total": 3, "dados": "y"})