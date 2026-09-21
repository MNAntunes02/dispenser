"""Armazenamento local (SQLite): ocorrências, fila outbox e trilha de eventos.

Fase 2 define o schema e as operações. Logs NUNCA contêm nomes de
medicamento (LGPD); a trilha registra apenas tipos de evento + ocorrência.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.agendador import Ocorrencia

_ESTADOS_ATIVOS = (
    "ALARME",
    "AGUARDANDO_GAVETA",
    "GAVETA_ABERTA",
    "MEDICAMENTO_RETIRADO",
    "AGUARDANDO_RETORNO",
    "RETORNO_PENDENTE",
    "FALHA",
)


class Database:
    """Interface do banco SQLite local do dispensador."""

    def __init__(
        self,
        caminho: Path | str,
        relogio: Callable[[], datetime] | None = None,
    ) -> None:
        self._caminho = Path(caminho)
        self._conn: sqlite3.Connection | None = None
        self._relogio = relogio or datetime.now

    def conectar(self) -> None:
        if self._conn is not None:
            return
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._caminho)
        self._conn.row_factory = sqlite3.Row
        self.criar_schema()

    def fechar(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conexao(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("banco não está conectado")
        return self._conn

    def _agora(self) -> str:
        return self._relogio().isoformat(timespec="seconds")

    def criar_schema(self) -> None:
        self.conexao.executescript(
            """
            CREATE TABLE IF NOT EXISTS ocorrencias (
                id TEXT PRIMARY KEY,
                medicamento TEXT NOT NULL,
                medicamento_nome TEXT NOT NULL DEFAULT '',
                dosagem TEXT NOT NULL DEFAULT '',
                slot INTEGER,
                dia TEXT NOT NULL,
                horario TEXT NOT NULL,
                estado TEXT NOT NULL,
                tentativas INTEGER NOT NULL DEFAULT 0,
                notificado INTEGER NOT NULL DEFAULT 0,
                atualizado_em TEXT
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chave TEXT NOT NULL UNIQUE,
                ocorrencia_id TEXT NOT NULL,
                tipo TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                criado_em TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pendente',
                enviado_em TEXT
            );
            CREATE TABLE IF NOT EXISTS log_eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                em TEXT NOT NULL,
                tipo TEXT NOT NULL,
                ocorrencia_id TEXT,
                detalhe TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS agenda_cache (
                medicamento_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                atualizado_em TEXT NOT NULL
            );
            """
        )

    # --- ocorrências -------------------------------------------------------

    def inserir_ocorrencia_se_nova(self, occ: Ocorrencia) -> None:
        """Insere a ocorrência do dia sem sobrescrever estado de uma ativa."""
        self.conexao.execute(
            """
            INSERT OR IGNORE INTO ocorrencias
                (id, medicamento, medicamento_nome, dosagem, slot, dia, horario,
                 estado, tentativas, notificado, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'AGUARDANDO', 0, 0, NULL)
            """,
            (
                occ.id,
                occ.medicamento,
                occ.medicamento_nome,
                occ.dosagem,
                occ.slot,
                occ.dia,
                occ.horario,
            ),
        )
        self.conexao.commit()

    def obter_ocorrencia(self, ocorrencia_id: str) -> dict | None:
        linha = self.conexao.execute(
            "SELECT * FROM ocorrencias WHERE id = ?", (ocorrencia_id,)
        ).fetchone()
        return dict(linha) if linha else None

    def ocorrencia_ativa(self) -> dict | None:
        marcadores = ",".join("?" for _ in _ESTADOS_ATIVOS)
        linha = self.conexao.execute(
            f"SELECT * FROM ocorrencias WHERE estado IN ({marcadores}) ORDER BY horario LIMIT 1",
            _ESTADOS_ATIVOS,
        ).fetchone()
        return dict(linha) if linha else None

    def proxima_ocorrencia_aguardando(self, dia: str | None = None) -> dict | None:
        if dia is None:
            linha = self.conexao.execute(
                """
                SELECT * FROM ocorrencias
                WHERE estado = 'AGUARDANDO'
                ORDER BY horario, medicamento
                LIMIT 1
                """
            ).fetchone()
        else:
            linha = self.conexao.execute(
                """
                SELECT * FROM ocorrencias
                WHERE estado = 'AGUARDANDO' AND dia = ?
                ORDER BY horario, medicamento
                LIMIT 1
                """,
                (dia,),
            ).fetchone()
        return dict(linha) if linha else None

    def proximas_ocorrencias_aguardando(self, dia: str) -> list[dict]:
        linhas = self.conexao.execute(
            """
            SELECT * FROM ocorrencias
            WHERE estado = 'AGUARDANDO' AND dia = ?
            ORDER BY horario, medicamento
            """,
            (dia,),
        ).fetchall()
        return [dict(l) for l in linhas]

    def atualizar_ocorrencia(
        self,
        ocorrencia_id: str,
        *,
        estado: str | None = None,
        tentativas: int | None = None,
        notificado: int | None = None,
    ) -> None:
        campos: list[str] = ["atualizado_em = ?"]
        valores: list[object] = [self._agora()]
        if estado is not None:
            campos.append("estado = ?")
            valores.append(estado)
        if tentativas is not None:
            campos.append("tentativas = ?")
            valores.append(tentativas)
        if notificado is not None:
            campos.append("notificado = ?")
            valores.append(notificado)
        valores.append(ocorrencia_id)
        self.conexao.execute(
            f"UPDATE ocorrencias SET {', '.join(campos)} WHERE id = ?", valores
        )
        self.conexao.commit()

    # --- trilha de eventos -------------------------------------------------

    def registrar_log(
        self, tipo: str, ocorrencia_id: str | None = None, detalhe: str = ""
    ) -> None:
        self.conexao.execute(
            "INSERT INTO log_eventos (em, tipo, ocorrencia_id, detalhe) VALUES (?, ?, ?, ?)",
            (self._agora(), tipo, ocorrencia_id, detalhe),
        )
        self.conexao.commit()

    def ultimos_logs(self, limite: int = 50) -> list[dict]:
        linhas = self.conexao.execute(
            "SELECT * FROM log_eventos ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        return [dict(l) for l in linhas]

    # --- outbox ------------------------------------------------------------

    def enfileirar_outbox(
        self, chave: str, ocorrencia_id: str, tipo: str, payload: dict
    ) -> None:
        self.conexao.execute(
            """
            INSERT OR IGNORE INTO outbox
                (chave, ocorrencia_id, tipo, payload, criado_em)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chave, ocorrencia_id, tipo, json.dumps(payload, ensure_ascii=False), self._agora()),
        )
        self.conexao.commit()

    def outbox_pendentes(self) -> list[dict]:
        linhas = self.conexao.execute(
            "SELECT * FROM outbox WHERE status = 'pendente' ORDER BY id"
        ).fetchall()
        return [dict(l) for l in linhas]

    def marcar_outbox_enviado(self, outbox_id: int) -> None:
        self.conexao.execute(
            "UPDATE outbox SET status = 'enviado', enviado_em = ? WHERE id = ?",
            (self._agora(), outbox_id),
        )
        self.conexao.commit()

    def contar_outbox_pendentes(self) -> int:
        linha = self.conexao.execute(
            "SELECT COUNT(*) AS n FROM outbox WHERE status = 'pendente'"
        ).fetchone()
        return int(linha["n"])

    # --- agenda cache (sincronizada com o backend, Fase 3) -----------------

    def substituir_agenda(self, medicamentos: list[dict]) -> None:
        """Substitui a agenda em cache pelos medicamentos do backend."""
        conn = self.conexao
        agora = self._agora()
        linhas = [
            (str(med.get("id", "")), json.dumps(med, ensure_ascii=False), agora)
            for med in medicamentos
        ]
        with conn:
            conn.execute("DELETE FROM agenda_cache")
            conn.executemany(
                """
                INSERT INTO agenda_cache (medicamento_id, payload, atualizado_em)
                VALUES (?, ?, ?)
                """,
                linhas,
            )

    def agenda_cached(self) -> list[dict]:
        """Lê a agenda sincronizada em cache, na ordem em que foi gravada."""
        linhas = self.conexao.execute(
            "SELECT payload FROM agenda_cache ORDER BY rowid"
        ).fetchall()
        return [json.loads(l["payload"]) for l in linhas]