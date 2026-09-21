"""Integração: fluxo completo via coordenador + ponte simulada + relógio fake."""

from datetime import datetime, timedelta

from core.agendador import abrev_dia_semana
from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador, PublicadorLog
from hardware.bridge.bridge_simulada import PonteSimulada

DIA = datetime(2026, 9, 19, 8, 0, 0)  # sábado


class RelogioFake:
    def __init__(self, inicio):
        self._agora = inicio

    def agora(self):
        return self._agora

    def avancar(self, **kw):
        self._agora += timedelta(**kw)


def _meds(horarios, prefixo="med"):
    return [
        {
            "id": f"{prefixo}{i}",
            "nome": f"Medicamento {i}",
            "dosagem": "10mg",
            "dias": [
                {
                    "dia_semana": abrev_dia_semana(DIA.date()),
                    "horario": [horarios[i]],
                }
            ],
        }
        for i in range(len(horarios))
    ]


def _montar(tmp_path, medicamentos, config=None, inicio=None, relogio=None):
    fake = relogio or RelogioFake(inicio or DIA)
    db = Database(tmp_path / "s.db", relogio=fake.agora)
    db.conectar()
    pub = PublicadorLog()
    ponte = PonteSimulada()
    coord = Coordenador(
        config or Config(),
        db,
        AgendaMemo(medicamentos),
        ponte,
        publicador_ui=pub,
        relogio=fake.agora,
    )
    coord.conectar()
    return coord, db, pub, ponte, fake


def _chaves(pub):
    return [m.get("chave") for m in pub.mensagens if m.get("chave")]


def _concluir(coord, ponte, pub):
    passos = (
        {"e": "botao"},
        {"e": "gaveta_aberta"},
        {"e": "slot_ausente", "slot": 0},
        {"e": "botao"},
        {"e": "slot_presente", "slot": 0},
        {"e": "gaveta_fechada"},
    )
    for evento in passos:
        ponte.simular(evento)
        coord.tick()
    return _chaves(pub)


def test_fluxo_feliz_completo_no_simulador(tmp_path):
    coord, db, pub, ponte, relogio = _montar(
        tmp_path, _meds(["08:00"]), inicio=DIA - timedelta(seconds=1)
    )
    coord.tick()  # antes do horário não dispara
    assert _chaves(pub) == []
    assert db.ocorrencia_ativa() is None

    relogio.avancar(seconds=1)
    coord.tick()
    chaves = _chaves(pub)
    assert "hora_remedio" in chaves
    assert db.ocorrencia_ativa() is not None

    _concluir(coord, ponte, pub)
    assert "tudo_certo" in _chaves(pub)
    assert db.ocorrencia_ativa() is None
    ocorr = db.proxima_ocorrencia_aguardando(dia=DIA.date().isoformat())
    assert ocorr is None
    ativa = db.obter_ocorrencia(f"med0|{DIA.date().isoformat()}|08:00")
    assert ativa["estado"] == "CONCLUIDA"
    pendentes = db.outbox_pendentes()
    assert [p["tipo"] for p in pendentes] == ["dose_tomada", "dose_concluida"]

    coord.tick()  # dose concluída não reabre
    assert _chaves(pub).count("hora_remedio") == 1


def test_dose_tomada_so_possivel_apos_sensor_e_ok(tmp_path):
    coord, db, pub, ponte, relogio = _montar(tmp_path, _meds(["08:00"]), inicio=DIA)
    coord.tick()
    assert db.outbox_pendentes() == []

    ponte.simular({"e": "botao"})  # OK sem alarme prévio? já está em ALARME
    coord.tick()
    assert "abra_gaveta" in _chaves(pub)

    ponte.simular({"e": "botao"})  # OK duplo, sem retirada
    coord.tick()
    assert db.outbox_pendentes() == []  # não registrou tomada

    ponte.simular({"e": "gaveta_aberta"})
    coord.tick()
    ponte.simular({"e": "botao"})  # OK sem tirar o remédio
    coord.tick()
    assert [p["tipo"] for p in db.outbox_pendentes()] == []  # tomada exige slot_ausente

    ponte.simular({"e": "slot_ausente", "slot": 0})
    coord.tick()
    assert "tome_e_ok" in _chaves(pub)
    ponte.simular({"e": "botao"})
    coord.tick()
    assert [p["tipo"] for p in db.outbox_pendentes()] == ["dose_tomada"]


