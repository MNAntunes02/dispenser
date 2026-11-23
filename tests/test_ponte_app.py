"""Ponte Firestore com o app mobile: estoque, comandos e cadastro guiado."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.coordenador import AgendaMemo, Coordenador, PublicadorLog
from core.protocolo_ui import (
    comando_cancelar_registro,
    comando_confirmar_registro,
    comando_iniciar_registro,
    comando_registrar_manual,
)
from core.sync import Sincronizador
from core.transporte import (
    TransporteFake,
    TransporteFirestore,
    _campo,
    _valor_tipado,
)
from hardware.bridge.bridge_simulada import PonteSimulada


class Resp:
    def __init__(self, status, dados=None):
        self.status_code = status
        self._dados = dados or {}

    def json(self):
        return self._dados


class Http:
    def __init__(self):
        self.chamadas = []
        self.get_docs = {"documents": []}

    def post(self, url, params=None, json=None, timeout=None):
        return Resp(200, {"idToken": "T", "expiresIn": "3600"})

    def get(self, url, headers=None, timeout=None):
        self.chamadas.append(("get", url))
        return Resp(200, self.get_docs)

    def patch(self, url, headers=None, json=None, timeout=None):
        self.chamadas.append(("patch", url, json))
        return Resp(200)


@pytest.fixture
def transporte(monkeypatch):
    http = Http()
    monkeypatch.setattr("core.transporte.requests.post", http.post)
    monkeypatch.setattr("core.transporte.requests.get", http.get)
    monkeypatch.setattr("core.transporte.requests.patch", http.patch)
    return (
        TransporteFirestore(
            projeto="p",
            usuario_id="paciente",
            api_key="k",
            email="e@x",
            senha="s",
            dispenser_id="disp",
        ),
        http,
    )


@pytest.fixture
def montagem(tmp_path):
    from core.armazenamento import Database
    from core.config import Config

    db = Database(tmp_path / "ponte.db")
    db.conectar()
    coord = Coordenador(
        Config(),
        db,
        AgendaMemo([]),
        PonteSimulada(slots=12),
        publicador_ui=PublicadorLog(),
    )
    coord.conectar()
    yield coord
    coord.finalizar()


def test_campos_firestore_preservam_tipo():
    assert _campo(7) == {"integerValue": "7"}
    assert _campo(True) == {"booleanValue": True}
    assert _campo("7") == {"stringValue": "7"}
    assert _campo(None) == {"nullValue": None}
    assert _valor_tipado(_campo({"a": 1, "b": False})) == {"a": 1, "b": False}
    assert _valor_tipado(_campo([1, "dois"])) == [1, "dois"]


def test_estoque_e_registro_publicados_em_dispensadores(transporte):
    t, http = transporte
    assert t.gravar_estoque(
        [{"slot": 1, "medicamento": "Losartana", "dosagem": "50mg",
          "quantidade": 7, "vazio": False}]
    )
    url, corpo = [c for c in http.chamadas if c[0] == "patch"][0][1:]
    assert "/Dispensadores/disp/Estoque/slot_01" in url
    campos = corpo["fields"]
    assert campos["quantidade"] == {"integerValue": "7"}
    assert campos["vazio"] == {"booleanValue": False}
    assert campos["dosagem"] == {"stringValue": "50mg"}

    assert t.gravar_registro({"registroId": "abc", "fase": "slot", "slot": 12,
                              "quantidade": 5, "mensagem": "Coloque no slot"})
    url, corpo = [c for c in http.chamadas if c[0] == "patch"][-1][1:]
    assert "/Dispensadores/disp/Registro/estado" in url
    assert corpo["fields"]["slot"] == {"integerValue": "12"}


def test_leitura_de_comandos_com_tipos(transporte):
    t, http = transporte
    http.get_docs = {
        "documents": [
            {
                "name": "projects/p/databases/(default)/documents/Dispensadores/disp/Comandos/c1",
                "fields": {
                    "tipo": {"stringValue": "registrar_manual"},
                    "status": {"stringValue": "pendente"},
                    "args": {
                        "mapValue": {
                            "fields": {
                                "registroId": {"stringValue": "abc"},
                                "quantidade": {"integerValue": "5"},
                            }
                        }
                    },
                    "criadoEm": {"stringValue": "2026-11-22T10:00:00"},
                },
            }
        ]
    }
    assert t.ler_comandos() == [
        {
            "id": "c1",
            "tipo": "registrar_manual",
            "status": "pendente",
            "args": {"registroId": "abc", "quantidade": 5},
            "criadoEm": "2026-11-22T10:00:00",
            "processadoEm": None,
        }
    ]


def test_comandos_sao_executados_uma_vez_e_marcados(db, monkeypatch):
    fake = TransporteFake()
    fake.comandos = {
        "c1": {"tipo": "registrar_manual", "status": "pendente", "args": {}},
        "c2": {"tipo": "registrar_manual", "status": "concluido", "args": {}},
        "c3": {"tipo": "cancelar_registro", "status": "pendente", "args": {}},
    }
    vistos = []
    sinc = Sincronizador(db, fake)
    assert sinc.processar_comandos(lambda cmd: vistos.append(cmd["id"]) or True) == 2
    assert sorted(vistos) == ["c1", "c3"]
    assert fake.comandos["c1"]["status"] == "concluido"
    assert fake.comandos["c1"]["resultado"] == {"ok": True}
    assert sinc.processar_comandos(lambda cmd: True) == 0


def test_comando_processando_antigo_e_retomado(db):
    fake = TransporteFake()
    antigo = (datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds")
    fake.comandos = {
        "c1": {"tipo": "registrar_manual", "status": "processando",
               "processadoEm": antigo, "args": {}}
    }
    Sincronizador(db, fake).processar_comandos(lambda cmd: False)
    assert fake.comandos["c1"]["status"] == "erro"
    assert fake.comandos["c1"]["resultado"] == {"ok": False}


def test_erro_de_rede_no_comando_nao_quebra_a_fila(db):
    fake = TransporteFake()
    fake.comandos = {"c1": {"tipo": "x", "status": "pendente", "args": {}}}
    fake.offline = True
    assert Sincronizador(db, fake).processar_comandos(lambda cmd: True) == 0


def test_registro_guiado_pelo_app_usa_id_externo_e_publica_estado(montagem):
    coord = montagem
    assert coord.entrada_ui(
        comando_iniciar_registro("Losartana", "50mg", registro_id="app-123")
    )
    estado = coord.retrato_registro()
    assert estado["registroId"] == "app-123"
    assert estado["fase"] == "posicionar"
    assert estado["medicamento"] == "Losartana"
    assert estado["dosagem"] == "50mg"

    assert coord.entrada_ui(comando_registrar_manual("app-123", 5))
    estado = coord.retrato_registro()
    assert estado["fase"] == "slot"
    assert estado["slot"] == 12
    assert "12" in estado["mensagem"]

    assert coord.entrada_ui(comando_confirmar_registro("app-123"))
    assert coord.retrato_registro()["fase"] == ""
    itens = {item["slot"]: item for item in coord.retrato_estoque()}
    assert itens[12]["quantidade"] == 5
    assert itens[12]["dosagem"] == "50mg"


def test_cancelamento_do_app_limpa_estado_do_registro(montagem):
    coord = montagem
    coord.entrada_ui(comando_iniciar_registro("X", registro_id="app-9"))
    assert coord.entrada_ui(comando_cancelar_registro("app-9")) is True
    assert coord.retrato_registro()["fase"] == ""
    assert coord.entrada_ui(comando_cancelar_registro("app-9")) is False


def test_comando_de_outro_app_nao_cancela_registro(montagem):
    coord = montagem
    coord.entrada_ui(comando_iniciar_registro("X", registro_id="app-9"))
    assert coord.entrada_ui(comando_cancelar_registro("outro")) is False
    assert coord.retrato_registro()["registroId"] == "app-9"


def test_registro_repetido_e_idempotente_e_motivo_e_exposto(montagem):
    coord = montagem
    assert coord.entrada_ui(comando_iniciar_registro("X", registro_id="app-1"))
    # Retry do app (ou comando reprocessado): não é erro.
    assert coord.entrada_ui(comando_iniciar_registro("X", registro_id="app-1"))
    assert coord.retrato_registro()["registroId"] == "app-1"
    # Outro cadastro tentando abrir ao mesmo tempo é recusado com motivo.
    assert coord.entrada_ui(comando_iniciar_registro("Y", registro_id="app-2")) is False
    assert coord.motivo_ui() == "registro_ja_andamento"


def test_resultado_do_comando_leva_o_motivo(db):
    fake = TransporteFake()
    fake.comandos = {"c1": {"tipo": "x", "status": "pendente", "args": {}}}
    sinc = Sincronizador(db, fake)
    assert sinc.processar_comandos(lambda cmd: (False, "sem_slot_vazio")) == 1
    assert fake.comandos["c1"]["status"] == "erro"
    assert fake.comandos["c1"]["resultado"] == {
        "ok": False,
        "motivo": "sem_slot_vazio",
    }


def test_comandos_pendentes_antigos_sao_cancelados_no_boot(db):
    fake = TransporteFake()
    antigo = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
    recente = datetime.now().isoformat(timespec="seconds")
    fake.comandos = {
        "antigo": {"status": "pendente", "criadoEm": antigo, "args": {}},
        "recente": {"status": "pendente", "criadoEm": recente, "args": {}},
        "processando": {
            "status": "processando",
            "criadoEm": antigo,
            "processadoEm": recente,
            "args": {},
        },
    }
    assert Sincronizador(db, fake).descartar_comandos_antigos() == 1
    assert fake.comandos["antigo"]["status"] == "cancelado"
    assert fake.comandos["recente"]["status"] == "pendente"
    assert fake.comandos["processando"]["status"] == "processando"


def test_saude_publicada_em_registro_saude(transporte):
    t, http = transporte
    assert t.gravar_saude({"ativa": True})
    url, corpo = [c for c in http.chamadas if c[0] == "patch"][-1][1:]
    assert "/Dispensadores/disp/Registro/saude" in url
    assert corpo["fields"]["ativa"] == {"booleanValue": True}
    assert corpo["fields"]["ultimoTick"]["stringValue"]


def test_atender_dispositivo_publica_saude(db):
    fake = TransporteFake()
    fake.comandos = {"c1": {"status": "pendente", "tipo": "x", "args": {}}}
    resumo = Sincronizador(db, fake).atender_dispositivo(
        lambda cmd: True, [], {}, saude={"ativa": True}
    )
    assert resumo["comandos"] == 1
    assert fake.saude["ativa"] is True
