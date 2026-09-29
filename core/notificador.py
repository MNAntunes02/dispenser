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

    def notificar_relogio(
        self,
        doses: int,
        *,
        inicio: datetime | None = None,
        durou_s: float = 0.0,
    ) -> None:
        """Relógio incorreto: **um** aviso por indisponibilidade (ADR 012).

        Não é um aviso por dose perdida — se o Pi ficar dias sem NTP, o
        cuidador recebe uma mensagem dizendo quantas doses ficaram sem lembrete
        em vez de dezenas de avisos. A chave inclui o dia, então uma segunda
        janela no mesmo dia não vira aviso novo (e o reenvio é idempotente).
        """
        doses = max(0, int(doses))
        agora = self._relogio()
        dia = agora.date().isoformat()
        payload: dict = {
            "dia": dia,
            "doses": doses,
            "horario_real": agora.isoformat(timespec="seconds"),
        }
        if inicio is not None:
            payload["inicio"] = inicio.isoformat(timespec="seconds")
        if durou_s > 0:
            payload["durou_s"] = int(duru_s)
        self._sync.enfileirar_evento(
            f"relogio|{dia}",
            "relogio",
            payload,
            chave=f"sem_dose|relogio|{dia}",
        )
        # Sem nome de medicamento no log (LGPD).
        self._db.registrar_log("notificar_relogio", detalhe=f"doses={doses}")

    def _enfileirar(
        self, ocorrencia_id: str, tipo: str, payload: dict | None = None
    ) -> None:
        dados = dict(payload or {})
        dados.setdefault(
            "horario_real", self._relogio().isoformat(timespec="seconds")
        )
        dados["ocorrencia_id"] = ocorrencia_id
        self._sync.enfileirar_evento(ocorrencia_id, tipo, dados)
