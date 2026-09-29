"""Integração do ciclo de sync com TransporteFake: agenda em cache + fila."""

from core.agendador import Ocorrencia
from core.sync import FonteAgendaLocal, Sincronizador, SyncService
from core.transporte import (
    TransporteFake,
    doc_historico_id,
    doc_notificacao_id,
)

MEDS = [
    {
        "id": "med1",
        "nome": "Paracetamol",
        "dosagem": "500",
        "dias": [{"dia_semana": "sáb", "horario": ["08:00"]}],
    }
]


def _ocorrencia(ocorrencia_id="med1|2026-09-19|08:00"):
    return Ocorrencia(
        id=ocorrencia_id,
        medicamento="med1",
        medicamento_nome="Paracetamol",
        dosagem="500",
        slot=None,
        dia="2026-09-19",
        horario="08:00",
    )


def test_substituir_e_ler_agenda_em_cache(db):
    db.substituir_agenda(MEDS)
    assert db.agenda_cached() == MEDS
    db.substituir_agenda([])
    assert db.agenda_cached() == []


def test_ciclo_atualiza_agenda_pela_fonte_local(db):
    fake = TransporteFake(MEDS)
    sinc = Sincronizador(db, fake)
    resumo = sinc.ciclo()
    assert resumo["agenda"] is True
    assert FonteAgendaLocal(db).agenda() == MEDS


def test_historico_so_com_dose_tomada_e_aviso_com_dose_perdida(db):
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    sync = SyncService(db)
    sync.enfileirar_evento(
        "med1|2026-09-19|08:00", "dose_tomada", {"horario_real": "2026-09-19T08:05:00"}
    )
    sync.enfileirar_evento("med1|2026-09-19|08:00", "dose_concluida", {})
    sync.enfileirar_evento("med1|2026-09-19|08:00", "dose_perdida", {})

    fake = TransporteFake(MEDS)
    resumo = Sincronizador(db, fake).ciclo()
    assert resumo["enviados"] == 2  # tomada (Histórico) + perdida (aviso)

    cadeia = doc_historico_id("med1|2026-09-19|08:00")
    assert fake.historico[cadeia] == {
        "dia": "19/09/2026",
        "horario_previsto": "08:00",
        "horario_real": "08:05",
        "nome": "Paracetamol",
    }
    # dose perdida vira aviso; dose concluída ainda não tem destino no app
    aviso = fake.notificacoes[doc_notificacao_id("med1|2026-09-19|08:00", "dose_perdida")]
    assert aviso["motivo"] == "dose_perdida"
    assert [p["tipo"] for p in db.outbox_pendentes()] == ["dose_concluida"]


def test_sem_horario_real_payload_fica_na_fila(db):
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    SyncService(db).enfileirar_evento(
        "med1|2026-09-19|08:00", "dose_tomada", {}
    )
    fake = TransporteFake(MEDS)
    resumo = Sincronizador(db, fake).ciclo()
    assert resumo["enviados"] == 0
    assert fake.historico == {}
    assert db.outbox_pendentes() != []


def test_offline_mantem_pendente_e_online_entrega_uma_vez(db):
    db.inserir_ocorrencia_se_nova(_ocorrencia())
    sync = SyncService(db)
    sync.enfileirar_evento(
        "med1|2026-09-19|08:00", "dose_tomada", {"horario_real": "2026-09-19T08:05:00"}
    )
    fake = TransporteFake(MEDS)

    fake.offline = True
    resumo = Sincronizador(db, fake).ciclo()
    assert resumo["agenda"] is False
    assert resumo["enviados"] == 0
    assert db.outbox_pendentes() != []
    assert fake.historico == {}

    fake.offline = False
    resumo2 = Sincronizador(db, fake).ciclo()
    assert resumo2["agenda"] is True
    assert resumo2["enviados"] == 1
    assert db.outbox_pendentes() == []
    assert len(fake.historico) == 1

    resumo3 = Sincronizador(db, fake).ciclo()
    assert resumo3["enviados"] == 0  # já marcado; não reenvia
    assert len(fake.historico) == 1  # sem duplicar docs


def test_ocorrencia_desconhecida_nao_envia_e_permanece(db):
    SyncService(db).enfileirar_evento(
        "idnaoexiste", "dose_tomada", {"horario_real": "2026-09-19T08:05:00"}
    )
    fake = TransporteFake(MEDS)
    resumo = Sincronizador(db, fake).ciclo()
    assert resumo["enviados"] == 0
    assert fake.historico == {}
    assert db.outbox_pendentes() != []


def test_cache_vazio_offline_nao_fornece_agenda(db):
    fake = TransporteFake([])
    Sincronizador(db, fake).ciclo()
    assert FonteAgendaLocal(db).agenda() == []