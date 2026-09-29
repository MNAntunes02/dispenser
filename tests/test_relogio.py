"""Relógio não confiável (Fase 7, ADR 012).

O Pi não tem RTC: sem NTP e sem rede a hora pode vir em 1970 ou pular para
frente quando sincroniza. Estes testes travam a política aprovada: **não
dispara** por horário não confiável, avisa na tela, retoma quando a hora volta
e avisa o cuidador **uma vez** por indisponibilidade.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from core.agendador import abrev_dia_semana
from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador, PublicadorLog
from core.relogio import (
    DATA_MINIMA_PADRAO,
    FUSO_PADRAO,
    EstadoRelogio,
    FusoInvalido,
    VerificadorRelogio,
    aplicar_fuso,
    aplicar_fuso_com_padrao,
    chave_tela,
    fuso_existe,
    ler_data_minima,
)
from core.textos import plural_doses, texto
from core.transporte import registro_notificacao
from hardware.bridge.bridge_simulada import PonteSimulada

DIA = datetime(2026, 9, 19, 8, 0, 0)  # sábado
EPOCH = datetime(1970, 1, 1, 0, 0, 0)


class RelogioFake:
    def __init__(self, inicio):
        self._agora = inicio
        self.mono = 0.0

    def agora(self):
        return self._agora

    def marcar(self, momento: datetime) -> None:
        self._agora = momento

    def avancar(self, **kw) -> None:
        self._agora += timedelta(**kw)
        self.mono += kw.get("seconds", 0) + kw.get("minutes", 0) * 60 + kw.get("hours", 0) * 3600

    def mono_agora(self) -> float:
        return self.mono


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


class PonteSpy(PonteSimulada):
    """Ponte simulada que guarda buzzer/LED (o core manda parar o alarme)."""

    def __init__(self) -> None:
        super().__init__()
        self.buzzer_recebido: list[str] = []
        self.led_recebido: list[tuple[int, str]] = []

    def buzzer(self, padrao: str) -> None:
        self.buzzer_recebido.append(padrao)

    def acender_led(self, slot: int, estado: str) -> None:
        self.led_recebido.append((slot, estado))

    @property
    def ultimo_buzzer(self) -> str | None:
        return self.buzzer_recebido[-1] if self.buzzer_recebido else None


def _montar(tmp_path, medicamentos, relogio, config=None):
    db = Database(tmp_path / "s.db", relogio=relogio.agora)
    db.conectar()
    pub = PublicadorLog()
    ponte = PonteSpy()
    coord = Coordenador(
        config or Config(),
        db,
        AgendaMemo(medicamentos),
        ponte,
        publicador_ui=pub,
        relogio=relogio.agora,
    )
    coord.conectar()
    return coord, db, pub, ponte


def _chaves(pub):
    return [m.get("chave") for m in pub.mensagens if m.get("chave")]


# --- verificador puro -------------------------------------------------------


def test_relogio_valido_e_confiavel():
    v = VerificadorRelogio(lambda: DIA)
    avaliacao = v.avaliar()
    assert avaliacao.estado is EstadoRelogio.CONFIVEL
    assert avaliacao.confiavel
    assert v.confiavel


def test_relogio_em_1970_e_invalido():
    v = VerificadorRelogio(lambda: EPOCH)
    avaliacao = v.avaliar()
    assert avaliacao.estado is EstadoRelogio.INVALIDO
    assert avaliacao.motivo == "abaixo_do_piso"
    assert chave_tela(avaliacao.estado) == "relogio_nao_confiavel"


def test_salto_de_relogio_com_referencia_monotonica_e_instavel():
    rel = RelogioFake(DIA)
    v = VerificadorRelogio(rel.agora, relogio_mono=rel.mono_agora)
    v.avaliar()  # base confiável
    rel.avancar(minutes=30)  # 30 min de tempo real...
    rel.marcar(DIA + timedelta(hours=3))  # ...e a hora pulou 2h30
    avaliacao = v.avaliar()
    assert avaliacao.estado is EstadoRelogio.INSTAVEL
    assert avaliacao.motivo == "para_frente"
    assert chave_tela(avaliacao.estado) == "relogio_instavel"


def test_relogio_que_volta_para_tras_e_instavel():
    rel = RelogioFake(DIA)
    v = VerificadorRelogio(rel.agora, relogio_mono=rel.mono_agora)
    v.avaliar()
    rel.avancar(minutes=1)
    rel.marcar(DIA - timedelta(hours=2))
    assert v.avaliar().estado is EstadoRelogio.INSTAVEL


def test_correcao_pequena_de_ntp_continua_confiavel():
    rel = RelogioFake(DIA)
    v = VerificadorRelogio(rel.agora, relogio_mono=rel.mono_agora, tolerancia_s=300)
    v.avaliar()
    rel.avancar(minutes=1)
    rel.marcar(DIA + timedelta(minutes=1, seconds=2))  # NTP corrigiu 2 s
    assert v.avaliar().estado is EstadoRelogio.CONFIVEL


def test_sem_referencia_monotonica_o_piso_e_o_unico_limite():
    """Em teste/demo o relógio é falso e pula minutos: isso é tempo passando."""
    rel = RelogioFake(DIA)
    v = VerificadorRelogio(rel.agora)  # sem `relogio_mono`
    v.avaliar()
    rel.marcar(DIA + timedelta(hours=5))
    assert v.avaliar().estado is EstadoRelogio.CONFIVEL


def test_recuperacao_de_1970_avisa_data_de_baixo():
    rel = RelogioFake(EPOCH)
    v = VerificadorRelogio(rel.agora)
    assert v.avaliar().estado is EstadoRelogio.INVALIDO
    rel.marcar(DIA)
    recuperacao = v.avaliar()
    assert recuperacao.estado is EstadoRelogio.CONFIVEL
    assert recuperacao.recuperado is True
    assert recuperacao.inicio is None  # começou em 1970: janela não datável
    assert recuperacao.durou_s == 0.0


def test_recuperacao_datada_informa_o_incipio():
    rel = RelogioFake(datetime(2026, 9, 19, 6, 0))
    v = VerificadorRelogio(rel.agora, relogio_mono=rel.mono_agora)
    v.avaliar()  # base
    rel.avancar(hours=1)
    rel.marcar(datetime(2026, 9, 19, 6, 10))  # pulou 10 min -> instavel
    assert v.avaliar().estado is EstadoRelogio.INSTAVEL
    rel.avancar(seconds=5)
    rel.marcar(datetime(2026, 9, 19, 7, 10))  # corrigido: nova base
    recuperacao = v.avaliar()
    assert recuperacao.recuperado is True
    assert recuperacao.inicio == datetime(2026, 9, 19, 6, 10)
    assert recuperacao.durou_s == 3600.0


# --- fuso -------------------------------------------------------------------


def test_fuso_padrao_e_aplicado_no_processo():
    assert aplicar_fuso(FUSO_PADRAO) == FUSO_PADRAO
    assert fuso_existe(FUSO_PADRAO)
    # `datetime.now()` passa a ser interpretado no fuso do paciente.
    assert datetime.now().astimezone().tzinfo is not None


def test_fuso_inexistente_cai_no_padrao_com_aviso():
    aplicado, ok = aplicar_fuso_com_padrao("Mars/Phobos")
    assert aplicado == FUSO_PADRAO
    assert ok is False


def test_fuso_vazio_usa_padrao():
    assert aplicar_fuso_com_padrao(None) == (FUSO_PADRAO, True)
    assert aplicar_fuso_com_padrao("  ") == (FUSO_PADRAO, True)


def test_fuso_invalido_levanta_erro_explicito():
    try:
        aplicar_fuso("Nao/Existe")
    except FusoInvalido as erro:
        assert "Nao/Existe" in str(erro)
    else:  # pragma: no cover
        raise AssertionError("deveria recusar fuso inexistente")


def test_config_le_fuso_e_piso_do_ambiente(monkeypatch):
    monkeypatch.setenv("DISPENSER_TZ", "America/Manaus")
    monkeypatch.setenv("DISPENSER_DATA_MINIMA", "2025-01-01")
    monkeypatch.setenv("DISPENSER_JANELA_ATRASO_S", "600")
    config = Config.de_env()
    assert config.fuso == "America/Manaus"
    assert ler_data_minima(config.data_minima) == datetime(2025, 1, 1)
    assert config.janela_atraso_s == 600


def test_data_minima_invalida_usa_o_padrao():
    assert ler_data_minima("19/09/2026") == DATA_MINIMA_PADRAO
    assert ler_data_minima("") == DATA_MINIMA_PADRAO
    assert ler_data_minima(None) == DATA_MINIMA_PADRAO


# --- política no coordenador ------------------------------------------------


def test_relogio_invalido_nao_dispara_e_avisa_na_tela(tmp_path):
    rel = RelogioFake(EPOCH)
    coord, db, pub, _ponte = _montar(tmp_path, _meds(["08:00"]), rel)
    coord.tick()

    assert _chaves(pub) == ["relogio_nao_confiavel"]
    assert db.ocorrencias_do_dia("1970-01-01") == []  # nem agenda o dia de 1970
    assert db.ocorrencia_ativa() is None
    tela = pub.mensagens[-1]
    assert tela["fluxo"] == "alerta"
    assert tela["mensagem"] == texto("relogio_nao_confiavel")
    assert [log["tipo"] for log in db.ultimos_logs()] == ["relogio_invalido"]


def test_relatorio_repetido_nao_repinta_nem_escreve(tmp_path):
    rel = RelogioFake(EPOCH)
    coord, db, pub, _ponte = _montar(tmp_path, _meds(["08:00"]), rel)
    coord.tick()
    rel.avancar(seconds=5)
    coord.tick()
    rel.avancar(seconds=5)
    coord.tick()
    assert _chaves(pub).count("relogio_nao_confiavel") == 1
    assert [log["tipo"] for log in db.ultimos_logs()].count("relogio_invalido") == 1


def test_salvar_para_tela_de_relogio_quando_a_hora_pula(tmp_path):
    rel = RelogioFake(DIA)
    v = VerificadorRelogio(rel.agora, relogio_mono=rel.mono_agora)
    coord, db, pub, _ponte = _montar(tmp_path, _meds(["08:00"]), rel)
    coord._verificador = v  # palavra-chave Privada: injeção de teste
    coord.tick()
    assert db.ocorrencia_ativa()["estado"] == "ALARME"

    rel.avancar(minutes=1)
    rel.marcar(DIA + timedelta(hours=4))  # a hora pulou 4 h
    coord.tick()
    assert _chaves(pub)[-1] == "relogio_instavel"
    assert "relogio_instavel" in [log["tipo"] for log in db.ultimos_logs()]


def test_dose_parada_por_relogio_nao_estra_a_silencio(tmp_path):
    """Alarme tocando às cegas é pior que silêncio: o buzzer é desligado."""
    rel = RelogioFake(DIA)
    coord, db, _pub, ponte = _montar(tmp_path, _meds(["08:00"]), rel)
    coord.tick()
    assert db.ocorrencia_ativa()["estado"] == "ALARME"
    assert ponte.ultimo_buzzer == "dose"

    rel.marcar(EPOCH)
    coord.tick()
    assert ponte.ultimo_buzzer == "off"


def test_retomada_do_relogio_recomeca_os_temporizadores(tmp_path):
    rel = RelogioFake(DIA)
    cfg = Config(intervalo_alarme_s=60)
    coord, db, _pub, ponte = _montar(tmp_path, _meds(["08:00"]), rel, config=cfg)
    coord.tick()
    assert db.ocorrencia_ativa()["estado"] == "ALARME"

    rel.marcar(EPOCH)  # a hora some no meio do alarme
    for _ in range(4):
        rel.avancar(seconds=30)
        coord.tick()
    # 2 min de alarme sem timeout: o tempo parou de contar
    assert db.ocorrencia_ativa()["estado"] == "ALARME"
    assert db.ocorrencia_ativa()["tentativas"] == 0

    rel.marcar(DIA + timedelta(minutes=5))
    coord.tick()  # a hora volta
    assert "relogio_confiavel" in [log["tipo"] for log in db.ultimos_logs()]


# --- doses que passaram sem lembrete ----------------------------------------


def test_dose_passar_da_janela_nao_dispara_em_fila(tmp_path):
    """Aparelho que ligou 3 h depois não toca a dose das 08:00 às 14:00."""
    rel = RelogioFake(DIA + timedelta(hours=6))
    coord, db, pub, _ponte = _montar(tmp_path, _meds(["08:00", "12:00"]), rel)
    coord.tick()

    estados = {o["horario"]: o["estado"] for o in db.ocorrencias_do_dia("2026-09-19")}
    assert estados == {"08:00": "NAO_ATENDIDA", "12:00": "NAO_ATENDIDA"}
    assert db.ocorrencia_ativa() is None
    assert "hora_remedio" not in _chaves(pub)
    assert db.ultimos_logs()[0]["tipo"] == "doses_passadas"


def test_dose_dentro_da_janela_ainda_dispara(tmp_path):
    """10 min de atraso ainda ajuda o paciente: o alarme toca."""
    rel = RelogioFake(DIA + timedelta(minutes=10))
    coord, db, _pub, _ponte = _montar(tmp_path, _meds(["08:00"]), rel)
    coord.tick()
    assert db.ocorrencia_ativa()["estado"] == "ALARME"


def test_doses_perdidas_por_relogio_viram_um_aviso_agregado(tmp_path):
    rel = RelogioFake(EPOCH)
    coord, db, _pub, _ponte = _montar(tmp_path, _meds(["08:00", "12:00"]), rel)
    coord.tick()
    assert db.outbox_pendentes() == []

    rel.marcar(DIA + timedelta(hours=14))  # NTP sincronizou às 22:00
    coord.tick()
    coord.tick()  # ticks seguintes não repetem o aviso

    pendentes = db.outbox_pendentes()
    assert [p["tipo"] for p in pendentes] == ["relogio"]
    import json

    payload = json.loads(pendentes[0]["payload"])
    assert payload["doses"] == 2
    assert payload["dia"] == "2026-09-19"
    assert "durou_s" not in payload  # começou em 1970: duração não é datável
    assert [o["estado"] for o in db.ocorrencias_do_dia("2026-09-19")] == [
        "NAO_ATENDIDA",
        "NAO_ATENDIDA",
    ]


def test_relogio_confiavel_sem_dose_perdida_nao_avisa(tmp_path):
    rel = RelogioFake(DIA)
    coord, db, _pub, _ponte = _montar(tmp_path, _meds(["08:00"]), rel)
    coord.tick()
    rel.marcar(EPOCH)
    coord.tick()
    rel.marcar(DIA + timedelta(minutes=1))
    coord.tick()

    assert [p["tipo"] for p in db.outbox_pendentes()] == []
    assert "relogio_confiavel" in [log["tipo"] for log in db.ultimos_logs()]


# --- o aviso no backend -----------------------------------------------------


def _aviso(doses):
    return registro_notificacao(
        None,
        {
            "tipo": "relogio",
            "dia": "2026-09-19",
            "doses": doses,
            "horario_real": "2026-09-19T22:00:00",
        },
    )


def test_aviso_de_relogio_vai_para_notificacoes_sem_nome_de_medicamento():
    aviso = _aviso(2)
    assert aviso["motivo"] == "relogio"
    assert aviso["dia"] == "19/09/2026"
    assert aviso["doses"] == "2"
    assert aviso["horario_real"] == "22:00"
    assert "2 doses" in aviso["mensagem"]
    assert "19/09/2026" in aviso["mensagem"]
    assert "nome" not in aviso
    assert "horario_previsto" not in aviso


def test_aviso_de_relogio_aceita_um_numero_quebrado():
    aviso = registro_notificacao(
        None, {"tipo": "relogio", "dia": "2026-09-19", "doses": "x"}
    )
    assert aviso["doses"] == "0"
    assert "0 doses" in aviso["mensagem"]


def test_aviso_de_dose_ainda_exige_ocorrencia():
    assert (
        registro_notificacao(None, {"tipo": "dose_perdida", "dia": "2026-09-19"})
        is None
    )


def test_plural_doses_em_portugues():
    assert plural_doses(0) == "0 doses"
    assert plural_doses(1) == "1 dose"
    assert plural_doses(7) == "7 doses"
