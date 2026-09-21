"""Sync com o backend do app (Firestore): polling + fila outbox.

Estratégia (ADR 005): polling da agenda a cada ~15s; eventos de adesão
enfileirados em SQLite com idempotência por chave. O transporte real
(Firestore, Fase 3) fornece a agenda e registra `dose_tomada`; aqui ficam
a fila, a fonte local da agenda (cache) e a orquestração do ciclo.
"""

from __future__ import annotations

import json

from core.armazenamento import Database
from core.transporte import Transporte, registro_historico


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


class FonteAgendaLocal:
    """Fonte de agenda que lê o cache sincronizado do backend (Fase 3)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def agenda(self) -> list[dict]:
        return self._db.agenda_cached()


class Sincronizador:
    """Orquestra um ciclo de sync: atualizar agenda + despachar a fila."""

    _TIPOS_ENVIADOS = ("dose_tomada",)

    def __init__(
        self,
        db: Database,
        transporte: Transporte,
        sync_service: SyncService | None = None,
    ) -> None:
        self._db = db
        self._transporte = transporte
        self._sync = sync_service or SyncService(db)

    def atualizar_agenda(self) -> bool:
        """Lê os medicamentos do backend e substitui o cache local."""
        try:
            medicamentos = self._transporte.ler_medicamentos()
        except Exception:
            return False
        self._db.substituir_agenda(medicamentos)
        return True

    def enviar_pendentes(self) -> int:
        """Despacha a fila; só tipos desta fase saem; falha mantém pendente."""
        enviados = 0
        for item in self._sync.pendentes():
            if item["tipo"] not in self._TIPOS_ENVIADOS:
                continue
            try:
                if self._enviar_tomada(item):
                    self._sync.marca_enviado(item["id"])
                    enviados += 1
            except Exception:
                continue
        return enviados

    def _enviar_tomada(self, item: dict) -> bool:
        ocorrencia = self._db.obter_ocorrencia(item["ocorrencia_id"])
        if ocorrencia is None:
            return False
        try:
            payload = json.loads(item["payload"])
        except ValueError:
            return False
        registro = registro_historico(ocorrencia, payload)
        if registro is None:
            return False
        return self._transporte.gravar_historico(item["ocorrencia_id"], registro)

    def ciclo(self) -> dict:
        """Um ciclo completo de sincronização (agenda + eventos)."""
        return {
            "agenda": self.atualizar_agenda(),
            "enviados": self.enviar_pendentes(),
        }