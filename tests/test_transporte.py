"""Testes do transporte Firestore: mapeamentos, token e comportamento de rede."""

import pytest
import requests

from core.transporte import (
    AutenticacaoFalhou,
    ErroTransporte,
    TransporteFake,
    TransporteFirestore,
    doc_historico_id,
    normalizar_medicamentos,
    registro_historico,
)

_DOC_MED = {
    "name": "projects/p/databases/(default)/documents/UsuarioMedicamento/u/Medicamentos/med1",
    "fields": {
        "nome": {"stringValue": "Paracetamol"},
        "dosagem": {"stringValue": "500"},
        "dias": {
            "arrayValue": {
                "values": [
                    {
                        "mapValue": {
                            "fields": {
                                "dia_semana": {"stringValue": "sáb"},
                                "horario": {
                                    "arrayValue": {
                                        "values": [
                                            {"stringValue": "08:00"},
                                            {"stringValue": "20:00"},
                                        ]
                                    }
                                },
                            }
                        }
                    }
                ]
            }
        },
    },
}


class Resp:
    def __init__(self, status, dados=None):
        self.status_code = status
        self._dados = dados or {}

    def json(self):
        return self._dados


class FakeHttp:
    def __init__(self):
        self.chamadas = []
        self.auth = Resp(200, {"idToken": "T1", "refreshToken": "R1", "expiresIn": "3600"})
        self.token = Resp(200, {"access_token": "T2", "refresh_token": "R2", "expires_in": "3600"})
        self.get_status = 200
        self.get_docs = {"documents": []}
        self.get_401 = 0
        self.get_offline = False
        self.patch_status = 200
        self.patch_offline = False

    def post(self, url, params=None, json=None, timeout=None):
        self.chamadas.append(("post", url, json))
        return self.token if "securetoken" in url else self.auth

    def get(self, url, headers=None, timeout=None):
        self.chamadas.append(("get", url, headers))
        if self.get_offline:
            raise requests.exceptions.ConnectionError("sem rede")
        if self.get_401 > 0:
            self.get_401 -= 1
            return Resp(401)
        return Resp(self.get_status, self.get_docs)

    def patch(self, url, headers=None, json=None, timeout=None):
        self.chamadas.append(("patch", url, headers, json))
        if self.patch_offline:
            raise requests.exceptions.ConnectionError("sem rede")
        return Resp(self.patch_status)


def _transporte(monkeypatch):
    http = FakeHttp()
    monkeypatch.setattr("core.transporte.requests.post", http.post)
    monkeypatch.setattr("core.transporte.requests.get", http.get)
    monkeypatch.setattr("core.transporte.requests.patch", http.patch)
    t = TransporteFirestore(
        projeto="p", usuario_id="u", api_key="k", email="e@x", senha="s"
    )
    return t, http


def test_normalizar_medicamentos_para_agendador():
    meds = normalizar_medicamentos([_DOC_MED])
    assert meds == [
        {
            "id": "med1",
            "nome": "Paracetamol",
            "dosagem": "500",
            "dias": [{"dia_semana": "sáb", "horario": ["08:00", "20:00"]}],
        }
    ]


def test_normalizar_ignora_docs_sem_nome():
    sem_nome = {**_DOC_MED, "fields": {"dosagem": {"stringValue": "1"}}}
    assert normalizar_medicamentos([sem_nome]) == []


def test_doc_historico_id_deterministico():
    a = doc_historico_id("m1|2026-09-19|08:00")
    b = doc_historico_id("m1|2026-09-19|08:00")
    assert a == b
    assert a.startswith("h")
    assert a != doc_historico_id("m2|2026-09-19|08:00")


def test_registro_historico_formato_do_app():
    occ = {"dia": "2026-09-19", "horario": "08:00", "medicamento_nome": "Paracetamol"}
    payload = {"horario_real": "2026-09-19T08:05:00"}
    assert registro_historico(occ, payload) == {
        "dia": "19/09/2026",
        "horario_previsto": "08:00",
        "horario_real": "08:05",
        "nome": "Paracetamol",
    }


def test_registro_sem_horario_real_valido_nao_envia():
    occ = {"dia": "2026-09-19", "horario": "08:00", "medicamento_nome": "X"}
    assert registro_historico(occ, {}) is None
    assert registro_historico(occ, {"horario_real": "invalido"}) is None


def test_primeira_sessao_loga_e_le_medicamentos(monkeypatch):
    t, http = _transporte(monkeypatch)
    http.get_docs = {"documents": [_DOC_MED]}
    meds = t.ler_medicamentos()
    assert [m["id"] for m in meds] == ["med1"]
    assert t.autenticado is True
    login = [c for c in http.chamadas if c[0] == "post" and "signInWithPassword" in c[1]]
    assert login
    cab = [c for c in http.chamadas if c[0] == "get"][0][2]
    assert cab["Authorization"] == "Bearer T1"


def test_401_renova_token_e_repete(monkeypatch):
    t, http = _transporte(monkeypatch)
    http.get_401 = 1
    http.get_docs = {"documents": [_DOC_MED]}
    meds = t.ler_medicamentos()
    assert meds != []
    renovados = [c for c in http.chamadas if c[0] == "post" and "securetoken" in c[1]]
    assert renovados
    seg_gets = [c for c in http.chamadas if c[0] == "get"]
    assert seg_gets[-1][2]["Authorization"] == "Bearer T2"


def test_sem_rede_vira_erro_transporte(monkeypatch):
    t, http = _transporte(monkeypatch)
    http.get_offline = True
    with pytest.raises(ErroTransporte):
        t.ler_medicamentos()


def test_conexao_fora_do_ar_nos_escritos(monkeypatch):
    t, http = _transporte(monkeypatch)
    http.patch_offline = True
    with pytest.raises(ErroTransporte):
        t.gravar_historico("o1", {"nome": "X"})


def test_403_na_leitura_e_acesso_negado(monkeypatch):
    t, http = _transporte(monkeypatch)
    http.get_status = 403
    with pytest.raises(AutenticacaoFalhou):
        t.ler_medicamentos()


def test_escrita_idempotente_grava_no_doc_deterministico(monkeypatch):
    t, http = _transporte(monkeypatch)
    registro = {"nome": "Paracetamol", "dia": "19/09/2026"}
    assert t.gravar_historico("o1", registro) is True
    patch = [c for c in http.chamadas if c[0] == "patch"][0]
    assert doc_historico_id("o1") in patch[1]
    assert patch[2]["Authorization"] == "Bearer T1"
    assert patch[3]["fields"]["dia"]["stringValue"] == "19/09/2026"


def test_fake_offline_e_reescrita_sobrescreve():
    fake = TransporteFake(medicamentos=[{"id": "m", "nome": "A", "dosagem": "", "dias": []}])
    assert fake.ler_medicamentos() != []
    assert fake.gravar_historico("o1", {"nome": "A"}) is True
    assert fake.gravar_historico("o1", {"nome": "A2"}) is True
    cadeia = doc_historico_id("o1")
    assert fake.historico[cadeia]["nome"] == "A2"
    fake.offline = True
    with pytest.raises(ErroTransporte):
        fake.ler_medicamentos()
    with pytest.raises(ErroTransporte):
        fake.gravar_historico("o2", {"nome": "B"})