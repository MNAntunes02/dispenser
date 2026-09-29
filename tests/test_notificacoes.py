"""Fase 6: avisos ao cuidador/app (ADR 010).

Cobre o caminho completo — máquina de estados -> `Notificador` -> fila outbox
-> `Sincronizador` -> `Notificacoes` do Firestore — com o transporte em memória
(sem rede) e com a ponte simulada no lugar do hardware.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import requests

from core.agendador import Ocorrencia, abrev_dia_semana
from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador, PublicadorLog
from core.notificador import Notificador
from core.sync import Sincronizador, SyncService
from core.textos import AVISOS_CUIDADOR, aviso_cuidador
from core.transporte import (
    MOTIVO_AVISO,
    ErroTransporte,
    TransporteFake,
    TransporteFirestore,
    doc_notificacao_id,
    motivo_aviso,
    registro_notificacao,
)
from hardware.bridge.bridge_simulada import PonteSimulada

DIA = datetime(2026, 9, 19, 8, 0, 0)  # sábado
OCC = f"med0|{DIA.date().isoformat()}|08:00"


def _ocorrencia(ocorrencia_id: str = OCC) -> Ocorrencia:
    return Ocorrencia(
        id=ocorrencia_id,
        medicamento="med0",
        medicamento_nome="Losartana",
        dosagem="50mg",
        slot=1,
        dia=DIA.date().isoformat(),
        horario="08:00",
    )


class RelogioFake:
    def __init__(self, inicio: datetime) -> None:
        self._agora = inicio

    def agora(self) -> datetime:
        return self._agora

    def avancar(self, **kw) -> None:
        self._agora += timedelta(**kw)


def _notificador(db, relogio=None) -> Notificador:
    return Notificador(db, SyncService(db), (relogio or RelogioFake(DIA)).agora)


def _montar(tmp_path, config=None, relogio=None):
    fake = relogio or RelogioFake(DIA)
    db = Database(tmp_path / "s.db", relogio=fake.agora)
    db.conectar()
    ponte = PonteSimulada()
    coord = Coordenador(
        config or Config(),
        db,
        AgendaMemo(
            [
                {
                    "id": "med0",
                    "nome": "Losartana",
                    "dosagem": "50mg",
                    "dias": [
                        {
                            "dia_semana": abrev_dia_semana(DIA.date()),
                            "horario": ["08:00"],
                        }
                    ],
                }
            ]
        ),
        ponte,
        publicador_ui=PublicadorLog(),
        relogio=fake.agora,
    )
    coord.conectar()
    return coord, db, ponte, fake


# --- mapeamento do documento de aviso ---------------------------------------


def test_motivo_do_tipo_de_evento():
    assert motivo_aviso("dose_perdida") == "dose_perdida"
    assert motivo_aviso("retorno_pendente") == "nao_devolvido"
    assert motivo_aviso("falha") == "falha"
    assert motivo_aviso("dose_concluida") is None


def test_doc_notificacao_id_deterministico():
    a = doc_notificacao_id(OCC, "dose_perdida")
    assert a == doc_notificacao_id(OCC, "dose_perdida")
    assert a.startswith("n")
    assert a != doc_notificacao_id(OCC, "falha")
    assert a != doc_notificacao_id("med1|2026-09-19|08:00", "dose_perdida")


def test_aviso_de_dose_perdida_com_dados_da_ocorrencia():
    aviso = registro_notificacao(
        {"dia": "2026-09-19", "horario": "08:00", "medicamento_nome": "Losartana",
         "dosagem": "50mg"},
        {"tipo": "dose_perdida", "horario_real": "2026-09-19T08:12:00"},
    )
    assert aviso == {
        "motivo": "dose_perdida",
        "em": "2026-09-19T08:12:00",
        "horario_real": "08:12",
        "dia": "19/09/2026",
        "horario_previsto": "08:00",
        "nome": "Losartana",
        "mensagem": "Dose não tomada: Losartana (50mg), prevista para 08:00.",
    }


def test_aviso_de_nao_devolvido():
    aviso = registro_notificacao(
        {"dia": "2026-09-19", "horario": "08:00", "medicamento_nome": "Losartana",
         "dosagem": "50mg"},
        {"tipo": "retorno_pendente", "horario_real": "2026-09-19T08:40:00"},
    )
    assert aviso["motivo"] == "nao_devolvido"
    assert aviso["mensagem"] == (
        "Medicamento não devolvido ao slot: Losartana (50mg), dose das 08:00."
    )


def test_falha_sem_dose_avisou_com_dia_e_codigo():
    aviso = registro_notificacao(
        None,
        {"tipo": "falha", "codigo": "F003", "dia": "2026-09-19",
         "horario_real": "2026-09-19T09:00:00"},
    )
    assert aviso == {
        "motivo": "falha",
        "em": "2026-09-19T09:00:00",
        "horario_real": "09:00",
        "dia": "19/09/2026",
        "codigo": "F003",
        "mensagem": (
            "Falha F003 no sensor do dispensador. Confira a dose manualmente."
        ),
    }


def test_aviso_invalido_nao_e_montado():
    occ = {"dia": "2026-09-19", "horario": "08:00", "medicamento_nome": "X",
           "dosagem": "1"}
    assert registro_notificacao(occ, {"tipo": "dose_concluida"}) is None
    assert registro_notificacao(occ, {}) is None
    # dose perdida/sem ocorrência não é aviso: não pode afirmar nada
    assert registro_notificacao(None, {"tipo": "dose_perdida"}) is None
    assert registro_notificacao(None, {"tipo": "retorno_pendente"}) is None


# --- textos (regra 9 do AGENTS.md) ------------------------------------------


def test_todos_os_motivos_tem_frase_pt_br():
    assert set(AVISOS_CUIDADOR) == set(MOTIVO_AVISO.values())
    assert aviso_cuidador("falha", codigo="F001") == (
        "Falha F001 no sensor do dispensador. Confira a dose manualmente."
    )
    with pytest.raises(KeyError):
        aviso_cuidador("motivo_desconhecido", nome="X", dosagem="1", horario="08:00")


# --- notificador: um aviso por ocorrência, log sem nome (LGPD) --------------


def test_notificador_enfileira_um_aviso_por_motivo(db):
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    notificador = _notificador(db)

    notificador.notificar_dose_perdida(OCC)
    notificador.notificar_dose_perdida(OCC)  # repetido (reinício/retry)
    notificador.notificar_retorno_pendente(OCC)

    pendentes = db.outbox_pendentes()
    assert [p["tipo"] for p in pendentes] == ["dose_perdida", "retorno_pendente"]
    assert pendentes[0]["payload"] and "Losartana" not in pendentes[0]["payload"]

    logs = [l["tipo"] for l in db.ultimos_logs()]
    assert "notificar_dose_perdida" in logs
    assert "notificar_retorno_pendente" in logs


def test_log_local_nao_tem_nome_de_medicamento(db):
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    _notificador(db).notificar_dose_perdida(OCC)
    _notificador(db).notificar_falha("F003", OCC)
    for log in db.ultimos_logs():
        assert "Losartana" not in (log["tipo"] + log["detalhe"])


def test_falha_sem_dose_usa_chave_com_dia_e_nao_colide_entre_dias(db):
    notificador = _notificador(db)
    notificador.notificar_falha("F003")
    notificador.notificar_falha("F003")  # mesmo dia: não duplica
    notificador.notificar_falha("F004")  # outro código: aviso próprio

    pendentes = db.outbox_pendentes()
    assert len(pendentes) == 2
    assert {p["chave"] for p in pendentes} == {
        "sem_dose|falha|F003|2026-09-19",
        "sem_dose|falha|F004|2026-09-19",
    }

    dia_seguinte = RelogioFake(DIA + timedelta(days=1))
    Notificador(db, SyncService(db), dia_seguinte.agora).notificar_falha("F003")
    assert len(db.outbox_pendentes()) == 3


def test_falha_com_ocorrencia_compartilha_a_chave_do_evento(db):
    """A ação `registrar` da máquina e a ação `notificar` não podem gerar dois itens."""
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    sync = SyncService(db)
    sync.enfileirar_evento(OCC, "falha", {"codigo": "F003"})
    _notificador(db, None).notificar_falha("F003", OCC)
    assert [p["tipo"] for p in db.outbox_pendentes()] == ["falha"]


# --- entrega: fila -> Notificacoes ------------------------------------------


def _avisos(fake: TransporteFake) -> list[dict]:
    return list(fake.notificacoes.values())


def test_ciclo_publica_o_aviso_de_dose_perdida(db):
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    _notificador(db).notificar_dose_perdida(OCC)

    fake = TransporteFake([])
    resumo = Sincronizador(db, fake).ciclo()
    assert resumo["enviados"] == 1
    assert db.outbox_pendentes() == []
    aviso = _avisos(fake)[0]
    assert aviso["motivo"] == "dose_perdida"
    assert aviso["nome"] == "Losartana"
    assert aviso["dia"] == "19/09/2026"


def test_offline_mantem_o_aviso_pendente_e_entrega_uma_vez(db):
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    _notificador(db).notificar_retorno_pendente(OCC)
    fake = TransporteFake([])

    fake.offline = True
    assert Sincronizador(db, fake).ciclo()["enviados"] == 0
    assert [p["tipo"] for p in db.outbox_pendentes()] == ["retorno_pendente"]

    fake.offline = False
    assert Sincronizador(db, fake).ciclo()["enviados"] == 1
    assert db.outbox_pendentes() == []

    assert Sincronizador(db, fake).ciclo()["enviados"] == 0
    assert len(fake.notificacoes) == 1  # reenvio não duplica doc


def test_dose_perdida_nao_entra_no_historico_do_app(db):
    """`Historico` é adesão positiva: dose perdida vira só aviso."""
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    _notificador(db).notificar_dose_perdida(OCC)
    fake = TransporteFake([])
    Sincronizador(db, fake).ciclo()
    assert fake.historico == {}
    assert _avisos(fake)[0]["motivo"] == "dose_perdida"


def test_reenvio_sobrescreve_o_mesmo_doc(db):
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    notificador = _notificador(db)
    notificador.notificar_dose_perdida(OCC)
    fake = TransporteFake([])
    Sincronizador(db, fake).ciclo()

    # segunda tentativa depois de "queda de energia": mesmo doc, sem duplicar
    db.enfileirar_outbox(f"{OCC}|dose_perdida", OCC, "dose_perdida", {})
    Sincronizador(db, fake).ciclo()
    assert len(fake.notificacoes) == 1


# --- integração com a máquina de estados ------------------------------------


def test_dose_perdida_no_fluxo_gera_um_aviso_com_mensagem(tmp_path):
    cfg = Config(max_tentativas=2, intervalo_alarme_s=60)
    coord, db, ponte, relogio = _montar(tmp_path, config=cfg)
    coord.tick()
    relogio.avancar(seconds=60)
    coord.tick()
    relogio.avancar(seconds=60)
    coord.tick()  # tentativas = N -> dose perdida

    assert [p["tipo"] for p in db.outbox_pendentes()] == ["dose_perdida"]

    fake = TransporteFake([])
    Sincronizador(db, fake).ciclo()
    aviso = _avisos(fake)[0]
    assert aviso["motivo"] == "dose_perdida"
    assert aviso["horario_previsto"] == "08:00"
    assert aviso["horario_real"] == "08:02"  # quando o alarme desistiu
    assert aviso["mensagem"] == (
        "Dose não tomada: Losartana (50mg), prevista para 08:00."
    )


def test_medicamento_nao_devolvido_gera_aviso_uma_vez(tmp_path):
    cfg = Config(timeout_retorno_s=60, limite_retorno_s=1800)
    coord, db, ponte, relogio = _montar(tmp_path, config=cfg)
    coord.tick()
    for evento in (
        {"e": "botao"},
        {"e": "gaveta_aberta"},
        {"e": "slot_ausente", "slot": 1},
        {"e": "botao"},
    ):
        ponte.simular(evento)
        coord.tick()

    relogio.avancar(seconds=60)
    coord.tick()  # retorno pendente
    assert db.ocorrencia_ativa()["estado"] == "RETORNO_PENDENTE"

    relogio.avancar(seconds=1800)
    coord.tick()  # limite excedido -> notifica
    coord.tick()  # tick seguinte: não notifica de novo

    tipos = [p["tipo"] for p in db.outbox_pendentes()]
    assert tipos == ["dose_tomada", "retorno_pendente"]  # a dose foi tomada...
    assert tipos.count("retorno_pendente") == 1  # ...e o aviso sai uma vez só

    fake = TransporteFake([])
    Sincronizador(db, fake).ciclo()
    aviso = _avisos(fake)[0]
    assert aviso["motivo"] == "nao_devolvido"
    assert "não devolvido" in aviso["mensagem"]
    assert fake.historico != {}  # a tomada vai para o Histórico


def test_falha_no_fluxo_avisa_com_codigo_e_nao_marca_dose_tomada(tmp_path):
    coord, db, ponte, relogio = _montar(tmp_path)
    coord.tick()
    ponte.simular({"e": "falha", "codigo": "F003"})
    coord.tick()

    tipos = [p["tipo"] for p in db.outbox_pendentes()]
    assert tipos == ["falha"]
    assert "dose_tomada" not in tipos

    fake = TransporteFake([])
    Sincronizador(db, fake).ciclo()
    aviso = _avisos(fake)[0]
    assert aviso["codigo"] == "F003"
    assert aviso["motivo"] == "falha"
    assert fake.historico == {}


def test_falha_com_ociosidade_avisa_mesmo_sem_dose(tmp_path):
    """Sensor falha com ociosidade: não há dose, mas o cuidador precisa saber."""
    relogio = RelogioFake(DIA - timedelta(minutes=30))
    coord, db, ponte, _ = _montar(tmp_path, relogio=relogio)
    coord.tick()
    assert db.ocorrencia_ativa() is None

    ponte.simular({"e": "falha", "codigo": "F001"})
    coord.tick()

    pendentes = db.outbox_pendentes()
    assert [p["tipo"] for p in pendentes] == ["falha"]
    assert pendentes[0]["ocorrencia_id"] == ""

    fake = TransporteFake([])
    Sincronizador(db, fake).ciclo()
    aviso = _avisos(fake)[0]
    assert aviso["motivo"] == "falha"
    assert aviso["dia"] == "19/09/2026"
    assert aviso["codigo"] == "F001"
    assert "nome" not in aviso  # sem dose não há medicamento para citar


def test_fluxo_feliz_nao_gera_aviso(tmp_path):
    coord, db, ponte, relogio = _montar(tmp_path)
    coord.tick()
    for evento in (
        {"e": "botao"},
        {"e": "gaveta_aberta"},
        {"e": "slot_ausente", "slot": 1},
        {"e": "botao"},
        {"e": "slot_presente", "slot": 1},
        {"e": "gaveta_fechada"},
    ):
        ponte.simular(evento)
        coord.tick()

    fake = TransporteFake([])
    Sincronizador(db, fake).ciclo()
    assert fake.notificacoes == {}
    assert fake.historico != {}  # a dose tomada segue no Histórico do app


# --- transporte real (REST) -------------------------------------------------


class _Resp:
    def __init__(self, status, dados=None):
        self.status_code = status
        self._dados = dados or {}

    def json(self):
        return self._dados


class _Http:
    def __init__(self):
        self.chamadas = []
        self.patch_status = 200
        self.patch_offline = False
        self.patch_401 = 0

    def post(self, url, params=None, json=None, timeout=None):
        self.chamadas.append(("post", url, json))
        return _Resp(200, {"idToken": "T1", "refreshToken": "R1", "expiresIn": "3600"})

    def patch(self, url, headers=None, json=None, timeout=None):
        self.chamadas.append(("patch", url, json))
        if self.patch_offline:
            raise requests.exceptions.ConnectionError("sem rede")
        if self.patch_401 > 0:
            self.patch_401 -= 1
            return _Resp(401)
        return _Resp(self.patch_status)


def _transporte_real(monkeypatch) -> tuple[TransporteFirestore, _Http]:
    http = _Http()
    monkeypatch.setattr("core.transporte.requests.post", http.post)
    monkeypatch.setattr("core.transporte.requests.patch", http.patch)
    transporte = TransporteFirestore(
        projeto="p", usuario_id="u", api_key="k", email="e@x", senha="s"
    )
    return transporte, http


def test_aviso_grava_na_subcolecao_notificacoes(monkeypatch):
    transporte, http = _transporte_real(monkeypatch)
    aviso = {"motivo": "dose_perdida", "mensagem": "Dose não tomada: X (1)."}
    assert transporte.gravar_notificacao(OCC, "dose_perdida", aviso) is True
    patch = [c for c in http.chamadas if c[0] == "patch"][0]
    assert "UsuarioMedicamento/u/Notificacoes/" in patch[1]
    assert doc_notificacao_id(OCC, "dose_perdida") in patch[1]
    assert patch[2]["fields"]["mensagem"]["stringValue"] == aviso["mensagem"]


def test_aviso_trata_401_negativo_e_rede(monkeypatch):
    transporte, http = _transporte_real(monkeypatch)
    http.patch_status = 403
    assert transporte.gravar_notificacao(OCC, "falha", {"motivo": "falha"}) is False
    antes = len([c for c in http.chamadas if c[0] == "patch"])

    http.patch_status = 200
    http.patch_401 = 1  # renova o token e repete o PATCH
    assert transporte.gravar_notificacao(OCC, "falha", {"motivo": "falha"}) is True
    assert len([c for c in http.chamadas if c[0] == "patch"]) == antes + 2

    http.patch_status = 500
    with pytest.raises(ErroTransporte):
        transporte.gravar_notificacao(OCC, "falha", {"motivo": "falha"})

    http.patch_offline = True
    with pytest.raises(ErroTransporte):
        transporte.gravar_notificacao(OCC, "falha", {"motivo": "falha"})


def test_fake_grava_aviso_e_respeita_offline():
    fake = TransporteFake([])
    assert fake.gravar_notificacao(OCC, "dose_perdida", {"motivo": "dose_perdida"})
    assert fake.gravar_notificacao(OCC, "dose_perdida", {"motivo": "dose_perdida"})
    assert len(fake.notificacoes) == 1
    fake.offline = True
    with pytest.raises(ErroTransporte):
        fake.gravar_notificacao(OCC, "falha", {"motivo": "falha"})
