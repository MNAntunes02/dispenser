"""Testes de esqueleto: módulos importam e contratos existem."""

from core.agendador import Agendador
from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador, PublicadorLog
from core.maquina_estados import Fase, processar
from core.notificador import Notificador
from core.sync import FonteAgendaLocal, Sincronizador, SyncService
from core.transporte import Transporte, TransporteFirestore
from hardware.bridge.hardware_bridge import HardwareBridge


def test_modulos_core_importam():
    assert Database.__name__ == "Database"
    assert Agendador.__name__ == "Agendador"
    assert processar.__name__ == "processar"
    assert Notificador.__name__ == "Notificador"
    assert SyncService.__name__ == "SyncService"
    assert Sincronizador.__name__ == "Sincronizador"
    assert FonteAgendaLocal.__name__ == "FonteAgendaLocal"
    assert TransporteFirestore.__name__ == "TransporteFirestore"
    assert issubclass(TransporteFirestore, Transporte)
    assert Coordenador.__name__ == "Coordenador"
    assert AgendaMemo.__name__ == "AgendaMemo"
    assert PublicadorLog.__name__ == "PublicadorLog"


def test_fases_da_dose_definidas():
    fases = {f.value for f in Fase}
    assert fases == {
        "AGUARDANDO",
        "ALARME",
        "AGUARDANDO_GAVETA",
        "GAVETA_ABERTA",
        "MEDICAMENTO_RETIRADO",
        "AGUARDANDO_RETORNO",
        "RETORNO_PENDENTE",
        "CONCLUIDA",
        "NAO_ATENDIDA",
        "FALHA",
    }


def test_config_de_env_usa_padroes():
    cfg = Config.de_env()
    assert cfg.intervalo_alarme_s == 120
    assert cfg.max_tentativas == 5
    assert cfg.limite_retorno_s == 1800


def test_ponte_implementa_contrato():
    from hardware.bridge.bridge_simulada import PonteSimulada

    assert issubclass(PonteSimulada, HardwareBridge)


def test_banco_ok(db):
    db.conexao.execute("select 1")
    assert db.conexao is not None


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