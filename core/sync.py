"""Sync com o backend do app (Firestore): polling + fila outbox.

Estratégia (ADR 005): polling da agenda a cada ~15s; eventos de adesão
enfileirados em SQLite com retry/backoff e idempotência. Credencial
própria e ajuste de regras Firestore: Fase 3.
"""

from __future__ import annotations

SYNC_INTERVAL_S = 15


class SyncService:
    """Busca a agenda e envia a fila de eventos."""

    def poll(self) -> None:
        raise NotImplementedError("Fase 3: ler agenda do backend e fila outbox")

    def enfileirar_evento(self, ocorrencia_id: str, tipo: str) -> None:
        raise NotImplementedError("Fase 2: persistir evento pendente")