"""Armazenamento local (SQLite): ocorrências, fila outbox e trilha de eventos.

Fase 2 define o schema e as operações. Logs NUNCA contêm nomes de
medicamento (LGPD); a trilha registra apenas tipos de evento + ocorrência.

Fase 7 (ADR 013) cuida do cartão SD: WAL (uma escrita por transação em vez de
duas), `synchronous=NORMAL` (agrupa o fsync), `busy_timeout` e retenção da
trilha. A fila `outbox` **nunca** é purgada — é o que garante não perder evento
na falta de rede.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
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

#: Retenção padrão da trilha local (`log_eventos`).
RETENCAO_PADRAO_DIAS = 90


class Database:
    """Interface do banco SQLite local do dispensador."""

    def __init__(
        self,
        caminho: Path | str,
        relogio: Callable[[], datetime] | None = None,
        retencao_log_dias: int = RETENCAO_PADRAO_DIAS,
    ) -> None:
        self._caminho = Path(caminho)
        self._conn: sqlite3.Connection | None = None
        self._relogio = relogio or datetime.now
        self._retencao_log_dias = max(0, int(retencao_log_dias))
        self._ultima_purga: str | None = None

    def conectar(self) -> None:
        if self._conn is not None:
            return
        self._caminho.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._caminho, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        self._ajustar_para_cartao_sd()
        self.criar_schema()

    def _ajustar_para_cartao_sd(self) -> None:
        """PRAGMAs que importam no cartão SD (spec 04, ADR 013).

        - `journal_mode=WAL`: a transação escreve uma vez, em vez de criar e
          apagar um journal de rollback por commit;
        - `synchronous=NORMAL`: com WAL, perde-se no máximo a última transação
          numa queda de energia (o estado é reconstruído do próprio banco) e
          para de dar `fsync` a cada commit;
        - `busy_timeout`: duas tentativas de lock (ex.: diagnóstico lendo o
          banco) esperam em vez de falhar com "database is locked".
        """
        conexao = self.conexao
        conexao.execute("PRAGMA journal_mode=WAL")
        conexao.execute("PRAGMA synchronous=NORMAL")
        conexao.execute("PRAGMA busy_timeout=5000")
        conexao.execute("PRAGMA foreign_keys=ON")

    def fechar(self) -> None:
        """Fecha o banco consolidando o WAL (uma escrita, não várias)."""
        if self._conn is not None:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
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

    def inserir_ocorrencia_se_nova(self, occ: Ocorrencia) -> bool:
        """Insere a ocorrência do dia sem sobrescrever estado de uma ativa.

        Devolve `True` apenas quando a linha é nova (usado pela UI para
        saber se a agenda mudou).
        """
        cur = self.conexao.execute(
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
        return cur.rowcount > 0

    def ocorrencias_do_dia(self, dia: str) -> list[dict]:
        """Todas as ocorrências do dia, na ordem do fluxo (usado pela UI)."""
        linhas = self.conexao.execute(
            """
            SELECT * FROM ocorrencias
            WHERE dia = ?
            ORDER BY horario, medicamento
            """,
            (dia,),
        ).fetchall()
        return [dict(l) for l in linhas]

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

    def marcar_nao_atendida(self, ocorrencia_ids: list[str]) -> None:
        """Fecha várias ocorrências de uma vez (doses cujo horário passou).

        Um único `commit` para não espalhar escrita no cartão SD (spec 04).
        """
        if not ocorrencia_ids:
            return
        agora = self._agora()
        self.conexao.executemany(
            "UPDATE ocorrencias SET estado = 'NAO_ATENDIDA', atualizado_em = ? WHERE id = ?",
            [(agora, occ_id) for occ_id in ocorrencia_ids],
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

    def purgar_logs(self, forcar: bool = False) -> int:
        """Corta a trilha antiga para o banco não crescer sem teto no SD.

        Roda no máximo uma vez por dia (a data do último corte fica em memória,
        então reiniciar o core não repete a escrita) e só quando há o que
        apagar. A fila `outbox` não é tocada: evento pendente é evento que
        ainda não chegou ao cuidador.
        """
        if self._retencao_log_dias <= 0:
            return 0
        hoje = self._relogio().date().isoformat()
        if not forcar and self._ultima_purga == hoje:
            return 0
        self._ultima_purga = hoje
        corte = (self._relogio() - timedelta(days=self._retencao_log_dias)).isoformat(
            timespec="seconds"
        )
        cur = self.conexao.execute("DELETE FROM log_eventos WHERE em < ?", (corte,))
        self.conexao.commit()
        return int(cur.rowcount or 0)

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