"""Testes do servidor Unix da UI (core/servidor_ui.py).

Usam um socket real em `tmp_path` e um cliente falso: o servidor é testado
sem UI Flutter, sem placa e sem rede.
"""

from __future__ import annotations

import json
import socket
import stat
import time
from datetime import datetime

import pytest

from core.protocolo_ui import envelope
from core.servidor_ui import ServidorUI

RELOGIO = datetime(2026, 9, 29, 8, 0, 0)


class ClienteFake:
    """UI mínima: conecta, lê linhas JSON e envia mensagens."""

    def __init__(self, caminho, timeout: float = 2.0) -> None:
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        self._sock.connect(str(caminho))
        self._buffer = b""
        self._pendentes: list[dict] = []

    def receber(self, tipo: str | None = None, timeout: float = 2.0) -> dict:
        """Espera a próxima mensagem (opcionalmente de um `type`).

        As mensagens que chegam no mesmo pacote ficam em fila: nada se perde.
        """
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            self._extrair()
            for i, msg in enumerate(self._pendentes):
                if tipo is None or msg.get("type") == tipo:
                    return self._pendentes.pop(i)
            self._sock.settimeout(max(0.01, limite - time.monotonic()))
            try:
                pedaco = self._sock.recv(4096)
            except socket.timeout:
                break
            if not pedaco:
                break
            self._buffer += pedaco
        raise AssertionError(f"mensagem {tipo!r} não chegou")

    def _extrair(self) -> None:
        linhas = self._buffer.split(b"\n")
        self._buffer = linhas.pop()
        self._pendentes.extend(
            json.loads(bruta.decode("utf-8")) for bruta in linhas if bruta.strip()
        )

    def enviar(self, **campos) -> None:
        self._sock.sendall((json.dumps(campos, ensure_ascii=False) + "\n").encode("utf-8"))

    def fechar(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


@pytest.fixture
def servidor(tmp_path):
    srv = ServidorUI(
        tmp_path / "run" / "core.sock",
        retrato=lambda: [
            envelope("agenda", lambda: RELOGIO, dia="2026-09-29", ocorrencias=[])
        ],
        relogio=lambda: RELOGIO,
        intervalo_health_s=0.1,
    )
    srv.iniciar()
    yield srv
    srv.parar()


def test_socket_criado_com_permissao_600(tmp_path):
    srv = ServidorUI(tmp_path / "core.sock", retrato=lambda: [])
    srv.iniciar()
    try:
        modo = stat.S_IMODE(srv.caminho.stat().st_mode)
        assert modo == 0o600
        assert stat.S_IMODE(srv.caminho.parent.stat().st_mode) == 0o700
    finally:
        srv.parar()


def test_cliente_recebe_o_retrato_na_conexao(servidor):
    cliente = ClienteFake(servidor.caminho)
    try:
        assert cliente.receber("agenda")["dia"] == "2026-09-29"
    finally:
        cliente.fechar()


def test_publicacao_chega_na_ui(servidor):
    cliente = ClienteFake(servidor.caminho)
    try:
        cliente.receber("agenda")
        servidor.publicar(envelope("estado", lambda: RELOGIO, fase="ALARME", passo=1))
        msg = cliente.receber("estado")
        assert msg["fase"] == "ALARME"
        assert msg["passo"] == 1
    finally:
        cliente.fechar()


def test_heartbeat_periodico(servidor):
    cliente = ClienteFake(servidor.caminho)
    try:
        cliente.receber("agenda")
        assert cliente.receber("health", timeout=3.0)["type"] == "health"
    finally:
        cliente.fechar()


def test_entrada_da_ui_entra_na_fila(servidor):
    """A entrada não é executada no socket: fica na fila para o `tick`."""
    cliente = ClienteFake(servidor.caminho)
    try:
        cliente.receber("agenda")
        cliente.enviar(v=1, type="input", acao="confirma")
        for _ in range(100):
            if servidor.tem_entrada():
                break
            time.sleep(0.02)
        assert servidor.entradas() == [{"v": 1, "type": "input", "acao": "confirma"}]
        assert servidor.entradas() == []  # drena uma vez só
    finally:
        cliente.fechar()


def test_aguardar_proxima_desperta_com_entrada(servidor):
    cliente = ClienteFake(servidor.caminho)
    cliente.receber("agenda")
    servidor.aguardar_proxima(0.2)  # espera o retrato não deixar evento pendente
    inicio = time.monotonic()
    cliente.enviar(v=1, type="input", acao="confirma")
    servidor.aguardar_proxima(5.0)  # botão na tela: não espera o tick inteiro
    cliente.fechar()
    assert time.monotonic() - inicio < 2.0


def test_mensagem_invalida_da_ui_vira_alerta(servidor):
    cliente = ClienteFake(servidor.caminho)
    try:
        cliente.receber("agenda")
        cliente._sock.sendall(b"isso nao e json\n")
        alerta = cliente.receber("alerta")
        assert alerta["codigo"] == "F005"
        assert servidor.entradas() == []  # nada executável entrou na fila
    finally:
        cliente.fechar()


def test_tipo_desconhecido_da_ui_vira_alerta(servidor):
    cliente = ClienteFake(servidor.caminho)
    try:
        cliente.receber("agenda")
        cliente.enviar(v=1, type="apagar_tudo")
        assert cliente.receber("alerta")["codigo"] == "F005"
        assert servidor.entradas() == []
    finally:
        cliente.fechar()


def test_ui_reconecta_e_recebe_retrato_de_novo(servidor):
    primeira = ClienteFake(servidor.caminho)
    primeira.receber("agenda")
    primeira.fechar()
    for _ in range(50):
        if not servidor.conectado():
            break
        time.sleep(0.02)
    segunda = ClienteFake(servidor.caminho)
    try:
        assert segunda.receber("agenda")["dia"] == "2026-09-29"
        assert servidor.conectado()
    finally:
        segunda.fechar()


def test_parar_remove_o_socket(tmp_path):
    srv = ServidorUI(tmp_path / "core.sock", retrato=lambda: [])
    srv.iniciar()
    caminho = srv.caminho
    srv.parar()
    assert not caminho.exists()


def test_socket_orfao_e_removido_no_inicio(tmp_path):
    caminho = tmp_path / "core.sock"
    caminho.write_bytes(b"")  # arquivo antigo, sem processo escutando
    srv = ServidorUI(caminho, retrato=lambda: [])
    srv.iniciar()
    try:
        cliente = ClienteFake(caminho)
        cliente.fechar()
    finally:
        srv.parar()


def test_iniciar_falha_se_ja_existe_ui_conectada(tmp_path):
    caminho = tmp_path / "core.sock"
    primeiro = ServidorUI(caminho, retrato=lambda: [])
    primeiro.iniciar()
    cliente = ClienteFake(caminho)
    segundo = ServidorUI(caminho, retrato=lambda: [])
    try:
        with pytest.raises(RuntimeError):
            segundo.iniciar()
    finally:
        cliente.fechar()
        primeiro.parar()


def test_publicar_sem_nenhum_cliente_nao_quebra(servidor):
    servidor.publicar(envelope("alerta", lambda: RELOGIO, codigo="F004"))
    servidor.parar()
