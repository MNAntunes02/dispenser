"""Testes de esqueleto da Fase 1: módulos importam e contratos existem."""

import pytest

from core.armazenamento import Database
from core.agendador import Agendador
from core.maquina_estados import Fase, MaquinaEstados
from core.notificador import Notificador
from core.sync import SyncService
from hardware.bridge.hardware_bridge import HardwareBridge


def test_modulos_core_importam():
    assert Database.__name__ == "Database"
    assert Agendador.__name__ == "Agendador"
    assert MaquinaEstados.__name__ == "MaquinaEstados"
    assert Notificador.__name__ == "Notificador"
    assert SyncService.__name__ == "SyncService"


def test_fases_da_dose_definidas():
    fases = {f.value for f in Fase}
    assert fases == {
        "espera",
        "alarme",
        "abrir",
        "ingerir",
        "devolver",
        "confirmada",
        "perdida",
        "retorno_pendente",
    }


def test_ponte_implementa_contrato():
    from hardware.bridge.bridge_simulada import PonteSimulada

    assert issubclass(PonteSimulada, HardwareBridge)


def test_banco_ok(db):
    db.conexao.execute("select 1")
    assert db.conexao is not None


def test_transicao_pendente_de_implementacao(ponte_simulada, db):  # noqa: ARG001
    maquina = MaquinaEstados()
    with pytest.raises(NotImplementedError):
        maquina.transicionar("gaveta_aberta")


def test_status_da_ponte_simulada(ponte_simulada):
    assert ponte_simulada.status()["gaveta"] == 0
    assert set(ponte_simulada.status()["slots"]) == {"0", "1", "2", "3"}


def test_eventos_injetados_chegam_ao_handler(ponte_simulada):
    recebidos = []

    def handler(evento):
        recebidos.append(evento)

    ponte_simulada.registrar_evento(handler)
    ponte_simulada.simular({"e": "gaveta_aberta"})
    ponte_simulada.simular({"e": "slot_presente", "slot": 2})

    assert [e["e"] for e in recebidos] == ["gaveta_aberta", "slot_presente"]
    assert ponte_simulada.status()["gaveta"] == 1
    assert ponte_simulada.status()["slots"]["2"]["presente"] == 1