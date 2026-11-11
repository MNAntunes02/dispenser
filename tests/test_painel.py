"""Testes do painel de desenvolvimento (sem abrir a janela Tkinter).

A GUI em si não é testada aqui (Tkinter exige display); o que importa é o
contrato que a janela usa: comandos/ambiente isolados, buffer de log e ciclo de
vida dos processos.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.agendador import abrev_dia_semana
from core.protocolo_ui import comando_simular
from core.servidor_ui import ServidorUI
from painel import configuracao
from painel.comandos import ComandosCore
from painel.gerenciador import (
    EstadoServico,
    FalhaAoIniciar,
    JaRodando,
    Servico,
)
from painel.log_buffer import BufferLog, formatar, limpar_ansi
from painel.textos import TEXTOS

# --- configuração/ambiente ---------------------------------------------------


def test_comando_core_usa_entrypoint_do_projeto():
    comando = configuracao.comando_core()
    assert comando[1:] == ["-m", "core.dispenser_main"]
    assert Path(comando[0]).exists()


def test_ambiente_core_carrega_env_e_aponta_estado_para_run(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comentario\n"
        "FIREBASE_PROJECT_ID=projeto-dev\n"
        "DISPENSER_CREDENTIALS_PATH=/cred.json\n"
        "DISPENSER_DB_PATH=/outra/maquina/.run/state.db\n"
        "DISPENSER_SOCKET=/outra/maquina/.run/core.sock\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(configuracao, "DIR_DEV", tmp_path / ".run")
    monkeypatch.setattr(configuracao, "ARQUIVO_ENV_DEV", env)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "projeto-do-shell")
    monkeypatch.setenv("DISPENSER_USER_ID", "paciente-do-shell")
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    monkeypatch.setenv("WATCHDOG_USEC", "45000000")
    monkeypatch.setenv("DISPENSER_AGENDA_JSON", "/tmp/agenda.json")

    ambiente = configuracao.ambiente_core()

    dev = tmp_path / ".run"
    # Variáveis do .env entram no ambiente (como `source .env`)...
    assert ambiente["FIREBASE_PROJECT_ID"] == "projeto-dev"
    assert ambiente["DISPENSER_CREDENTIALS_PATH"] == "/cred.json"
    # ...mas os caminhos de estado são sempre os do projeto atual.
    assert ambiente["DISPENSER_DB_PATH"] == str(dev / "state.db")
    assert ambiente["DISPENSER_SOCKET"] == str(dev / "core.sock")
    assert ambiente["DISPENSER_LOCK_PATH"] == str(dev / "core.lock")
    assert ambiente["DISPENSER_ENV_PATH"] == str(env)
    assert ambiente["PYTHONUNBUFFERED"] == "1"
    # Credencial herdada do shell e variáveis do systemd não vazam.
    for chave in (
        "DISPENSER_USER_ID",
        "NOTIFY_SOCKET",
        "WATCHDOG_USEC",
        "DISPENSER_AGENDA_JSON",
    ):
        assert chave not in ambiente


def test_ambiente_core_sem_env_roda_em_modo_demo(monkeypatch, tmp_path):
    monkeypatch.setattr(configuracao, "DIR_DEV", tmp_path / ".run")
    monkeypatch.setattr(configuracao, "ARQUIVO_ENV_DEV", tmp_path / ".env")
    monkeypatch.setenv("DISPENSER_USER_ID", "paciente-do-shell")

    ambiente = configuracao.ambiente_core()

    assert "DISPENSER_USER_ID" not in ambiente
    assert ambiente["DISPENSER_SOCKET"] == str(tmp_path / ".run" / "core.sock")


def test_ler_env_dev_aceita_export_e_aspas(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "export A=1\nB=\"dois\"\nC='tres'\nsem_igual\n\n# D=4\nE=a=b\n",
        encoding="utf-8",
    )
    assert configuracao.ler_env_dev(env) == {
        "A": "1",
        "B": "dois",
        "C": "tres",
        "E": "a=b",
    }
    assert configuracao.ler_env_dev(tmp_path / "nao-existe") == {}


def test_binario_ui_usa_bundle_debug_da_arquitetura(monkeypatch, tmp_path):
    monkeypatch.setattr(configuracao, "PASTA_UI", tmp_path / "ui")
    monkeypatch.setattr(configuracao.platform, "machine", lambda: "aarch64")
    bundle = tmp_path / "ui" / "build" / "linux" / "arm64" / "debug" / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "dispenser_ui").write_text("")

    assert configuracao.binario_ui() == bundle / "dispenser_ui"
    assert configuracao.comando_ui() == [str(bundle / "dispenser_ui")]


def test_binario_ui_cai_para_outra_arquitetura_encontrada(monkeypatch, tmp_path):
    monkeypatch.setattr(configuracao, "PASTA_UI", tmp_path / "ui")
    monkeypatch.setattr(configuracao.platform, "machine", lambda: "aarch64")
    bundle = tmp_path / "ui" / "build" / "linux" / "x64" / "debug" / "bundle"
    bundle.mkdir(parents=True)
    (bundle / "dispenser_ui").write_text("")

    assert configuracao.binario_ui() == bundle / "dispenser_ui"


def test_ambiente_ui_renderiza_por_software_e_aponta_para_socket(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(configuracao, "DIR_DEV", tmp_path / ".run")
    monkeypatch.setenv("DISPENSER_CREDENTIALS_PATH", "/segredo.json")

    ambiente = configuracao.ambiente_ui()

    assert ambiente["DISPENSER_SOCKET"] == str(tmp_path / ".run" / "core.sock")
    assert ambiente["LIBGL_ALWAYS_SOFTWARE"] == "1"
    assert ambiente["FLUTTER_ENGINE_SWITCHES"] == "1"
    assert ambiente["FLUTTER_ENGINE_SWITCH_1"] == "enable-impeller=false"
    assert "DISPENSER_CREDENTIALS_PATH" not in ambiente


def test_agenda_demo_gera_dose_dois_minutos_a_frente(tmp_path):
    agora = datetime(2026, 11, 9, 10, 0, 0)
    agenda = configuracao.gerar_agenda_demo(
        tmp_path / "agenda.json", agora=agora
    )

    assert agenda.horario == "10:02"
    dados = json.loads(Path(agenda.caminho).read_text(encoding="utf-8"))
    assert dados[0]["id"] == "med-demo"
    assert dados[0]["dias"][0]["dia_semana"] == abrev_dia_semana(
        agora.date()
    )
    assert dados[0]["dias"][0]["horario"] == ["10:02"]


def test_agenda_demo_atravessa_meia_noite(tmp_path):
    agora = datetime(2026, 11, 9, 23, 59, 0)
    agenda = configuracao.gerar_agenda_demo(
        tmp_path / "agenda.json", agora=agora
    )

    assert agenda.horario == "00:01"
    dados = json.loads(Path(agenda.caminho).read_text(encoding="utf-8"))
    assert dados[0]["dias"][0]["dia_semana"] == abrev_dia_semana(
        (agora + timedelta(days=1)).date()
    )


# --- buffer de log -----------------------------------------------------------


def test_buffer_limita_filtra_e_formata():
    buffer = BufferLog(limite=3)
    inicio = datetime(2026, 11, 9, 10, 0, 0)
    for indice in range(5):
        buffer.adicionar(
            "core",
            "saida",
            f"linha {indice}",
            momento=inicio + timedelta(seconds=indice),
        )

    assert len(buffer) == 3
    assert [linha.texto for linha in buffer.linhas()] == [
        "linha 2",
        "linha 3",
        "linha 4",
    ]
    assert [linha.texto for linha in buffer.filtrar("LINHA 3")] == [
        "linha 3"
    ]
    assert "10:00:04" in formatar(buffer.linhas()[-1])
    assert "linha 4" in buffer.texto()


def test_limpar_ansi_remove_cores_e_retorno_de_carro():
    assert limpar_ansi("\x1b[32mok\x1b[0m\r") == "ok"
    assert limpar_ansi("\x1b[32mok\x1b[0m\r\n") == "ok\n"


# --- processos ---------------------------------------------------------------


def _codigo_que_imprime_e_dorme() -> str:
    return (
        "import time; "
        "print('pronto', flush=True); "
        "time.sleep(30)"
    )


def _codigo_que_ignora_sigterm() -> str:
    return (
        "import signal, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print('pronto', flush=True); "
        "time.sleep(30)"
    )


def _esperar(eventos: list, predicado, limite_s: float = 5.0) -> None:
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        if predicado(eventos):
            return
        time.sleep(0.01)
    assert predicado(eventos), eventos


def _novo_servico(tmp_path: Path, codigo: str, eventos: list) -> Servico:
    return Servico(
        "teste",
        [sys.executable, "-u", "-c", codigo],
        tmp_path,
        os.environ.copy(),
        eventos.append,
    )


def test_servico_inicia_entrega_log_e_para(tmp_path):
    eventos: list = []
    servico = _novo_servico(tmp_path, _codigo_que_imprime_e_dorme(), eventos)

    servico.iniciar()
    assert servico.estado is EstadoServico.RODANDO
    assert servico.pid is not None
    _esperar(
        eventos,
        lambda e: any(
            evento[0] == "log" and "pronto" in evento[3] for evento in e
        ),
    )

    servico.parar_sincrono(timeout_s=2.0)

    assert servico.ativo is False
    assert servico.estado is EstadoServico.PARADO
    assert any(
        evento[0] == "log" and "parado" in evento[3] for evento in eventos
    )


def test_servico_recusa_iniciar_duas_vezes(tmp_path):
    eventos: list = []
    servico = _novo_servico(tmp_path, _codigo_que_imprime_e_dorme(), eventos)
    servico.iniciar()
    try:
        with pytest.raises(JaRodando):
            servico.iniciar()
    finally:
        servico.parar_sincrono(timeout_s=2.0)


def test_falha_ao_iniciar_marca_estado_e_erro(tmp_path):
    eventos: list = []
    servico = Servico(
        "teste",
        [str(tmp_path / "comando-que-nao-existe")],
        tmp_path,
        os.environ.copy(),
        eventos.append,
    )

    with pytest.raises(FalhaAoIniciar):
        servico.iniciar()

    assert servico.estado is EstadoServico.ENCERRADO
    assert servico.erro
    assert any(
        evento[0] == "log" and evento[2] == "erro" for evento in eventos
    )


def test_parada_escalona_para_sigkill(tmp_path):
    eventos: list = []
    servico = _novo_servico(tmp_path, _codigo_que_ignora_sigterm(), eventos)
    servico.iniciar()
    _esperar(
        eventos,
        lambda e: any(
            evento[0] == "log" and "pronto" in evento[3] for evento in e
        ),
    )

    inicio = time.monotonic()
    servico.parar_sincrono(timeout_s=0.5)

    assert servico.ativo is False
    assert servico.estado is EstadoServico.PARADO
    assert time.monotonic() - inicio < 8.0
    assert any(
        evento[0] == "log" and "SIGKILL" in evento[3] for evento in eventos
    )


# --- comandos ao core pelo socket (simulador, ADR 015) -----------------------


def _drenar_ate(servidor: ServidorUI, quantidade: int) -> list[dict]:
    """Drena a fila de entradas até chegar `quantidade` mensagens."""
    recebidas: list[dict] = []
    fim = time.monotonic() + 5.0
    while time.monotonic() < fim and len(recebidas) < quantidade:
        recebidas.extend(servidor.entradas())
        time.sleep(0.01)
    return recebidas


def test_comandos_core_envia_simulacoes_ao_socket(tmp_path):
    """O painel fala o mesmo protocolo da UI, no mesmo socket."""
    servidor = ServidorUI(tmp_path / "core.sock")
    servidor.iniciar()
    try:
        logs: list[tuple[str, str]] = []
        comandos = ComandosCore(
            servidor.caminho, ao_logar=lambda fluxo, msg: logs.append((fluxo, msg))
        )

        # um por vez: cada clique do painel é uma conexão one-shot, e a ordem
        # de threads separadas não é garantida
        comandos.simular("gaveta_aberta")
        entradas = _drenar_ate(servidor, 1)
        comandos.simular("slot_ausente", 2)
        entradas += _drenar_ate(servidor, 1)

        assert [e["args"] for e in entradas] == [
            {"evento": "gaveta_aberta"},
            {"evento": "slot_ausente", "slot": 2},
        ]
        assert all(e["cmd"] == "simular" for e in entradas)
        assert logs == []  # envio sem erro não gera log
    finally:
        servidor.parar()


def test_comandos_core_loga_falha_quando_o_core_nao_existe(tmp_path):
    logs: list[tuple[str, str]] = []
    comandos = ComandosCore(
        tmp_path / "inexistente.sock",
        ao_logar=lambda fluxo, msg: logs.append((fluxo, msg)),
    )

    comandos.simular("gaveta_aberta")

    fim = time.monotonic() + 5.0
    while time.monotonic() < fim and not logs:
        time.sleep(0.01)
    assert logs, "a falha de conexão deveria virar log"
    fluxo, mensagem = logs[0]
    assert fluxo == "erro"
    assert mensagem.startswith("falha ao enviar simulação")


def test_textos_do_simulador_estao_completos():
    # Regra 9 do AGENTS.md: strings do painel centralizadas em painel/textos.py.
    for chave in (
        "simulador",
        "simulador_dica",
        "simular_abrir_gaveta",
        "simular_fechar_gaveta",
        "simular_retirar",
        "simular_devolver",
        "simular_slot",
        "simulado",
        "simulado_slot",
        "erro_simular",
    ):
        assert chave in TEXTOS, f"texto ausente: {chave}"
        assert TEXTOS[chave].strip()
