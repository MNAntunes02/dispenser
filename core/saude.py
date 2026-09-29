"""Liveness do core para o systemd (Fase 7, ADR 011).

O systemd só sabe que um serviço está vivo se ele **dizer**. Com `Type=notify`
e `WatchdogSec`, o `dispenser-core` manda `WATCHDOG=1` periodicamente no socket
`NOTIFY_SOCKET`; se o aviso parar — loop travado na máquina de estados, disco
cheio, bloqueio em I/O — o systemd mata o processo e sobe outro.

Implementado com `AF_UNIX` direto, sem o pacote `systemd`: o core roda num venv
mínimo e o protocolo é um `sendto` de texto em datagram. Sem `NOTIFY_SOCKET`
(roda à mão, em teste ou no demo) tudo vira no-op silencioso — o watchdog é
infraestrutura, nunca uma dependência do fluxo da dose.
"""

from __future__ import annotations

import os
import socket
import time
from typing import Callable

#: Intervalo padrão entre pulsos. A unit usa `WatchdogSec=45`, ou seja, o
#: systemd tolera ~3 pulsos perdidos antes de matar o processo.
INTERVALO_PADRAO_S = 15.0

#: Tamanho de um datagram de notificação (systemd usa mensagens bem curtas).
_BUFFER = 4096


def caminho_notify(ambiente: dict[str, str] | None = None) -> str | None:
    """Endereço do `NOTIFY_SOCKET`, ou `None` se o systemd não está lá.

    O systemd usa `@caminho` para o namespace abstrato; no Linux o socket
    abstrato é o mesmo endereço com um byte NUL no lugar do `@`.
    """
    valor = (ambiente if ambiente is not None else os.environ).get("NOTIFY_SOCKET", "")
    return valor or None


def _endereco(valor: str) -> bytes:
    if valor.startswith("@"):
        return b"\0" + valor[1:].encode("utf-8")
    return valor.encode("utf-8")


def _mensagem(**campos: object) -> str:
    """Linha `KEY=value` como o sd_notify espera (sem quebra de linha)."""
    partes = []
    for chave, valor in campos.items():
        if valor is None:
            continue
        texto = str(valor).replace("\n", " ").strip()
        if texto:
            partes.append(f"{chave.upper()}={texto}")
    return "\n".join(partes)


class NotificadorSaude:
    """Envia `READY`/`WATCHDOG`/`STOPPING` para o systemd.

    Nunca levanta exceção: um watchdog quebrado não pode derrubar o core que
    guarda a dose do paciente. No máximo ele desliga a si mesmo e avisa uma
    vez, pelo callback `ao_falhar`.
    """

    def __init__(
        self,
        *,
        caminho: str | None = None,
        intervalo_s: float = INTERVALO_PADRAO_S,
        ao_falhar: Callable[[str], None] | None = None,
        ambiente: dict[str, str] | None = None,
    ) -> None:
        self._caminho = caminho or caminho_notify(ambiente)
        self._intervalo_s = float(intervalo_s)
        self._ao_falhar = ao_falhar
        self._socket: socket.socket | None = None
        self._ultimo_pulso = 0.0
        self._desligado = False
        self._avisou = False

    @property
    def ativo(self) -> bool:
        """O watchdog do systemd está em uso neste processo?"""
        return bool(self._caminho) and not self._desligado

    def _abrir(self) -> socket.socket | None:
        if self._socket is not None:
            return self._socket
        if not self._caminho:
            return None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
            sock.settimeout(1.0)
        except OSError as erro:
            self._desligar(f"socket: {erro}")
            return None
        self._socket = sock
        return sock

    def _desligar(self, motivo: str) -> None:
        self._desligado = True
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        if self._ao_falhar is not None and not self._avisou:
            self._avisou = True
            self._ao_falhar(motivo)

    def _enviar(self, **campos: object) -> bool:
        sock = self._abrir()
        if sock is None:
            return False
        try:
            sock.sendto(_mensagem(**campos).encode("utf-8"), _endereco(self._caminho or ""))
        except OSError as erro:
            # Sem listener (ou systemd recarregando): desliga e segue rodando.
            self._desligar(f"sendto: {erro}")
            return False
        return True

    def iniciar(self, status: str = "") -> bool:
        """`READY=1`: o core subiu e já pode ser considerado vivo."""
        self._ultimo_pulso = time.monotonic()
        return self._enviar(READY="1", STATUS=status or None, MAINPID=os.getpid())

    def pulso(self, status: str = "", forcar: bool = False) -> bool:
        """Manda `WATCHDOG=1` se já passou o intervalo. Devolve se enviou.

        Chame uma vez por volta do `tick`: é justamente quando o `tick` trava
        que o pulso para e o systemd reinicia o core.
        """
        agora = time.monotonic()
        if not forcar and (agora - self._ultimo_pulso) < self._intervalo_s:
            return False
        self._ultimo_pulso = agora
        return self._enviar(WATCHDOG="1", STATUS=status or None)

    def parar(self, status: str = "") -> bool:
        """`STOPPING=1`: o core está encerrando de boa (SIGTERM)."""
        return self._enviar(STOPPING="1", STATUS=status or None)

    def fechar(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        self._desligado = True
