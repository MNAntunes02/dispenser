"""Testes do armazenamento: schema, ocorrências, outbox e trilha."""

from datetime import datetime

from core.agendador import Ocorrencia
from core.armazenamento import Database


def _occ(dia="2026-09-19", horario="08:00", med="med1"):
    return Ocorrencia(
        id=f"{med}|{dia}|{horario}",
        medicamento=med,
        medicamento_nome="Losartana",
        dosagem="50mg",
        slot=None,
        dia=dia,
        horario=horario,
    )


def _tabelas(db):
    linhas = db.conexao.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {l["name"] for l in linhas}


def test_schema_criado_no_conectar(db):
    assert {"ocorrencias", "outbox", "log_eventos"} <= _tabelas(db)


def test_inserir_ocorrencia_se_nova_inicia_aguardando(db):
    db.inserir_ocorrencia_se_nova(_occ())
    db.inserir_ocorrencia_se_nova(_occ())  # não duplica nem reseta estado
    ocorr = db.obter_ocorrencia("med1|2026-09-19|08:00")
    assert ocorr["estado"] == "AGUARDANDO"
    assert ocorr["tentativas"] == 0
    assert db.contar_outbox_pendentes() == 0
    assert len(db.proximas_ocorrencias_aguardando("2026-09-19")) == 1


def test_atualizar_ocorrencia_mantem_campos(db):
    db.inserir_ocorrencia_se_nova(_occ())
    db.atualizar_ocorrencia("med1|2026-09-19|08:00", estado="ALARME", tentativas=2)
    ocorr = db.obter_ocorrencia("med1|2026-09-19|08:00")
    assert ocorr["estado"] == "ALARME"
    assert ocorr["tentativas"] == 2
    assert ocorr["atualizado_em"] is not None


def test_ocorrencia_ativa_filtra_estados(db):
    ativa = _occ(horario="08:00")
    terminada = _occ(horario="20:00")
    db.inserir_ocorrencia_se_nova(ativa)
    db.inserir_ocorrencia_se_nova(terminada)
    db.atualizar_ocorrencia(ativa.id, estado="MEDICAMENTO_RETIRADO")
    db.atualizar_ocorrencia(terminada.id, estado="CONCLUIDA")
    assert db.ocorrencia_ativa()["id"] == ativa.id


def test_proxima_aguardando_ordenada_e_filtra_dia(db):
    db.inserir_ocorrencia_se_nova(_occ(horario="20:00"))
    db.inserir_ocorrencia_se_nova(_occ(horario="08:00"))
    db.inserir_ocorrencia_se_nova(_occ(dia="2026-09-20", horario="07:00"))
    prox = db.proxima_ocorrencia_aguardando()
    assert prox["horario"] == "07:00"  # de outro dia, sem filtro
    prox_hoje = db.proxima_ocorrencia_aguardando(dia="2026-09-19")
    assert prox_hoje["horario"] == "08:00"


def test_outbox_chave_unica_e_status(db):
    db.enfileirar_outbox("m|tomada", "m", "dose_tomada", {"a": 1})
    db.enfileirar_outbox("m|tomada", "m", "dose_tomada", {"a": 2})  # ignorado
    db.enfileirar_outbox("m|perdida", "m", "dose_perdida", {})
    pendentes = db.outbox_pendentes()
    assert len(pendentes) == 2
    db.marcar_outbox_enviado(pendentes[0]["id"])
    assert db.contar_outbox_pendentes() == 1


def test_trilha_de_eventos(db):
    db.registrar_log("evento:horario_chegou", "med1|2026-09-19|08:00")
    db.registrar_log("evento:gaveta_aberta")  # sem ocorrência: fora de hora
    ultimos = db.ultimos_logs()
    assert [g["tipo"] for g in ultimos] == [
        "evento:gaveta_aberta",
        "evento:horario_chegou",
    ]


def test_relogio_injetado_controla_timestamps(tmp_path):
    atual = {"v": datetime(2026, 9, 19, 8, 0, 0)}
    banco = Database(tmp_path / "t.db", relogio=lambda: atual["v"])
    banco.conectar()
    banco.inserir_ocorrencia_se_nova(_occ())
    banco.atualizar_ocorrencia("med1|2026-09-19|08:00", estado="ALARME")
    assert banco.obter_ocorrencia("med1|2026-09-19|08:00")["atualizado_em"] == "2026-09-19T08:00:00"
    banco.fechar()
    atual["v"] = datetime(2026, 9, 19, 8, 2, 0)
    banco2 = Database(tmp_path / "t.db", relogio=lambda: atual["v"])
    banco2.conectar()
    assert banco2.obter_ocorrencia("med1|2026-09-19|08:00")["estado"] == "ALARME"
    banco2.atualizar_ocorrencia("med1|2026-09-19|08:00", tentativas=1)
    assert banco2.obter_ocorrencia("med1|2026-09-19|08:00")["tentativas"] == 1
    banco2.fechar()