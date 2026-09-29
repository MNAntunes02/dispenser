"""Fluxo completo da Fase 5: agendador -> core -> socket -> "botão OK" -> fim.

Estes testes exercitam o caminho real de dados (core publica no socket, um
cliente lê e devolve `input:confirma`) com a ponte simulada no lugar do
hardware. São o que garante que a UI, sozinha, não decide o estado da dose.
"""

from __future__ import annotations

import json
import select
import socket
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.agendador import abrev_dia_semana
from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador
from core.servidor_ui import ServidorUI
from hardware.bridge.bridge_simulada import PonteSimulada

CONFIG = Config(
    tick_s=0.05,
    intervalo_alarme_s=120,
    max_tentativas=5,
    timeout_gaveta_s=120,
    timeout_retorno_s=120,
    limite_retorno_s=1800,
)


class ClienteUI:
    """Cliente do socket que age como a UI: lê telas e manda o OK do paciente.

    Reproduz o que o app Flutter faz — e, de propósito, nada mais: a dose só
    avança porque o core pediu `ok` e o sensor correspondente confirmou.
    """

    def __init__(self, caminho: Path) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.setblocking(False)
        self._sock.connect(str(caminho))
        self._buffer = b""
        self.telas: list[dict] = []
        self.alertas: list[dict] = []
        self.conectado = True

    def bombear(self, timeout: float = 0.05) -> None:
        """Lê o que já chegou, como a UI real faz o tempo todo."""
        fim = _agora() + timeout
        while self.conectado:
            restante = fim - _agora()
            if restante <= 0:
                return
            prontos, _, _ = select.select([self._sock], [], [], restante)
            if not prontos:
                return
            try:
                pedaco = self._sock.recv(4096)
            except BlockingIOError:
                return
            except OSError:
                self.conectado = False
                return
            if not pedaco:
                self.conectado = False
                return
            self._buffer += pedaco
            self._parse()

    def _parse(self) -> None:
        partes = self._buffer.split(b"\n")
        self._buffer = partes.pop()
        for bruta in partes:
            if not bruta.strip():
                continue
            msg = json.loads(bruta.decode("utf-8"))
            if msg.get("type") == "estado":
                self.telas.append(msg)
            elif msg.get("type") == "alerta":
                self.alertas.append(msg)

    def confirmar(self) -> None:
        self._sock.sendall(b'{"v":1,"type":"input","acao":"confirma"}\n')

    def enviar(self, msg: dict) -> None:
        self._sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))

    def fechar(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class EspiaoHardware(PonteSimulada):
    """Ponte simulada que registra buzzer/LEDs para os testes da UI."""

    def __init__(self) -> None:
        super().__init__()
        self.buzzer_tocou: list[str] = []
        self.buzzer_desligou = 0
        self.leds_acesos: list[str] = []
        self.mensagens: list[str] = []

    def buzzer(self, padrao: str) -> None:  # noqa: D102 - ver listas acima
        if padrao == "off":
            self.buzzer_desligou += 1
        else:
            self.buzzer_tocou.append(padrao)

    def led(self, cor: str) -> None:  # noqa: D102 - ver listas acima
        self.leds_acesos.append(cor)

    def slot_ocupado(self, slot: int) -> bool:
        return False


def _agenda_para_agora() -> AgendaMemo:
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


@pytest.fixture
def montagem(tmp_path):
    db = Database(tmp_path / "fluxo.db")
    ponte = EspiaoHardware()
    coord = Coordenador(CONFIG, db, _agenda_para_agora(), ponte)
    coord.conectar()
    servidor = ServidorUI(tmp_path / "ui.sock", retrato=coord.retrato_cache)
    servidor.iniciar()
    coord.definir_ui(servidor)
    coord.definir_publicador_ui(servidor)
    yield coord, ponte, servidor, db
    servidor.parar()
    coord.finalizar()


def _agora() -> float:
    import time

    return time.monotonic()


def _rodar_ate(coord: Coordenador, servidor: ServidorUI, ui: ClienteUI, chave: str | None):
    """Dá ticks até a tela `chave` chegar (ou desistir)."""
    for _ in range(100):
        coord.tick()
        ui.bombear()
        if chave is None:
            if ui.telas:
                return True
        elif _chave(ui) == chave:
            return True
        servidor.aguardar_proxima(CONFIG.tick_s)
    return chave is None and bool(ui.telas) or _chave(ui) == chave


def _chave(ui: ClienteUI) -> str | None:
    return ui.telas[-1].get("chave") if ui.telas else None


def _estado(coord: Coordenador, db: Database) -> str | None:
    ocorrencias = db.ocorrencias_do_dia(datetime.now().date().isoformat())
    return ocorrencias[0]["estado"] if ocorrencias else None


def test_fluxo_dose_completo_pelo_socket(montagem):
    coord, ponte, servidor, db = montagem
    ui = ClienteUI(servidor.caminho)
    try:
        # 1. a dose vence e o core publica o primeiro passo
        assert _rodar_ate(coord, servidor, ui, "hora_remedio")
        assert ui.telas[-1]["passo"] == 1
        assert ui.telas[-1]["esperaBotao"] is True
        assert ui.telas[-1]["totalPassos"] == 6
        assert _estado(coord, db) == "ALARME"

        # 2. "abra a gaveta": só o OK do paciente move o passo (a UI não decide)
        ui.confirmar()
        assert _rodar_ate(coord, servidor, ui, "abra_gaveta")
        assert ponte.buzzer_tocou == ["dose"]  # alarme da dose
        assert ui.telas[-1]["esperaBotao"] is not True

        # 3. a gaveta abriu: o sensor move o passo, sem involve a UI
        ponte.simular({"e": "gaveta_aberta"})
        assert _rodar_ate(coord, servidor, ui, "retire_medicamento")

        # 4. retirar o medicamento do slot
        ponte.simular({"e": "slot_ausente", "slot": 0})
        assert _rodar_ate(coord, servidor, ui, "tome_e_ok")
        assert ui.telas[-1]["esperaBotao"] is True

        # 5. tomar e confirmar: a intenção volta pelo socket
        ui.confirmar()
        assert _rodar_ate(coord, servidor, ui, "devolva_slot")
        assert _estado(coord, db) == "AGUARDANDO_RETORNO"

        # 6. devolver o medicamento e fechar a gaveta
        ponte.simular({"e": "slot_presente", "slot": 0})
        ponte.simular({"e": "gaveta_fechada"})

        # fim: a ocorrência é registrada como tomada/concluída
        assert _rodar_ate(coord, servidor, ui, "tudo_certo")
        assert _estado(coord, db) == "CONCLUIDA"
        assert ui.telas[-1]["passo"] == 6
        assert ui.telas[-1]["esperaBotao"] is not True
    finally:
        ui.fechar()


def test_primeira_tela_mostra_o_passos_totais(montagem):
    coord, _ponte, servidor, _db = montagem
    ui = ClienteUI(servidor.caminho)
    try:
        assert _rodar_ate(coord, servidor, ui, None)
        assert ui.telas[-1]["totalPassos"] == 6
        assert 1 <= ui.telas[-1]["passo"] <= 6
    finally:
        ui.fechar()


def test_acao_desconhecida_da_ui_e_ignorada(montagem):
    """Política aprovada: sem soneca. A UI não inventa ação."""
    coord, _ponte, servidor, db = montagem
    ui = ClienteUI(servidor.caminho)
    try:
        ui.enviar({"v": 1, "type": "input", "acao": "soneca"})
        for _ in range(20):
            coord.tick()
            ui.bombear()
            servidor.aguardar_proxima(CONFIG.tick_s)
        assert _chave(ui) == "hora_remedio"  # não pulou para o passo 2
        assert _estado(coord, db) == "ALARME"
    finally:
        ui.fechar()


def test_mensagem_invalida_da_ui_gera_alerta_na_tela(montagem):
    coord, _ponte, servidor, _db = montagem
    ui = ClienteUI(servidor.caminho)
    try:
        ui._sock.sendall(b"isto nao e json\n")
        for _ in range(50):
            coord.tick()
            ui.bombear()
            if ui.alertas:
                break
            servidor.aguardar_proxima(CONFIG.tick_s)
        assert ui.alertas[-1]["codigo"] == "F005"
    finally:
        ui.fechar()


def test_reconexao_da_ui_redesenha_a_tela_atual(montagem):
    """A UI pode reiniciar à vontade: ao voltar, recebe o retrato pronto."""
    coord, _ponte, servidor, _db = montagem
    primeira = ClienteUI(servidor.caminho)
    assert _rodar_ate(coord, servidor, primeira, "hora_remedio")
    chave = _chave(primeira)
    primeira.fechar()

    segunda = ClienteUI(servidor.caminho)
    try:
        segunda.bombear(0.3)
        assert _chave(segunda) == chave
    finally:
        segunda.fechar()


def test_tela_de_repouso_avisa_proxima_dose(tmp_path):
    """Sem dose em aberto o core publica o repouso: a UI nunca fica "conectando"."""
    agora = datetime.now() + timedelta(minutes=30)
    agenda = AgendaMemo(
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
    db = Database(tmp_path / "repouso.db")
    ponte = PonteSimulada()
    coord = Coordenador(CONFIG, db, agenda, ponte)
    coord.conectar()
    servidor = ServidorUI(tmp_path / "ui.sock", retrato=coord.retrato_cache)
    servidor.iniciar()
    coord.definir_ui(servidor)
    coord.definir_publicador_ui(servidor)
    ui = ClienteUI(servidor.caminho)
    try:
        assert _rodar_ate(coord, servidor, ui, "reposo")
        assert ui.telas[-1]["fluxo"] == "reposo"
        assert ui.telas[-1]["proxima"] == agora.strftime("%H:%M")
        assert "passo" not in ui.telas[-1]  # fora do fluxo guiado
        assert ui.telas[-1]["mensagem"] == "Tudo em dia. Próxima dose às " + agora.strftime("%H:%M")
    finally:
        ui.fechar()
        servidor.parar()
        coord.finalizar()
