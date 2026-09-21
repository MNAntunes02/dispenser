"""Coordenador: liga agenda, relógio, ponte e máquina de estados.

Ciclo de um `tick()`:
1. sincroniza as ocorrências do dia na agenda local;
2. ativa a ocorrência devida (uma por vez, fila por horário);
3. verifica timeouts (alarme, gaveta, retorno, limite);
4. drena eventos da ponte para a máquina;
5. executa as ações resultantes (buzzer, LED, tela, registrar, notificar).

Relógio e fonte de agenda são injetáveis para testes e demo.
"""

from __future__ import annotations

from datetime import date, datetime, time
from threading import RLock
from typing import Callable

from core.agendador import Agendador
from core.armazenamento import Database
from core.config import Config
from core.maquina_estados import Acao, Contexto, Fase, processar
from core.notificador import Notificador
from core.sync import SyncService
from core.textos import texto
from hardware.bridge.hardware_bridge import HardwareBridge

Relogio = Callable[[], datetime]


class AgendaMemo:
    """Fonte de agenda em memória (testes/demo; backend real na Fase 3)."""

    def __init__(self, medicamentos: list[dict]) -> None:
        self._medicamentos = medicamentos

    def agenda(self) -> list[dict]:
        return self._medicamentos


class PublicadorLog:
    """Publicador de tela que apenas acumula mensagens (Fase 5 usa socket)."""

    def __init__(self) -> None:
        self.mensagens: list[dict] = []

    def publicar(self, msg: dict) -> None:
        self.mensagens.append(msg)


def _relogio_padrao() -> datetime:
    return datetime.now()


_FASES_ATIVAS = {
    Fase.ALARME.value,
    Fase.AGUARDANDO_GAVETA.value,
    Fase.GAVETA_ABERTA.value,
    Fase.MEDICAMENTO_RETIRADO.value,
    Fase.AGUARDANDO_RETORNO.value,
    Fase.RETORNO_PENDENTE.value,
    Fase.FALHA.value,
}