def test_alarme_sem_resposta_ate_perdida(tmp_path):
    cfg = Config(max_tentativas=2, intervalo_alarme_s=60)
    coord, db, pub, ponte, relogio = _montar(
        tmp_path, _meds(["08:00"]), config=cfg, inicio=DIA
    )
    coord.tick()
    assert db.ocorrencia_ativa()["estado"] == "ALARME"
    assert db.obter_ocorrencia(f"med0|{DIA.date().isoformat()}|08:00")["tentativas"] == 0

    relogio.avancar(seconds=60)
    coord.tick()  # 1ª repetição
    ocorr = db.obter_ocorrencia(f"med0|{DIA.date().isoformat()}|08:00")
    assert ocorr["estado"] == "ALARME"
    assert ocorr["tentativas"] == 1

    relogio.avancar(seconds=60)
    coord.tick()  # tentativas = N -> perdida
    ocorr2 = db.obter_ocorrencia(f"med0|{DIA.date().isoformat()}|08:00")
    assert ocorr2["estado"] == "NAO_ATENDIDA"
    assert [p["tipo"] for p in db.outbox_pendentes()] == ["dose_perdida"]
    logs = [l["tipo"] for l in db.ultimos_logs()]
    assert "notificar_dose_perdida" in logs
    assert db.ocorrencia_ativa() is None

    coord.tick()  # não reabre
    assert db.obter_ocorrencia(f"med0|{DIA.date().isoformat()}|08:00")["estado"] == "NAO_ATENDIDA"


def test_retomada_apos_reinicio_no_meio_da_dose(tmp_path):
    coord, db, pub, ponte, relogio = _montar(tmp_path, _meds(["08:00"]), inicio=DIA)
    coord.tick()

    ponte.simular({"e": "botao"})
    coord.tick()
    ponte.simular({"e": "gaveta_aberta"})
    coord.tick()
    ponte.simular({"e": "slot_ausente", "slot": 0})
    coord.tick()
    assert db.ocorrencia_ativa()["estado"] == "MEDICAMENTO_RETIRADO"
    assert db.outbox_pendentes() == []

    # "queda de energia": novo processo sobre o mesmo banco e relógio
    coord.finalizar()
    coord2, db2, pub2, ponte2, _ = _montar(
        tmp_path,
        _meds(["08:00"]),
        inicio=DIA,
        relogio=relogio,
    )
    coord2.tick()
    assert db2.ocorrencia_ativa()["estado"] == "MEDICAMENTO_RETIRADO"
    assert db2.outbox_pendentes() == []  # sem duplicar eventos

    ponte2.simular({"e": "botao"})
    coord2.tick()
    assert [p["tipo"] for p in db2.outbox_pendentes()] == ["dose_tomada"]
    ponte2.simular({"e": "slot_presente", "slot": 0})
    ponte2.simular({"e": "gaveta_fechada"})
    coord2.tick()
    assert db2.obter_ocorrencia(f"med0|{DIA.date().isoformat()}|08:00")["estado"] == "CONCLUIDA"


