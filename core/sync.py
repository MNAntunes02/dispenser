"""Sync com o backend do app (Firestore): polling + fila outbox.

Estratégia (ADR 005): polling da agenda a cada ~15s; eventos de adesão
enfileirados em SQLite com idempotência por chave. O transporte real
(Firestore, Fase 3) fornece a agenda, registra `dose_tomada` no `Historico` e
(a Fase 6, ADR 010) publica os avisos do cuidador em `Notificacoes`; aqui ficam
a fila, a fonte local da agenda (cache) e a orquestração do ciclo.

A ponte com o app mobile acrescenta `Dispensadores/{id}/Comandos` (intenções
do cadastro de cartela) e a publicação de `Estoque` e `Registro/estado`.
Comandos são executados **na thread do core** — quem decide o estoque e o
fluxo é o coordenador; o sync só transporta e confirma o resultado.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Callable

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
        self._ultimo_erro: str = ""

    def atualizar_agenda(self) -> bool:
        """Lê os medicamentos do backend e substitui o cache local."""
        try:
            medicamentos = self._transporte.ler_medicamentos()
        except Exception as erro:
            self._ultimo_erro = f"{erro.__class__.__name__}: {erro}"
            return False
        self._ultimo_erro = ""
        self._db.substituir_agenda(medicamentos)
        return True

    def enviar_item(self, item: dict) -> bool:
        """Envia **um** item da fila. `True` = saiu do aparelho.

        Usado tanto pelo `ciclo()` quanto pelo callback do coordenador, que
        precisa de uma função `item -> bool` para a `outbox` (Fase 7: o core
        tenta enviar assim que o app termina o pareamento, sem esperar o fim
        do intervalo de sync).
        """
        if item["tipo"] in self._TIPOS_HISTORICO:
            return self._enviar_tomada(item)
        if item["tipo"] in self._TIPOS_AVISO:
            return self._enviar_aviso(item)
        return False  # evento ainda sem destino no backend

    def enviar_pendentes(self) -> int:
        """Despacha a fila; falha de rede mantém o item pendente."""
        enviados = 0
        for item in self._sync.pendentes():
            try:
                if self.enviar_item(item):
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

    # --- ponte com o app mobile (estoque e cadastro de cartela) -------------

    _PRAZO_COMANDO = timedelta(minutes=2)

    def processar_comandos(
        self, executar: Callable[[dict], bool | tuple[bool, str]]
    ) -> int:
        """Executa comandos pendentes do app e grava o resultado no Firestore.

        O doc é marcado `processando` **antes** da execução: se o core cair no
        meio do caminho, um `processando` antigo é retomado em vez de virar
        duplicidade de cadastro. A execução é síncrona (thread do core).
        """
        try:
            comandos = self._transporte.ler_comandos()
        except Exception:
            return 0
        processados = 0
        for comando in comandos:
            comando_id = str(comando.get("id") or "")
            if not comando_id:
                continue
            status = str(comando.get("status") or "")
            if status not in ("pendente", "processando"):
                continue
            if status == "processando" and not self._comando_expirado(comando):
                continue
            try:
                self._transporte.gravar_comando(
                    comando_id,
                    {
                        "status": "processando",
                        "processadoEm": datetime.now().isoformat(timespec="seconds"),
                    },
                )
                executado = executar(comando)
                if isinstance(executado, tuple):
                    ok, motivo = bool(executado[0]), str(executado[1] or "")
                else:
                    ok, motivo = bool(executado), ""
            except Exception as erro:
                ok, motivo = False, "erro_interno"
                self._ultimo_erro = f"{erro.__class__.__name__}: {erro}"
            try:
                resultado = {"ok": ok}
                if not ok and motivo:
                    resultado["motivo"] = motivo
                self._transporte.gravar_comando(
                    comando_id,
                    {
                        "status": "concluido" if ok else "erro",
                        "processadoEm": datetime.now().isoformat(timespec="seconds"),
                        "resultado": resultado,
                    },
                )
            except Exception:
                pass  # o core já executou; falha só de publicação do resultado
            processados += 1
        return processados

    @classmethod
    def _comando_expirado(cls, comando: dict) -> bool:
        valor = comando.get("processadoEm") or comando.get("criadoEm")
        if not isinstance(valor, str):
            return True
        try:
            return datetime.now() - datetime.fromisoformat(valor) > cls._PRAZO_COMANDO
        except ValueError:
            return True

    def descartar_comandos_antigos(self, max_idade: timedelta | None = None) -> int:
        """Cancela no boot comandos `pendente` que o app já abandonou.

        Sem isto, uma tentativa que morreu no timeout volta a ser processada
        depois da reinicialização e abre um cadastro que bloqueia o novo.
        """
        prazo = max_idade or self._PRAZO_COMANDO
        try:
            comandos = self._transporte.ler_comandos()
        except Exception:
            return 0
        cancelados = 0
        for comando in comandos:
            comando_id = str(comando.get("id") or "")
            criado = comando.get("criadoEm")
            if (
                not comando_id
                or comando.get("status") != "pendente"
                or not isinstance(criado, str)
            ):
                continue
            try:
                idade = datetime.now() - datetime.fromisoformat(criado)
            except ValueError:
                continue
            if idade <= prazo:
                continue
            try:
                if self._transporte.gravar_comando(
                    comando_id,
                    {
                        "status": "cancelado",
                        "processadoEm": datetime.now().isoformat(timespec="seconds"),
                    },
                ):
                    cancelados += 1
            except Exception:
                continue
        return cancelados

    def publicar_estoque(self, itens: list[dict]) -> bool:
        try:
            return bool(self._transporte.gravar_estoque(itens))
        except Exception:
            return False

    def publicar_registro(self, estado: dict) -> bool:
        try:
            return bool(self._transporte.gravar_registro(estado))
        except Exception:
            return False

    def publicar_saude(self, estado: dict) -> bool:
        """Publica o batimento da ponte para o app não ficar no escuro."""
        try:
            return bool(self._transporte.gravar_saude(estado))
        except Exception:
            return False

    def atender_dispositivo(
        self,
        executar: Callable[[dict], bool | tuple[bool, str]],
        estoque: list[dict],
        registro: dict,
        saude: dict | None = None,
    ) -> dict:
        """Executa comandos do app e publica estoque/estado após mudanças."""
        processados = self.processar_comandos(executar)
        publicados = 0
        if processados:
            if self.publicar_estoque(estoque):
                publicados += 1
            if self.publicar_registro(registro):
                publicados += 1
        if saude is not None and self.publicar_saude(saude):
            publicados += 1
        return {"comandos": processados, "publicados": publicados}

    def ciclo(
        self,
        *,
        executar_comando: Callable[[dict], bool | tuple[bool, str]] | None = None,
        estoque: list[dict] | None = None,
        registro: dict | None = None,
        saude: dict | None = None,
    ) -> dict:
        """Um ciclo completo de sincronização (agenda + eventos + dispositivo)."""
        agendou = self.atualizar_agenda()
        if not agendou and self._ultimo_erro:
            self._db.registrar_log("sync_agenda_falhou", detalhe=self._ultimo_erro)
        resumo = {"agenda": agendou, "enviados": self.enviar_pendentes()}
        if executar_comando is not None:
            resumo.update(
                self.atender_dispositivo(
                    executar_comando, estoque or [], registro or {}, saude
                )
            )
        else:
            publicados = 0
            if estoque is not None and self.publicar_estoque(estoque):
                publicados += 1
            if registro is not None and self.publicar_registro(registro):
                publicados += 1
            if saude is not None and self.publicar_saude(saude):
                publicados += 1
            resumo["publicados"] = publicados
        return resumo
