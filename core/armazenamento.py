"""Armazenamento local (SQLite): cache da agenda e fila de eventos pendentes.

Fase 2 define o schema (tabelas de ocorrências, eventos outbox) e as
operações. Aqui fica apenas o esqueleto do ciclo de vida do banco.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Database:
    """Interface do banco SQLite local do dispensador."""

    def __init__(self, caminho: Path | str) -> None:
        self._caminho = Path(caminho)
        self._conn: sqlite3.Connection | None = None

    def conectar(self) -> None:
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._caminho)

    def fechar(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conexao(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("banco não está conectado")
        return self._conn