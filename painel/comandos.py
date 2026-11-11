"""Comandos que o painel envia ao core pelo socket da UI (ADR 003/015).

O painel fala o mesmo protocolo da UI Flutter e usa o mesmo socket
(`.run/core.sock`): um cliente *one-shot* por clique, em thread própria para
nunca travar o mainloop do Tkinter. O envio faz meia-fechadura e drena a
resposta (retrato/health), que é descartada — o painel não é UI. Reconexão
deliberadamente não existe: se o core reiniciar, o próximo clique abre outra
conexão. Falhas viram linha de log na aba do core, pela fila de eventos que
a thread principal do Tkinter drena.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Callable

from core.protocolo_ui import codificar, comando_simular
from painel.textos import texto

#: Conectar/enviar/fechar tem que ser rápido: o painel nunca deixa a janela
#: esperando por um socket lento (e o clique seguinte cria outra conexão).
_TIMEOUT_S = 2.0

#: Callback do painel: (fluxo, mensagem) — mesmo formato da fila de eventos.
AoLogar = Callable[[str, str], None]


class ComandosCore:
    """Envio pontual de comandos ao `dispenser-core` pelo Unix socket."""

    def __init__(self, caminho: Path | str, ao_logar: AoLogar) -> None:
        self._caminho = Path(caminho)
        self._ao_logar = ao_logar

    @property
    def caminho(self) -> Path:
        """Socket onde o core de desenvolvimento escuta."""
        return self._caminho

    def simular(self, evento: str, slot: int | None = None) -> None:
        """Envia o comando `simular` (evento de sensor) sem bloquear a janela.

        A resposta do core — tela nova, aviso ou recusa — aparece nos logs
        da aba do core, não como retorno aqui.
        """
        msg = comando_simular(evento, slot)
        threading.Thread(
            target=self._enviar,
            args=(msg,),
            name=f"painel-simular:{evento}",
            daemon=True,
        ).start()

    def _enviar(self, msg: dict) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(_TIMEOUT_S)
        try:
            sock.connect(str(self._caminho))
            sock.sendall(codificar(msg).encode("utf-8"))
            # Meia-fechadura (fim do nosso envio) e drenagem do que vier: o
            # servidor lê o comando até o EOF limpo e não sofre ECONNRESET
            # por resposta (retrato/health) que ninguém leu. A resposta em
            # si é descartada — o painel não é UI.
            sock.shutdown(socket.SHUT_WR)
            fim = time.monotonic() + _TIMEOUT_S
            while time.monotonic() < fim:
                try:
                    if not sock.recv(4096):
                        break
                except OSError:
                    break
        except OSError as erro:
            # Core parado ou socket sumindo no meio: o painel segue de pé.
            self._ao_logar("erro", texto("erro_simular", erro=erro))
        finally:
            try:
                sock.close()
            except OSError:
                pass