def test_gaveta_aberta_fora_de_horario_sem_dose(tmp_path):
    coord, db, pub, ponte, relogio = _montar(
        tmp_path, _meds(["08:00"]), inicio=DIA - timedelta(minutes=30)
    )
    coord.tick()
    assert db.ocorrencia_ativa() is None

    ponte.simular({"e": "gaveta_aberta"})
    coord.tick()
    assert "gaveta_fora_de_horario" in _chaves(pub)
    assert [p["tipo"] for p in db.outbox_pendentes()] == ["gaveta_fora_de_horario"]
    ocorr = db.proxima_ocorrencia_aguardando(dia=DIA.date().isoformat())
    assert ocorr["estado"] == "AGUARDANDO"

    relogio.avancar(minutes=30)
    coord.tick()  # horário chegou mesmo com a gaveta aberta
    assert db.ocorrencia_ativa()["estado"] == "ALARME"


def test_doses_simultaneas_em_fila_uma_por_vez(tmp_path):
    coord, db, pub, ponte, relogio = _montar(tmp_path, _meds(["08:00", "08:00"]))
    coord.tick()
    ativa_1 = db.ocorrencia_ativa()
    assert ativa_1["medicamento"] == "med0"

    _concluir(coord, ponte, pub)
    coord.tick()  # libera a próxima da fila
    ativa_2 = db.ocorrencia_ativa()
    assert ativa_2 is not None
    assert ativa_2["medicamento"] == "med1"
    assert db.obter_ocorrencia(ativa_1["id"])["estado"] == "CONCLUIDA"

    _concluir(coord, ponte, pub)
    coord.tick()
    assert db.ocorrencia_ativa() is None
    assert db.obter_ocorrencia(ativa_2["id"])["estado"] == "CONCLUIDA"


def test_falha_de_sensor_no_meio_do_fluxo(tmp_path):
    coord, db, pub, ponte, relogio = _montar(tmp_path, _meds(["08:00"]), inicio=DIA)
    coord.tick()
    ponte.simular({"e": "gaveta_aberta"})
    coord.tick()

    ponte.simular({"e": "falha", "codigo": "F003"})
    coord.tick()
    assert "falha" in _chaves(pub)
    ativa = db.ocorrencia_ativa()
    assert ativa["estado"] == "FALHA"
    assert [p["tipo"] for p in db.outbox_pendentes()] == ["falha"]
    assert not any(p["tipo"] == "dose_tomada" for p in db.outbox_pendentes())

    coord.tick()  # FALHA permanece bloqueada
    assert db.ocorrencia_ativa()["estado"] == "FALHA"


def test_medicamento_nao_devolvido_avisa_ate_limite(tmp_path):
    cfg = Config(timeout_retorno_s=60, limite_retorno_s=1800)
    coord, db, pub, ponte, relogio = _montar(
        tmp_path, _meds(["08:00"]), config=cfg, inicio=DIA
    )
    coord.tick()
    _concluir_ate_tomada(coord, ponte, pub)

    relogio.avancar(seconds=60)
    coord.tick()  # timeout do retorno -> pendente
    ativa = db.ocorrencia_ativa()
    assert ativa["estado"] == "RETORNO_PENDENTE"
    assert "aviso_retorno" in _chaves(pub)

    relogio.avancar(seconds=1800)
    coord.tick()  # limite excedido -> notifica "não devolvido"
    logs = [l["tipo"] for l in db.ultimos_logs()]
    assert "notificar_retorno_pendente" in logs
    assert db.obter_ocorrencia(ativa["id"])["notificado"] == 1

    coord.tick()  # após o limite, não notifica de novo
    assert [l["tipo"] for l in db.ultimos_logs()].count("notificar_retorno_pendente") == 1

    ponte.simular({"e": "slot_presente", "slot": 0})
    ponte.simular({"e": "gaveta_fechada"})
    coord.tick()
    assert db.obter_ocorrencia(ativa["id"])["estado"] == "CONCLUIDA"


def _concluir_ate_tomada(coord, ponte, pub):
    for evento in ({"e": "botao"}, {"e": "gaveta_aberta"}, {"e": "slot_ausente", "slot": 0}, {"e": "botao"}):
        ponte.simular(evento)
        coord.tick()