"""Processos de desenvolvimento iniciados pelo painel.

Cada `Servico` é dono de um processo filho (core ou UI). O painel não usa
systemd nem shell: o comando é uma lista fixa, o processo roda em sessão própria
(para que parar atinja também os filhos do Flutter) e os logs saem por uma fila
consumida pela thread do Tkinter.

Estados:
    PARADO -> INICIANDO -> RODANDO -> PARANDO -> PARADO
                                   `-> ENCERRADO (queda sem parada solicitada)
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Sequence

from painel.log_buffer import limpar_ansi
from painel.textos import texto

#: Eventos entregues ao Tkinter:
#:   ("log", servico, fluxo, texto)
#:   ("estado", servico)
Evento = tuple[object, ...]


class EstadoServico(str, Enum):
    PARADO = "parado"
    INICIANDO = "iniciando"
    RODANDO = "rodando"
    PARANDO = "parando"
    ENCERRADO = "encerrado"


class JaRodando(RuntimeError):
    """Tentativa de iniciar um serviço que já tem processo vivo."""


class FalhaAoIniciar(RuntimeError):
    """O processo não pôde ser criado (comando ausente, permissão etc.)."""


class Servico:
    """Processo filho controlado pelo painel e observável pela janela."""

    def __init__(
        self,
        nome: str,
        comando: Sequence[str],
        cwd: Path | str,
        ambiente: Mapping[str, str],
        ao_evento: Callable[[Evento], None],
        *,
        intervalo_timeout_s: float = 10.0,
    ) -> None:
        self.nome = nome
        self.comando = list(comando)
        self.cwd = Path(cwd)
        self.ambiente = dict(ambiente)
        self.intervalo_timeout_s = intervalo_timeout_s
        self._ao_evento = ao_evento
        self._lock = threading.RLock()
        self._processo: subprocess.Popen[str] | None = None
        self._pid: int | None = None
        self._codigo: int | None = None
        self._erro: str | None = None
        self._estado = EstadoServico.PARADO
        self._parada_solicitada = False

    # --- leitura de estado -------------------------------------------------

    @property
    def estado(self) -> EstadoServico:
        with self._lock:
            return self._estado

    @property
    def pid(self) -> int | None:
        with self._lock:
            return self._pid

    @property
    def codigo_saida(self) -> int | None:
        with self._lock:
            return self._codigo

    @property
    def erro(self) -> str | None:
        with self._lock:
            return self._erro

    @property
    def ativo(self) -> bool:
        with self._lock:
            processo = self._processo
            return processo is not None and processo.poll() is None

    # --- eventos -----------------------------------------------------------

    def _emitir(self, *evento: object) -> None:
        try:
            self._ao_evento(evento)
        except Exception:
            # Um callback da UI nunca pode derrubar a thread de leitura.
            pass

    # --- ciclo de vida -----------------------------------------------------

    def iniciar(self) -> None:
        """Cria o processo e começa a drenar stdout/stderr."""
        with self._lock:
            processo = self._processo
            if processo is not None and processo.poll() is None:
                raise JaRodando(
                    texto(
                        "ja_rodando",
                        servico=self.nome,
                        pid=processo.pid,
                    )
                )
            self._parada_solicitada = False
            self._codigo = None
            self._erro = None
            self._estado = EstadoServico.INICIANDO
        self._emitir("estado", self.nome)

        try:
            processo = subprocess.Popen(
                self.comando,
                cwd=str(self.cwd),
                env=dict(self.ambiente),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )
        except OSError as erro:
            with self._lock:
                self._processo = None
                self._pid = None
                self._estado = EstadoServico.ENCERRADO
                self._codigo = None
                self._erro = str(erro)
            self._emitir("estado", self.nome)
            self._emitir(
                "log",
                self.nome,
                "erro",
                texto("falha_iniciar", erro=erro),
            )
            raise FalhaAoIniciar(str(erro)) from erro

        with self._lock:
            self._processo = processo
            self._pid = processo.pid
            self._estado = EstadoServico.RODANDO
        self._emitir("estado", self.nome)
        self._emitir(
            "log",
            self.nome,
            "painel",
            texto("processo_iniciado", pid=processo.pid),
        )

        self._iniciar_thread(
            self._ler,
            processo.stdout,
            "saida",
            nome=f"{self.nome}-stdout",
        )
        self._iniciar_thread(
            self._ler,
            processo.stderr,
            "erro",
            nome=f"{self.nome}-stderr",
        )
        self._iniciar_thread(
            self._monitorar,
            processo,
            nome=f"{self.nome}-monitor",
        )

    def _iniciar_thread(self, alvo: Callable[..., None], *args: object, nome: str) -> None:
        thread = threading.Thread(
            target=alvo,
            args=args,
            name=nome,
            daemon=True,
        )
        thread.start()

    def _ler(self, fluxo: object, tipo: str) -> None:
        """Lê uma saída do processo até EOF, sem tocar em Tkinter."""
        if fluxo is None:
            return
        try:
            for linha in iter(fluxo.readline, ""):  # type: ignore[attr-defined]
                self._emitir(
                    "log",
                    self.nome,
                    tipo,
                    limpar_ansi(linha.rstrip("\r\n")),
                )
        except (OSError, ValueError):
            pass
        finally:
            try:
                fluxo.close()  # type: ignore[attr-defined]
            except OSError:
                pass

    def _monitorar(self, processo: subprocess.Popen[str]) -> None:
        try:
            codigo = processo.wait()
        except Exception:
            codigo = -1
        self._finalizar(processo, codigo)

    def _finalizar(self, processo: subprocess.Popen[str], codigo: int) -> None:
        """Consolida o fim do processo uma única vez, mesmo com dois waits."""
        with self._lock:
            if self._processo is not processo:
                return
            parada = self._parada_solicitada
            self._processo = None
            self._pid = None
            self._codigo = codigo
            self._erro = None
            self._estado = (
                EstadoServico.PARADO if parada else EstadoServico.ENCERRADO
            )
        self._emitir("estado", self.nome)
        if parada:
            self._emitir("log", self.nome, "painel", texto("processo_parado"))
        else:
            self._emitir(
                "log",
                self.nome,
                "painel",
                texto("processo_encerrado", codigo=codigo),
            )

    def parar_sincrono(self, timeout_s: float | None = None) -> None:
        """Pede SIGTERM ao grupo e escala para SIGKILL se não morrer a tempo.

        É síncrono para a janela poder esperar no fechamento. Ao clicar em
        Parar/Reiniciar, a UI chama este método numa thread para não congelar.
        """
        timeout = (
            self.intervalo_timeout_s if timeout_s is None else max(0.0, timeout_s)
        )
        with self._lock:
            processo = self._processo
            if processo is None:
                return
            if processo.poll() is not None:
                codigo = processo.returncode
                self._parada_solicitada = True
                # RLock: `_finalizar` pode reentrar nesta mesma thread.
                self._finalizar(processo, codigo if codigo is not None else -1)
                return
            self._parada_solicitada = True
            self._estado = EstadoServico.PARANDO
        self._emitir("estado", self.nome)
        self._emitir("log", self.nome, "painel", texto("processo_parando"))

        self._sinalizar(processo, signal.SIGTERM)
        try:
            processo.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._emitir(
                "log",
                self.nome,
                "painel",
                texto("processo_escalando"),
            )
            self._sinalizar(processo, signal.SIGKILL)
            try:
                processo.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._emitir(
                    "log",
                    self.nome,
                    "erro",
                    texto("processo_teimoso"),
                )

        codigo = processo.returncode
        self._finalizar(processo, codigo if codigo is not None else -1)

    def reiniciar_sincrono(self, timeout_s: float | None = None) -> None:
        """Para e sobe de novo; usado pela UI numa thread separada."""
        self.parar_sincrono(timeout_s)
        self.iniciar()

    def _sinalizar(self, processo: subprocess.Popen[str], sinal: int) -> None:
        """Manda o sinal para o grupo inteiro (Flutter cria subprocessos)."""
        try:
            os.killpg(os.getpgid(processo.pid), sinal)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            processo.send_signal(sinal)
        except (ProcessLookupError, OSError):
            pass

    def __repr__(self) -> str:  # pragma: no cover - conveniência de debug
        return (
            f"Servico({self.nome!r}, estado={self.estado.value!r}, "
            f"pid={self.pid!r})"
        )
