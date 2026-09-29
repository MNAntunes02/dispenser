"""Notificador: avisos para cuidador/app (Fase 6, ADR 010).

O aviso de cada motivo vira um evento da fila `outbox`; quem entrega é o
`Sincronizador`, quando houver rede. Nenhum aviso bloqueia o fluxo da dose e
nenhum nome de medicamento vai para o log local (LGPD).

A fila absorve a duplicidade: a chave `UNIQUE` da outbox
(`{ocorrencia_id}|{tipo}`) garante um aviso só por ocorrência, mesmo quando a
máquina de estados já registrou o mesmo evento na ação `registrar`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from core.armazenamento import Database
from core.sync import SyncService

Relogio = Callable[[], datetime]


class Notificador:
    """Enfileira os avisos do cuidador; a entrega é do `Sincronizador`."""

    def __init__(
        self,
        db: Database,
        sync: SyncService | None = None,
        relogio: Relogio | None = None,
    ) -> None:
        self._db = db
        self._sync = sync or SyncService(db)
        self._relogio = relogio or datetime.now

    def notificar_dose_perdida(self, ocorrencia_id: str) -> None:
        self._enfileirar(ocorrencia_id, "dose_perdida")
        self._db.registrar_log("notificar_dose_perdida", ocorrencia_id)

    def notificar_retorno_pendente(self, ocorrencia_id: str) -> None:
        self._enfileirar(ocorrencia_id, "retorno_pendente")
        self._db.registrar_log("notificar_retorno_pendente", ocorrencia_id)

    def notificar_falha(
        self, codigo: str, ocorrencia_id: str | None = None, info: str = ""
    ) -> None:
        """Falha com dose em andamento entra pelo aviso da ocorrência; sem dose
        (sensor com ociosidade) o aviso leva o dia, para o cuidador saber
        quando procurar o dispensador."""
        codigo = str(codigo or "?")
        if ocorrencia_id:
            self._enfileirar(ocorrencia_id, "falha", {"codigo": codigo})
        else:
            hoje = self._relogio().date().isoformat()
            self._sync.enfileirar_evento(
                "",
                "falha",
                {
                    "codigo": codigo,
                    "dia": hoje,
                    "horario_real": self._relogio().isoformat(timespec="seconds"),
                },
                chave=f"sem_dose|falha|{codigo}|{hoje}",
            )
        self._db.registrar_log("notificar_falha", detalhe=f"{codigo} {info}".strip())

    def _enfileirar(
        self, ocorrencia_id: str, tipo: str, payload: dict | None = None
    ) -> None:
        dados = dict(payload or {})
        dados.setdefault(
            "horario_real", self._relogio().isoformat(timespec="seconds")
        )
        dados["ocorrencia_id"] = ocorrencia_id
        self._sync.enfileirar_evento(ocorrencia_id, tipo, dados)
