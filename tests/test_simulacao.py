"""Comando `simular` do protocolo da UI (ADR 015 — painel de desenvolvimento).

O painel injeta eventos de sensor **na ponte simulada** para exercitar o fluxo
sem hardware. Estes testes guardam as propriedades de segurança:

- a simulação nunca confirma dose (`ok`/`botao` ficam de fora);
- nunca fabrica falha de sensor;
- é recusada quando a ponte não a suporta (hardware real, Fase 4+).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from core.agendador import abrev_dia_semana
from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador, PublicadorLog
from core.protocolo_ui import comando_simular, envelope
from hardware.bridge.bridge_simulada import PonteSimulada

CONFIG = Config(
    tick_s=0.05,
    intervalo_alarme_s=120,
    max_tentativas=5,
    timeout_gaveta_s=120,
    timeout_retorno_s=120,
    limite_retorno_s=1800,
)

CONFIRMA = {"v": 1, "type": "input", "acao": "confirma"}


def _agenda_de_agora() -> AgendaMemo:
    agora = datetime.now()
    return AgendaMemo(
        [
            {
                "id": "med-1",
                "nome": "Losartana 50 mg",
                "dosagem": "1 comprimido",
                "dias": [
                    {
                        "dia_semana": abrev_dia_semana(agora.date()),
                        "horario": [agora.strftime("%H:%M")],
                    }
                ],
            }
        ]
    )


class PonteSemSimulacao(PonteSimulada):
    """Ponte que recusa `simular`, como a ponte real (Fase 4) fará."""

    def simular(self, evento: dict) -> bool:
        return False


def _montar(tmp_path, ponte):
    db = Database(tmp_path / "sim.db")
    pub = PublicadorLog()
    coord = Coordenador(CONFIG, db, _agenda_de_agora(), ponte, publicador_ui=pub)
    coord.conectar()
    return coord, db, pub


def _chave_tela(pub: PublicadorLog) -> str | None:
    for msg in reversed(pub.mensagens):
        if msg.get("type") == "estado":
            return msg.get("chave")
    return None


def _tipos_de_log(db: Database) -> list[str]:
    return [linha["tipo"] for linha in db.ultimos_logs(limite=200)]


def _esperar_tela(coord: Coordenador, pub: PublicadorLog, chave: str) -> None:
    for _ in range(20):
        coord.tick()
        if _chave_tela(pub) == chave:
            return
    raise AssertionError(f"tela {chave} não chegou (última: {_chave_tela(pub)})")


# --- fluxo conduzido pelos comandos do painel --------------------------------


def test_fluxo_da_dose_conduzido_por_comandos(tmp_path):
    """Painel move gaveta/slots; o OK continua sendo do paciente."""
    coord, db, pub = _montar(tmp_path, PonteSimulada())
    try:
        _esperar_tela(coord, pub, "hora_remedio")

        assert coord.entrada_ui(CONFIRMA) is True
        coord.tick()
        assert _chave_tela(pub) == "abra_gaveta"

        # os sensores agora vêm dos comandos de simulação
        assert coord.entrada_ui(comando_simular("gaveta_aberta")) is True
        coord.tick()
        assert _chave_tela(pub) == "retire_medicamento"

        assert coord.entrada_ui(comando_simular("slot_ausente", 0)) is True
        coord.tick()
        assert _chave_tela(pub) == "tome_e_ok"

        # simular não substitui o OK: a dose só é registrada com o paciente
        assert coord.entrada_ui(CONFIRMA) is True
        coord.tick()
        assert _chave_tela(pub) == "devolva_slot"

        assert coord.entrada_ui(comando_simular("slot_presente", 0)) is True
        assert coord.entrada_ui(comando_simular("gaveta_fechada")) is True
        coord.tick()
        assert _chave_tela(pub) == "tudo_certo"
        assert db.ocorrencia_ativa() is None
    finally:
        coord.finalizar()


def test_comando_simula_o_retorno_sem_slot_mapeado(tmp_path):
    """Sem slot na ocorrência, devolver vale para qualquer slot ocupado."""
    coord, _db, pub = _montar(tmp_path, PonteSimulada())
    try:
        _esperar_tela(coord, pub, "hora_remedio")
        coord.entrada_ui(CONFIRMA)
        coord.tick()
        coord.entrada_ui(comando_simular("gaveta_aberta"))
        coord.tick()
        coord.entrada_ui(comando_simular("slot_ausente", 0))
        coord.tick()
        coord.entrada_ui(CONFIRMA)
        coord.tick()
        assert _chave_tela(pub) == "devolva_slot"
        # qualquer slot presente + gaveta fechada fecha a dose
        assert coord.entrada_ui(comando_simular("slot_presente", 3)) is True
        assert coord.entrada_ui(comando_simular("gaveta_fechada")) is True
        coord.tick()
        assert _chave_tela(pub) == "tudo_certo"
    finally:
        coord.finalizar()


# --- recusas (segurança do paciente) ------------------------------------------


def test_ponte_sem_simulacao_recusa_o_comando(tmp_path):
    """Com hardware real o comando é recusado; nada avança sozinho."""
    coord, db, pub = _montar(tmp_path, PonteSemSimulacao())
    try:
        _esperar_tela(coord, pub, "hora_remedio")
        coord.entrada_ui(CONFIRMA)
        coord.tick()
        assert _chave_tela(pub) == "abra_gaveta"

        assert coord.entrada_ui(comando_simular("gaveta_aberta")) is False
        coord.tick()
        # a dose não saiu do lugar: o sensor físico é a fonte de verdade
        assert _chave_tela(pub) == "abra_gaveta"
        assert "ui_comando_ignorado:simular/gaveta_aberta" in _tipos_de_log(db)
    finally:
        coord.finalizar()


@pytest.mark.parametrize(
    "evento", ["ok", "botao", "falha", "horario_chegou", "evento_novo", ""]
)
def test_comando_simular_nao_confirma_dose_nem_fabrica_falha(tmp_path, evento):
    coord, db, pub = _montar(tmp_path, PonteSimulada())
    try:
        _esperar_tela(coord, pub, "hora_remedio")
        msg = envelope("comando", cmd="simular", args={"evento": evento})
        assert coord.entrada_ui(msg) is False
        for _ in range(3):
            coord.tick()
        # continua no passo 1, alarme de pé, nada registrado
        assert _chave_tela(pub) == "hora_remedio"
        assert db.ocorrencia_ativa() is not None
        assert "ui_comando_ignorado:simular/" + (evento or "vazio") in _tipos_de_log(db)
    finally:
        coord.finalizar()


@pytest.mark.parametrize(
    "args",
    [
        None,
        "gaveta_aberta",
        {},
        {"evento": "slot_ausente"},
        {"evento": "slot_ausente", "slot": "x"},
        {"evento": "slot_ausente", "slot": None},
    ],
)
def test_args_invalidos_sao_ignorados_sem_excecao(tmp_path, args):
    coord, db, pub = _montar(tmp_path, PonteSimulada())
    try:
        _esperar_tela(coord, pub, "hora_remedio")
        msg = envelope("comando", cmd="simular", args=args)
        assert coord.entrada_ui(msg) is False
        coord.tick()
        assert _chave_tela(pub) == "hora_remedio"
        assert any(
            tipo.startswith("ui_comando_ignorado:simular")
            for tipo in _tipos_de_log(db)
        )
    finally:
        coord.finalizar()


def test_slot_fora_do_hardware_e_recusado(tmp_path):
    coord, db, pub = _montar(tmp_path, PonteSimulada())
    try:
        _esperar_tela(coord, pub, "hora_remedio")
        coord.entrada_ui(CONFIRMA)
        coord.tick()
        coord.entrada_ui(comando_simular("gaveta_aberta"))
        coord.tick()
        assert coord.entrada_ui(comando_simular("slot_ausente", 99)) is False
        coord.tick()
        assert _chave_tela(pub) == "retire_medicamento"
        assert "ui_comando_ignorado:simular/slot_ausente" in _tipos_de_log(db)
    finally:
        coord.finalizar()


def test_comando_desconhecido_e_ignorado(tmp_path):
    coord, db, _pub = _montar(tmp_path, PonteSimulada())
    try:
        msg = envelope("comando", cmd="desligar")
        assert coord.entrada_ui(msg) is False
        assert "ui_comando_ignorado:desligar" in _tipos_de_log(db)
    finally:
        coord.finalizar()


# --- ponte simulada: validação de slot -----------------------------------------


def test_ponte_simulada_recusa_slot_fora_da_faixa():
    ponte = PonteSimulada(slots=4)
    ponte.conectar()
    recebidos: list[dict] = []
    ponte.registrar_evento(recebidos.append)
    try:
        assert ponte.simular({"e": "slot_presente", "slot": 4}) is False
        assert ponte.simular({"e": "slot_ausente", "slot": -1}) is False
        assert ponte.simular({"e": "slot_presente"}) is False
        assert recebidos == []  # nada foi repassado
        assert ponte.status()["slots"]["0"]["presente"] == 0
    finally:
        ponte.desconectar()


def test_ponte_base_recusa_simular():
    from hardware.bridge.bridge_real import PonteSerial

    ponte = PonteSerial("/dev/null")
    assert ponte.simular({"e": "gaveta_aberta"}) is False
