"""Servidor do core para a UI (Unix socket + JSON, ADR 003).

Papel: point-to-point local, permissão 600, newline-delimited JSON. O
servidor implementa a mesma interface de publicação de `PublicadorLog`
(`publicar(msg)`), de modo que o coordenador não sabe se há UI conectada.

Garantias de projeto (importam para a segurança do paciente):
- **A UI não roda nada do core.** As mensagens recebidas entram numa fila
  que só o `tick()` drena; o socket nunca toca banco nem máquina de
  estados. O banco SQLite do core é usado por uma thread só.
- A UI pode reiniciar à vontade; ao reconectar recebe um retrato pronto
  (gerado pela thread do core, nunca calculado no socket) e volta a receber
  as publicações.
- Publicação nunca é bloqueada por UI lenta: uma UI que não consome é
  desconectada e volta pelo retrato — nenhuma mensagem de estado se perde,
  porque o estado chega inteiro no retrato.
- O chamador do loop principal usa `aguardar_proxima()` para dormir: um
  botão pressionado na tela acorda o core na hora.
"""

from __future__ import annotations

import errno
import select
import socket
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable, Deque

from core.protocolo_ui import TIPOS_DA_UI, ProtocoloInvalido, codificar, decodificar, envelope

_ERROS_DESCONEXAO = {errno.ECONNRESET, errno.EPIPE, errno.EBADF, errno.ENOTCONN}


class _Cliente:
    __slots__ = ("sock", "fila", "vivo")

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.fila: Deque[str] = deque()
        self.vivo = True


