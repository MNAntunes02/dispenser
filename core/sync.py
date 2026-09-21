"""Sync com o backend do app (Firestore): polling + fila outbox.

Estratégia (ADR 005): polling da agenda a cada ~15s; eventos de adesão
enfileirados em SQLite com idempotência por chave. O transporte real
(Firestore) entra na Fase 3; aqui ficam fila, reenvio e idempotência.
"""

from __future__ import annotations

from core.armazenamento import Database


class SyncService:
    """Enfileira os eventos de adesão e expõe a fila pendente."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def enfileirar_evento(self, ocorrencia_id: str, tipo: str, payload: dict) -> None:
        chave = f"{ocorrencia_id}|{tipo}"
        self._db.enfileirar_outbox(chave, ocorrencia_id, tipo, payload)

    def pendentes(self) -> list[dict]:
        return self._db.outbox_pendentes()

    def marca_enviado(self, outbox_id: int) -> None:
        self._db.marcar_outbox_enviado(outbox_id)

    def envia_emitidos(self, envio: callable) -> int:
        """Tenta enviar a fila; `envio(outbox_item) -> bool` por item."""
        enviados = 0
        for item in self.pendentes():
            try:
                if envio(item):
                    self.marca_enviado(item["id"])
                    enviados += 1
            except Exception:
                continue
        return enviados