class Coordenador:
    def __init__(
        self,
        config: Config,
        db: Database,
        agenda_fonte: object,
        ponte: HardwareBridge,
        sync: SyncService | None = None,
        notificador: Notificador | None = None,
        publicador_ui: PublicadorLog | None = None,
        relogio: Relogio | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._agenda_fonte = agenda_fonte
        self._ponte = ponte
        self._sync = sync or SyncService(db)
        self._notificador = notificador or Notificador(db)
        self._publicador_ui = publicador_ui or PublicadorLog()
        self._relogio = relogio or _relogio_padrao
        self._agendador = Agendador()
        self._trava = RLock()
        self._fila_ponte: list[dict] = []
        self._ativa: dict | None = None
        self._gaveta = False
        self._slots: dict[int, bool] = {}
        self._envio_outbox: Callable[[dict], bool] | None = None

    # --- ciclo -------------------------------------------------------------

    def conectar(self) -> None:
        self._db.conectar()
        self._ponte.conectar()
        self._ponte.registrar_evento(self._receber_evento_ponte)
        self._ler_status()
        self._db.criar_schema()
        self._carregar_ativa()

    def finalizar(self) -> None:
        self._ponte.desconectar()
        self._db.fechar()

    def tick(self) -> None:
        with self._trava:
            self._sincronizar_ocorrencias_do_dia()
            if self._ativa is None:
                self._carregar_ativa()
            self._escolher_proxima()
            self._processar_timeouts()
            self._drenar_ponte()
            self._avaliar_retorno()

    def definir_envio_outbox(self, envio: Callable[[dict], bool]) -> None:
        self._envio_outbox = envio

    def tentar_envio(self) -> int:
        if self._envio_outbox is None:
            return 0
        return self._sync.envia_emitidos(self._envio_outbox)

    # --- agendamento -------------------------------------------------------

    def _sincronizar_ocorrencias_do_dia(self) -> None:
        hoje = self._relogio().date()
        for occ in self._agendador.ocorrencias_do_dia(self._agenda_fonte.agenda(), hoje):
            self._db.inserir_ocorrencia_se_nova(occ)

    def _carregar_ativa(self) -> None:
        self._ativa = self._db.ocorrencia_ativa()
        if self._ativa is not None:
            self._avaliar_retorno()

    def _escolher_proxima(self) -> None:
        if self._ativa is not None:
            return
        hoje = self._relogio().date().isoformat()
        base = self._db.proxima_ocorrencia_aguardando(dia=hoje)
        if base is None:
            return
        hh, mm = (int(p) for p in base["horario"].split(":"))
        agendada = datetime.combine(date.fromisoformat(base["dia"]), time(hh, mm))
        if agendada <= self._relogio():
            self._emitir_para(base, "horario_chegou")

    # --- timeouts ----------------------------------------------------------

    def _processar_timeouts(self) -> None:
        ativa = self._ativa
        if ativa is None or ativa["atualizado_em"] is None:
            return
        try:
            ultimo = datetime.fromisoformat(ativa["atualizado_em"])
        except ValueError:
            return
        decorrido = (self._relogio() - ultimo).total_seconds()
        cfg = self._config
        estado = ativa["estado"]
        if estado == Fase.ALARME.value and decorrido >= cfg.intervalo_alarme_s:
            self._emitir_para(ativa, "timeout_alarme")
        elif estado == Fase.AGUARDANDO_GAVETA.value and decorrido >= cfg.timeout_gaveta_s:
            self._emitir_para(ativa, "timeout_gaveta")
        elif estado == Fase.AGUARDANDO_RETORNO.value and decorrido >= cfg.timeout_retorno_s:
            self._emitir_para(ativa, "timeout_retorno")
        elif estado == Fase.RETORNO_PENDENTE.value:
            if decorrido >= cfg.limite_retorno_s and not ativa["notificado"]:
                self._emitir_para(ativa, "limite_retorno_excedido")
                self._db.atualizar_ocorrencia(ativa["id"], notificado=1)

    # --- eventos da ponte --------------------------------------------------

    def _receber_evento_ponte(self, evento: dict) -> None:
        with self._trava:
            self._fila_ponte.append(evento)

    def _ler_status(self) -> None:
        status = self._ponte.status()
        self._gaveta = bool(status.get("gaveta", 0))
        self._slots = {
            int(i): bool(v.get("presente", 0))
            for i, v in status.get("slots", {}).items()
        }

    def _drenar_ponte(self) -> None:
        if not self._fila_ponte:
            return
        eventos = self._fila_ponte
        self._fila_ponte = []
        for evento in eventos:
            self._tratar_evento_ponte(evento)

    def _tratar_evento_ponte(self, evento: dict) -> None:
        tipo = evento.get("e")
        if tipo == "gaveta_aberta":
            self._gaveta = True
            self._emite("gaveta_aberta")
        elif tipo == "gaveta_fechada":
            self._gaveta = False
            self._emite("gaveta_fechada")
        elif tipo == "slot_presente":
            slot = int(evento.get("slot", -1))
            self._slots[slot] = True
            self._emite("slot_presente", {"slot": slot})
        elif tipo == "slot_ausente":
            slot = int(evento.get("slot", -1))
            self._slots[slot] = False
            self._emite("slot_ausente", {"slot": slot})
        elif tipo == "botao":
            self._emite("ok")
        elif tipo == "falha":
            self._emite("falha", {"codigo": evento.get("codigo", "F000")})
        else:
            self._db.registrar_log(f"evento_ignorado:{tipo}")

    def _retorno_ok(self, ativa: dict | None) -> bool:
        if ativa is None:
            return False
        if ativa["estado"] not in (Fase.AGUARDANDO_RETORNO.value, Fase.RETORNO_PENDENTE.value):
            return False
        if self._gaveta:  # gaveta precisa estar fechada
            return False
        slot = ativa["slot"]
        if slot is not None:
            return self._slots.get(slot, False)
        return any(self._slots.values())

    def _avaliar_retorno(self) -> None:
        if self._retorno_ok(self._ativa):
            self._emitir_para(self._ativa, "retorno_ok")

    def _emite(self, evento: str, dados: dict | None = None) -> None:
        if self._ativa is not None:
            self._emitir_para(self._ativa, evento, dados)
            return
        if evento == "gaveta_aberta":
            hoje = self._relogio().date().isoformat()
            base = self._db.proxima_ocorrencia_aguardando(dia=hoje)
            if base is not None:
                self._emitir_para(base, evento, dados)
            else:
                self._db.registrar_log("gaveta_fora_de_horario")

    # --- máquina de estados e ações ----------------------------------------

    def _emitir_para(self, occ: dict, evento: str, dados: dict | None = None) -> None:
        occ_id = occ["id"]
        ctx = Contexto(
            nome=occ["medicamento_nome"],
            dosagem=occ["dosagem"],
            slot=occ["slot"],
            tentativas=int(occ["tentativas"]),
            proxima_dose=self._proxima_dose(excepto=occ_id),
        )
        nova_fase, acoes, novas_tentativas = processar(
            Fase(occ["estado"]), ctx, self._config, evento, dados
        )
        self._db.registrar_log(f"evento:{evento}", occ_id)
        if nova_fase.value == occ["estado"] and not acoes:
            return
        self._db.atualizar_ocorrencia(
            occ_id, estado=nova_fase.value, tentativas=novas_tentativas
        )
        for acao in acoes:
            self._executar_acao(acao, occ_id)
        nova = self._db.obter_ocorrencia(occ_id)
        self._ativa = nova if nova["estado"] in _FASES_ATIVAS else None

    def _proxima_dose(self, excepto: str | None = None) -> str:
        hoje = self._relogio().date().isoformat()
        candidatas = self._db.proximas_ocorrencias_aguardando(dia=hoje)
        if excepto is not None:
            candidatas = [o for o in candidatas if o["id"] != excepto]
        return candidatas[0]["horario"] if candidatas else ""

    def _executar_acao(self, acao: Acao, occ_id: str) -> None:
        dados = acao.dados
        if acao.tipo == "buzzer":
            self._ponte.buzzer(dados.get("padrao", "dose"))
        elif acao.tipo == "parar_buzzer":
            self._ponte.buzzer("off")
        elif acao.tipo == "led":
            slot = dados.get("slot")
            self._ponte.acender_led(-1 if slot is None else int(slot), dados.get("estado", "on"))
        elif acao.tipo == "apagar_led":
            slot = dados.get("slot")
            self._ponte.acender_led(-1 if slot is None else int(slot), "off")
        elif acao.tipo == "tela":
            chave = dados.get("chave")
            variante = ""
            if chave in ("retire_medicamento", "devolva_slot", "aviso_retorno") and dados.get("slot") is None:
                variante = "_sem_slot"
            elif chave == "tudo_certo" and not dados.get("proxima"):
                variante = "_fim"
            params = {k: v for k, v in dados.items() if k != "chave"}
            mensagem = texto(f"{chave}{variante}", **params)
            self._publicador_ui.publicar({"tipo": "tela", "chave": chave, "mensagem": mensagem})
        elif acao.tipo == "registrar":
            self._registrar(occ_id, dados.get("tipo", ""), dados)
        elif acao.tipo == "notificar":
            self._notificar(occ_id, dados)

    def _registrar(self, occ_id: str, tipo: str, dados: dict) -> None:
        payload = {"ocorrencia_id": occ_id}
        if tipo == "dose_tomada":
            payload["horario_real"] = self._relogio().isoformat(timespec="seconds")
        elif tipo == "falha":
            payload["codigo"] = dados.get("codigo", "?")
        self._sync.enfileirar_evento(occ_id, tipo, payload)
        self._db.registrar_log(f"registrar:{tipo}", occ_id)

    def _notificar(self, occ_id: str, dados: dict) -> None:
        motivo = dados.get("motivo")
        if motivo == "dose_perdida":
            self._notificador.notificar_dose_perdida(occ_id)
        elif motivo == "nao_devolvido":
            self._notificador.notificar_retorno_pendente(occ_id)
        elif motivo == "falha":
            self._notificador.notificar_falha(dados.get("codigo", "?"))