class ServidorUI:
    """Escuta a UI em um Unix socket, publica e enfileira a entrada dela."""

    def __init__(
        self,
        caminho: Path | str,
        *,
        retrato: Callable[[], list[dict]] | None = None,
        relogio: Callable[[], datetime] | None = None,
        intervalo_health_s: float = 2.0,
        max_clientes: int = 4,
        max_fila: int = 200,
    ) -> None:
        self._caminho = Path(caminho)
        self._retrato = retrato
        self._relogio = relogio or datetime.now
        self._intervalo_health = intervalo_health_s
        self._max_clientes = max_clientes
        self._max_fila = max_fila
        self._cond = threading.Condition(threading.RLock())
        self._clientes: list[_Cliente] = []
        self._entradas: Deque[dict] = deque()
        self._evento = threading.Event()
        self._parar_health = threading.Event()
        self._ouvinte: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._thread_health: threading.Thread | None = None
        self._parando = False

    # --- ciclo de vida -----------------------------------------------------

    @property
    def caminho(self) -> Path:
        return self._caminho

    def iniciar(self) -> None:
        """Cria o socket (600) e sobe as threads de aceite e health."""
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._caminho.parent.chmod(0o700)
        except OSError:
            pass
        self._remover_socket_orfao()
        ouvinte = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        ouvinte.bind(str(self._caminho))
        self._caminho.chmod(0o600)
        ouvinte.listen(self._max_clientes)
        ouvinte.settimeout(0.5)
        self._ouvinte = ouvinte
        self._parando = False
        self._thread = threading.Thread(
            target=self._loop_aceite, name="ui-aceite", daemon=True
        )
        self._thread.start()
        self._thread_health = threading.Thread(
            target=self._loop_health, name="ui-health", daemon=True
        )
        self._thread_health.start()

    def parar(self) -> None:
        """Encerra o servidor, fecha clientes e remove o arquivo de socket."""
        with self._cond:
            self._parando = True
            clientes = list(self._clientes)
            self._clientes.clear()
            self._cond.notify_all()
        self._parar_health.set()
        for cliente in clientes:
            self._fechar(cliente)
        if self._ouvinte is not None:
            try:
                self._ouvinte.close()
            except OSError:
                pass
            self._ouvinte = None
        for thread in (self._thread, self._thread_health):
            if thread is not None:
                thread.join(timeout=2.0)
        try:
            self._caminho.unlink()
        except OSError:
            pass

    def conectado(self) -> bool:
        with self._cond:
            return bool(self._clientes)

    def aguardar_proxima(self, timeout: float) -> None:
        """Dorme até chegar mensagem da UI ou passar `timeout` (segundos)."""
        self._evento.wait(timeout)
        self._evento.clear()

    # --- publicação --------------------------------------------------------

    def publicar(self, msg: dict) -> None:
        """Enfileira a mensagem para todas as UIs conectadas."""
        linha = codificar(msg)
        with self._cond:
            if self._parando:
                return
            for cliente in list(self._clientes):
                if len(cliente.fila) >= self._max_fila:
                    # UI travada/lenta: derruba para que ela volte pelo retrato.
                    cliente.vivo = False
                    self._fechar(cliente)
                    continue
                cliente.fila.append(linha)
            self._cond.notify_all()

    def publicar_health(self) -> None:
        self.publicar(envelope("health", self._relogio))

    # --- entrada da UI (consumida pelo `tick` do core) ----------------------

    def entradas(self) -> list[dict]:
        """Retira da fila as mensagens recebidas da UI desde a última leitura."""
        with self._cond:
            if not self._entradas:
                return []
            mensagens = list(self._entradas)
            self._entradas.clear()
            return mensagens

    def tem_entrada(self) -> bool:
        """Há entrada esperando? Não consome a fila (checagem de espera)."""
        with self._cond:
            return bool(self._entradas)

    def _enfileirar_entrada(self, msg: dict) -> None:
        with self._cond:
            self._entradas.append(msg)
        self._evento.set()

    # --- threads -----------------------------------------------------------

    def _loop_health(self) -> None:
        # Evento próprio: publicar telas não pode apressar o heartbeat, senão
        # uma tela que muda muito vira uma rajada de `health` na UI.
        while not self._parando:
            if self._parar_health.wait(timeout=self._intervalo_health):
                return
            self.publicar_health()

    def _loop_aceite(self) -> None:
        while not self._parando:
            ouvinte = self._ouvinte
            if ouvinte is None:
                return
            try:
                sock, _ = ouvinte.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            # Retrato pego antes de registrar: garante que o estado do retrato
            # chegue antes das publicações seguintes.
            retrato: list[dict] = []
            if self._retrato is not None:
                try:
                    retrato = list(self._retrato())
                except Exception:  # noqa: BLE001 - retrato nunca derruba o core
                    retrato = []
            with self._cond:
                if self._parando:
                    sock.close()
                    return
                if len(self._clientes) >= self._max_clientes:
                    sock.close()
                    continue
                cliente = _Cliente(sock)
                for msg in retrato:
                    cliente.fila.append(codificar(msg))
                self._clientes.append(cliente)
            threading.Thread(
                target=self._loop_cliente, args=(cliente,), name="ui-cliente", daemon=True
            ).start()

    def _loop_cliente(self, cliente: _Cliente) -> None:
        buffer = b""
        try:
            while cliente.vivo and not self._parando:
                with self._cond:
                    while not cliente.fila and cliente.vivo and not self._parando:
                        self._cond.wait(timeout=0.2)
                    if not cliente.vivo or self._parando:
                        break
                    lote = b"".join(
                        bytes(cliente.fila[j], "utf-8") for j in range(len(cliente.fila))
                    )
                    cliente.fila.clear()
                try:
                    if lote:
                        cliente.sock.sendall(lote)
                except OSError as erro:
                    if erro.errno not in _ERROS_DESCONEXAO:
                        raise
                    break
                pedaco = self._ler_cliente(cliente)
                if pedaco is None:
                    continue
                if not pedaco:
                    break  # a UI fechou a conexão
                buffer, linhas = self._extrair(buffer + pedaco)
                for linha in linhas:
                    self._tratar(linha)
        finally:
            cliente.vivo = False
            with self._cond:
                if cliente in self._clientes:
                    self._clientes.remove(cliente)
            self._fechar(cliente)

    def _ler_cliente(self, cliente: _Cliente) -> bytes | None:
        """Lê o que já chegou do cliente sem bloquear.

        `None` = nada recebido agora; `b""` = a UI fechou a conexão (ou o
        servidor está encerrando e fechou o socket por baixo).
        """
        try:
            pronto, _, _ = select.select([cliente.sock], [], [], 0)
        except (OSError, ValueError):
            return b""
        if not pronto:
            return None
        try:
            return cliente.sock.recv(4096)
        except OSError as erro:
            if erro.errno in _ERROS_DESCONEXAO:
                return b""
            raise

    def _extrair(self, buffer: bytes) -> tuple[bytes, list[str]]:
        partes = buffer.split(b"\n")
        buffer = partes.pop()
        linhas = [p.decode("utf-8", "replace") for p in partes if p.strip()]
        return buffer, linhas

    def _tratar(self, linha: str) -> None:
        try:
            msg = decodificar(linha, tipos=TIPOS_DA_UI)
        except ProtocoloInvalido as erro:
            self.publicar(
                envelope(
                    "alerta",
                    self._relogio,
                    codigo="F005",
                    mensagem=f"Mensagem inválida da UI: {erro}",
                )
            )
            return
        self._enfileirar_entrada(msg)

    # --- socket ------------------------------------------------------------

    def _remover_socket_orfao(self) -> None:
        if not self._caminho.exists():
            return
        teste = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        teste.settimeout(0.5)
        try:
            teste.connect(str(self._caminho))
        except OSError:
            self._caminho.unlink(missing_ok=True)
            return
        finally:
            teste.close()
        raise RuntimeError(f"já existe uma UI conectada em {self._caminho}")

    def _fechar(self, cliente: _Cliente) -> None:
        cliente.vivo = False
        try:
            cliente.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            cliente.sock.close()
        except OSError:
            pass
