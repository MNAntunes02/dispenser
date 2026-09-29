"""Testes de boot e robustez (Fase 7): watchdog, instância única e disco.

Estes testes não dependem do systemd: o `NOTIFY_SOCKET` e o `flock` são reais,
mas criados no tmpdir. O que muda no Pi é apenas quem chama (`sd_notify` e o
gerenciador de serviços), não o protocolo exercitado aqui.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.armazenamento import Database
from core.instancia import JaExisteInstancia, TravaDeInstancia
from core.saude import NotificadorSaude, caminho_notify

DIA = datetime(2026, 9, 19, 8, 0, 0)


@pytest.fixture
def notify_socket(tmp_path):
    """Socket de notificação em disco, com um leitor coletando as mensagens."""
    caminho = tmp_path / "notify.sock"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    srv.bind(str(caminho))
    srv.settimeout(0.2)
    recebidas: list[bytes] = []

    def _leitor():
        while True:
            try:
                recebidas.append(srv.recv(4096))
            except (socket.timeout, OSError):
                return

    thread = threading.Thread(target=_leitor, daemon=True)
    thread.start()
    yield caminho, recebidas
    srv.close()


def esperar_por(recebidas: list, minimo: int, limite_s: float = 2.0) -> None:
    """Espera o leitor da thread receber o bastante (evita testar o scheduler)."""
    fim = time.monotonic() + limite_s
    while len(recebidas) < minimo and time.monotonic() < fim:
        time.sleep(0.01)
    assert len(recebidas) >= minimo, f"chegaram {len(recebidas)} de {minimo}"


# --- watchdog (core/saude.py) ------------------------------------------------


def test_caminho_notify_vazio_sem_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert caminho_notify() is None


def test_caminho_notify_aceita_ambiente_explicito():
    assert caminho_notify({"NOTIFY_SOCKET": "/run/x"}) == "/run/x"


def test_fora_do_systemd_o_watchdog_e_noop():
    """Sem NOTIFY_SOCKET (demo, dev, teste): nada quebra, nada echa."""
    n = NotificadorSaude(caminho=None)
    assert n.ativo is False
    assert n.iniciar() is False
    assert n.pulso(forcar=True) is False
    assert n.parar() is False


def test_avisa_ready_e_watchdog(notify_socket):
    caminho, recebidas = notify_socket
    n = NotificadorSaude(caminho=str(caminho), intervalo_s=0)
    n.iniciar("core no ar")
    n.pulso("tudo certo")
    esperar_por(recebidas, 2)
    texto = b"\n".join(recebidas).decode()
    assert "READY=1" in texto
    assert "WATCHDOG=1" in texto
    assert "STATUS=core no ar" in texto
    assert f"MAINPID={os.getpid()}" in texto


def test_pulso_respeita_o_intervalo(notify_socket):
    """O tick roda a cada 5 s: pulsar a cada 5 s gastaria o journal à toa."""
    caminho, recebidas = notify_socket
    n = NotificadorSaude(caminho=str(caminho), intervalo_s=30)
    n.iniciar()
    esperar_por(recebidas, 1)  #READY consumido antes de contar
    recebidas.clear()
    assert n.pulso() is False  # ainda não passou 30 s
    assert n.pulso(forcar=True) is True
    time.sleep(0.3)
    assert recebidas == [b"WATCHDOG=1"]


def test_status_quebra_linha_nao_estraga_o_protocolo(notify_socket):
    """O sd_notify é um protocolo de texto: uma \\n doida criaria campo falso."""
    caminho, recebidas = notify_socket
    n = NotificadorSaude(caminho=str(caminho), intervalo_s=0)
    n.iniciar("linha 1\nMAINPID=999999")
    esperar_por(recebidas, 1)
    texto = b"\n".join(recebidas).decode()
    assert "STATUS=linha 1 MAINPID=999999" in texto
    # O status vira uma linha só: não nasce um campo MAINPID falso.
    assert "\n999999" not in texto
    assert "READY=1" in texto.splitlines()[0]


def test_socket_morto_desliga_sem_derrubar_o_core(tmp_path):
    """O systemd pode não estar escutando: o core continua, só sem watchdog."""
    caminho = tmp_path / "inexistente.sock"
    avisos: list[str] = []
    n = NotificadorSaude(
        caminho=str(caminho), intervalo_s=0, ao_falhar=avisos.append
    )
    assert n.iniciar() is False
    assert n.ativo is False
    assert avisos  # avisou uma vez
    avisos.clear()
    # Segunda tentativa não repete o aviso: o ruído no journal também conta.
    assert n.pulso(forcar=True) is False
    assert avisos == []


def test_stopping_ao_encerrar(notify_socket):
    caminho, recebidas = notify_socket
    n = NotificadorSaude(caminho=str(caminho), intervalo_s=0)
    n.iniciar()
    esperar_por(recebidas, 1)
    recebidas.clear()
    assert n.parar("encerrando") is True
    esperar_por(recebidas, 1)
    assert b"STOPPING=1" in b"\n".join(recebidas)


# --- instância única (core/instancia.py) -------------------------------------


def test_lock_impede_segundo_core(tmp_path):
    caminho = tmp_path / "core.lock"
    first = TravaDeInstancia(caminho).adquirir()
    try:
        with pytest.raises(JaExisteInstancia):
            TravaDeInstancia(caminho).adquirir()
    finally:
        first.liberar()
    # Liberado, outro core entra sem intervenção (boot após queda de energia).
    segundo = TravaDeInstancia(caminho).adquirir()
    segundo.liberar()


def test_lock_grava_o_pid(tmp_path):
    caminho = tmp_path / "core.lock"
    trava = TravaDeInstancia(caminho).adquirir()
    try:
        assert caminho.read_text(encoding="utf-8").strip() == str(os.getpid())
    finally:
        trava.liberar()


def test_liberar_e_idempotente(tmp_path):
    trava = TravaDeInstancia(tmp_path / "core.lock").adquirir()
    trava.liberar()
    trava.liberar()  # não levanta


def test_lock_liberado_quando_o_processo_morre(tmp_path):
    """O flock é do kernel: SIGKILL (queda de energia) não deixa lock órfão."""
    caminho = tmp_path / "core.lock"
    codigo = (
        "import fcntl, pathlib, sys, time\n"
        f"f = open({str(caminho)!r}, 'a+')\n"
        "fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "sys.stdout.write('ok')\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    filho = subprocess.Popen(
        [sys.executable, "-c", codigo], stdout=subprocess.PIPE
    )
    try:
        assert filho.stdout.read(2) == b"ok"
        with pytest.raises(JaExisteInstancia):
            TravaDeInstancia(caminho).adquirir()
    finally:
        filho.kill()
        filho.wait(timeout=10)
    # Processo morto: o kernel liberou, o novo core assume.
    trava = TravaDeInstancia(caminho).adquirir()
    trava.liberar()


# --- disco e retenção (core/armazenamento.py) --------------------------------


def test_pragmas_de_cartao_sd(tmp_path):
    """WAL + synchronous normal: uma escrita por transação, sem fsync por commit."""
    db = Database(tmp_path / "s.db")
    db.conectar()
    try:
        modo = db.conexao.execute("PRAGMA journal_mode").fetchone()[0]
        sinc = db.conexao.execute("PRAGMA synchronous").fetchone()[0]
        assert modo.lower() == "wal"
        assert sinc == 1  # NORMAL
    finally:
        db.fechar()


def test_wal_e_consolidado_no_encerre(tmp_path):
    """Fechar consolida o WAL: uma escrita em vez de deixá-lo para depois."""
    caminho = tmp_path / "s.db"
    db = Database(caminho)
    db.conectar()
    db.registrar_log("dose_tomada")
    db.fechar()
    wal = caminho.with_name(caminho.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0


def test_fila_outbox_nunca_e_purgada(tmp_path):
    """Purga a trilha velha, mas evento não enviado é evento que não se perde."""
    relogio = [DIA]
    db = Database(
        tmp_path / "s.db",
        relogio=lambda: relogio[0],
        retencao_log_dias=30,
    )
    db.conectar()
    try:
        # Evento antigo, ainda pendente de entrega ao cuidador.
        db.registrar_log("dose_perdida")
        db.enfileirar_outbox("med0|2026-08-01|08:00", "med0", "dose_perdida", {})
        relogio[0] = DIA + timedelta(days=10)

        assert db.purgar_logs() == 0  # dentro da retenção de 30 dias
        relogio[0] = DIA + timedelta(days=60)
        assert db.purgar_logs(forcar=True) == 1
        assert db.ultimos_logs() == []
        pendentes = db.outbox_pendentes()
        assert len(pendentes) == 1
        assert pendentes[0]["tipo"] == "dose_perdida"
    finally:
        db.fechar()


def test_purga_roda_uma_vez_por_dia(tmp_path):
    """O core chama a cada tick: sem guarda, seriam writes a cada 5 s."""
    relogio = [DIA]
    db = Database(
        tmp_path / "s.db",
        relogio=lambda: relogio[0],
        retencao_log_dias=30,
    )
    db.conectar()
    try:
        # Linha antiga inserida direto: o carimbo vem do relógio injetado, e um
        # registro "de hoje" nunca poderia ser candidato à purga.
        antiga = (DIA - timedelta(days=90)).isoformat(timespec="seconds")
        db.conexao.execute(
            "INSERT INTO log_eventos (em, tipo, detalhe) VALUES (?, ?, ?)",
            (antiga, "antiga", ""),
        )
        db.conexao.commit()

        relogio[0] = DIA
        assert db.purgar_logs() == 1
        # A fila chama a cada tick (5 s): sem a guarda diária, isto seria uma
        # escrita no cartão a cada tick para não remover nada.
        assert db.purgar_logs() == 0
        assert db.purgar_logs() == 0

        relogio[0] = DIA + timedelta(days=1)
        db.conexao.execute(
            "INSERT INTO log_eventos (em, tipo, detalhe) VALUES (?, ?, ?)",
            (antiga, "antiga", ""),
        )
        db.conexao.commit()
        assert db.purgar_logs() == 1
    finally:
        db.fechar()


def test_retencao_zero_desliga_a_purga(tmp_path):
    relogio = [DIA]
    db = Database(tmp_path / "s.db", relogio=lambda: relogio[0], retencao_log_dias=0)
    db.conectar()
    try:
        db.registrar_log("fica_para_sempre")
        relogio[0] = DIA + timedelta(days=3650)
        assert db.purgar_logs() == 0
        assert len(db.ultimos_logs()) == 1
    finally:
        db.fechar()
