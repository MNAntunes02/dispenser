"""Sync com o backend do app (Firestore): polling + fila outbox.

Estratégia (ADR 005): polling da agenda a cada ~15s; eventos de adesão
enfileirados em SQLite com idempotência por chave. O transporte real
(Firestore, Fase 3) fornece a agenda, registra `dose_tomada` no `Historico` e
(a Fase 6, ADR 010) publica os avisos do cuidador em `Notificacoes`; aqui ficam
a fila, a fonte local da agenda (cache) e a orquestração do ciclo.
"""

from __future__ import annotations

import json

from core.armazenamento import Database
from core.transporte import Transporte, registro_historico, registro_notificacao


class SyncService:
    """Enfileira os eventos de adesão e expõe a fila pendente."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def enfileirar_evento(
        self,
        ocorrencia_id: str,
        tipo: str,
        payload: dict,
        *,
        chave: str | None = None,
    ) -> None:
        """Enfileira um evento. A chave `UNIQUE` garante um item só por
        ocorrência+tipo (idempotência); `chave` explícita é para eventos sem
        ocorrência (falha de sensor com ociosidade)."""
        self._db.enfileirar_outbox(
            chave or f"{ocorrencia_id}|{tipo}", ocorrencia_id, tipo, payload
        )

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

    #: Eventos que viram registro de adesão no `Historico` (o app só conhece
    #: dose tomada; dose perdida/nao devolvido/relogio vão para `Notificacoes`).
    _TIPOS_HISTORICO = ("dose_tomada",)
    #: Eventos que viram aviso para cuidador/app (ADR 010; `relogio` na Fase 7).
    _TIPOS_AVISO = ("dose_perdida", "retorno_pendente", "falha", "relogio")
    #: Avisos que descrevem o aparelho e por isso não têm ocorrência no banco.
    _AVISOS_SEM_OCORRENCIA = ("falha", "relogio")

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
        """Despacha a fila; falha de rede mantém o item pendente."""
        enviados = 0
        for item in self._sync.pendentes():
            if item["tipo"] in self._TIPOS_HISTORICO:
                enviar = self._enviar_tomada
            elif item["tipo"] in self._TIPOS_AVISO:
                enviar = self._enviar_aviso
            else:
                continue  # evento ainda sem destino no backend
            try:
                if enviar(item):
                    self._sync.marca_enviado(item["id"])
                    enviados += 1
            except Exception:
                continue
        return enviados

    def _payload(self, item: dict) -> dict | None:
        try:
            payload = json.loads(item["payload"])
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None
        payload.setdefault("tipo", item["tipo"])
        return payload

    def _enviar_tomada(self, item: dict) -> bool:
        ocorrencia = self._db.obter_ocorrencia(item["ocorrencia_id"])
        if ocorrencia is None:
            return False
        payload = self._payload(item)
        if payload is None:
            return False
        registro = registro_historico(ocorrencia, payload)
        if registro is None:
            return False
        return self._transporte.gravar_historico(item["ocorrencia_id"], registro)

    def _enviar_aviso(self, item: dict) -> bool:
        """Aviso do cuidador (ADR 010). Falha de sensor e relógio incorreto são
        os únicos casos em que a ocorrência não existe."""
        ocorrencia = self._db.obter_ocorrencia(item["ocorrencia_id"])
        if ocorrencia is None and item["tipo"] not in self._AVISOS_SEM_OCORRENCIA:
            return False
        payload = self._payload(item)
        if payload is None:
            return False
        aviso = registro_notificacao(ocorrencia, payload)
        if aviso is None:
            return False
        return self._transporte.gravar_notificacao(
            item["ocorrencia_id"], item["tipo"], aviso
        )

    def ciclo(self) -> dict:
        """Um ciclo completo de sincronização (agenda + eventos)."""
        return {
            "agenda": self.atualizar_agenda(),
            "enviados": self.enviar_pendentes(),
        }
