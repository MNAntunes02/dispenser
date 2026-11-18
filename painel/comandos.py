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

from core.protocolo_ui import (
    codificar,
    comando_confirmar_registro,
    comando_iniciar_registro,
    comando_liberar_proximo,
    comando_registrar_leitura,
    comando_registrar_manual,
    comando_simular,
)
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

    def iniciar_registro(
        self, medicamento: str = "", *, assincrono: bool = True
    ) -> bool:
        """Inicia a leitura da cartela (painel ou script)."""
        return self._enviar_ou_thread(
            comando_iniciar_registro(medicamento or None),
            "painel-iniciar-registro",
            assincrono,
        )

    def registrar_leitura(
        self, registro_id: str, quantidade: int, *, assincrono: bool = True
    ) -> bool:
        """Envia a contagem lida pela câmera (chamado pela UI/painel)."""
        return self._enviar_ou_thread(
            comando_registrar_leitura(registro_id, quantidade),
            "painel-registrar-leitura",
            assincrono,
        )

    def registrar_manual(
        self, registro_id: str, quantidade: int, *, assincrono: bool = True
    ) -> bool:
        """Fallback sem câmera: quantidade informada pelo operador."""
        return self._enviar_ou_thread(
            comando_registrar_manual(registro_id, quantidade),
            "painel-registrar-manual",
            assincrono,
        )

    def confirmar_registro(
        self, registro_id: str = "", *, assincrono: bool = True
    ) -> bool:
        """Confirma que a cartela foi colocada no slot indicado pelo core."""
        return self._enviar_ou_thread(
            comando_confirmar_registro(registro_id),
            "painel-confirmar-registro",
            assincrono,
        )

    def _enviar_ou_thread(self, msg: dict, nome: str, assincrono: bool) -> bool:
        if assincrono:
            threading.Thread(
                target=self._enviar,
                args=(msg,),
                name=nome,
                daemon=True,
            ).start()
            return True
        return self._enviar(msg)

    def liberar_proximo(self, *, assincrono: bool = True) -> bool:
        """Envia a liberação do passo de detecção (painel ou CLI).

        No painel o envio roda em thread (`assincrono=True`) para não travar o
        Tkinter. O CLI usa `assincrono=False` e recebe o resultado do envio.
        """
        msg = comando_liberar_proximo()
        if assincrono:
            threading.Thread(
                target=self._enviar,
                args=(msg,),
                name="painel-liberar-proximo",
                daemon=True,
            ).start()
            return True
        return self._enviar(msg)

    def _enviar(self, msg: dict) -> bool:
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
            return True
        except OSError as erro:
            # Core parado ou socket sumindo no meio: o painel segue de pé.
            self._ao_logar("erro", texto("erro_comando", erro=erro))
            return False
        finally:
            try:
                sock.close()
            except OSError:
                pass
