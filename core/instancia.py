"""Instância única do `dispenser-core` (Fase 7, ADR 011).

Dois cores no mesmo `/var/lib/dispenser/state.db` seria pior que não ter core:
os dois agendadores disparariam alarmes fora de hora e brigariam pelo SQLite.
O lock é de arquivo (`flock`) e fica em `/run` (tmpfs), então some sozinho no
boot e não gasta escrita do cartão SD.

`flock` é do kernel: se o processo morrer — inclusive por `SIGKILL` de queda de
energia — o lock é liberado, e o core novo assume sem intervenção.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

#: Caminho padrão: `/run` é tmpfs no systemd, então o arquivo não é persistido.
CAMINHO_PADRAO = Path("/run/dispenser/core.lock")


class JaExisteInstancia(RuntimeError):
    """Outro `dispenser-core` já está de pé com este banco."""


class TravaDeInstancia:
    """Lock exclusivo do processo, com o PID escrito dentro do arquivo.

    O arquivo fica aberto durante toda a vida do core; `liberar()` fecha (o
    `flock` cai junto) e pode ser chamada duas vezes sem efeito.
    """

    def __init__(self, caminho: Path | str | None = None) -> None:
        self._caminho = Path(caminho or CAMINHO_PADRAO)
        self._arquivo = None

    @property
    def caminho(self) -> Path:
        return self._caminho

    def adquirir(self) -> "TravaDeInstancia":
        """Toma o lock ou levanta `JaExisteInstancia`."""
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = open(self._caminho, "a+", encoding="utf-8")
        try:
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as erro:
            arquivo.close()
            raise JaExisteInstancia(
                f"outro dispenser-core já está rodando ({self._caminho})"
            ) from erro
        arquivo.seek(0)
        arquivo.truncate()
        arquivo.write(f"{os.getpid()}\n")
        arquivo.flush()
        self._arquivo = arquivo
        return self

    def liberar(self) -> None:
        arquivo, self._arquivo = self._arquivo, None
        if arquivo is None:
            return
        try:
            fcntl.flock(arquivo.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            arquivo.close()
        except OSError:
            pass

    def __enter__(self) -> "TravaDeInstancia":
        return self.adquirir()

    def __exit__(self, *_excecao: object) -> None:
        self.liberar()
