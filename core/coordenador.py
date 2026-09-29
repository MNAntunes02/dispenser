"""Coordenador: liga agenda, relógio, ponte e máquina de estados.

Ciclo de um `tick()`:
1. confere se o relógio é confiável (Fase 7, ADR 012) — sem hora certa, não
   agenda nem dispara nada e a tela avisa;
2. sincroniza as ocorrências do dia na agenda local;
3. ativa a ocorrência devida (uma por vez, fila por horário);
4. verifica timeouts (alarme, gaveta, retorno, limite);
5. drena eventos da ponte para a máquina;
6. executa as ações resultantes (buzzer, LED, tela, registrar, notificar).

Relógio e fonte de agenda são injetáveis para testes e demo.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from threading import RLock
from typing import Callable

from core.agendador import Agendador
from core.armazenamento import Database
from core.config import Config
from core.maquina_estados import Acao, Contexto, Fase, processar
from core.notificador import Notificador
from core.protocolo_ui import envelope, passo_de
from core.relogio import (
    EstadoRelogio,
    VerificadorRelogio,
    chave_tela,
    estado_para_notificacao,
    ler_data_minima,
)
from core.sync import SyncService
from core.textos import ROTULOS_UI, TOTAL_PASSOS, texto
from hardware.bridge.hardware_bridge import HardwareBridge

Relogio = Callable[[], datetime]


class AgendaMemo:
    """Fonte de agenda em memória (testes/demo; backend real na Fase 3)."""

    def __init__(self, medicamentos: list[dict]) -> None:
        self._medicamentos = medicamentos

    def agenda(self) -> list[dict]:
        return self._medicamentos


class PublicadorLog:
    """Publicador de tela que apenas acumula mensagens (sem UI conectada)."""

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

#: Fases em que a dose só avança com um "OK" (botão físico ou tecla na UI).
_FASES_ESPERAM_BOTAO = {Fase.ALARME.value, Fase.MEDICAMENTO_RETIRADO.value}

#: `botao` só confirma a dose quando o id da placa for este. Abridão: evento
#: sem id (simulador antigo) também confirma.
_BOTAO_CONFIRMA = "confirma"

#: Telas de repouso: fora do fluxo da dose e sem `passo` (spec 05).
_CHAVES_REPOSO = ("reposo", "reposo_sem_dose")

#: Telas que o core publica sem ocorrência (alerta). Não são tocadas pelo
#: `_publicar_reposo_se_precisa`, que só repinta telas de repouso.
_CHAVES_ALERTA = ("relogio_nao_confiavel", "relogio_instavel")

#: Chave de texto de cada fase da dose, só para **repetir a tela** depois que o
#: relógio deixou de ser confiável (a decisão continua na máquina de estados;
#: aqui é apresentação, para o paciente não ficar olhando o aviso de relógio).
_CHAVE_POR_FASE = {
    Fase.ALARME.value: "hora_remedio",
    Fase.AGUARDANDO_GAVETA.value: "abra_gaveta",
    Fase.GAVETA_ABERTA.value: "retire_medicamento",
    Fase.MEDICAMENTO_RETIRADO.value: "tome_e_ok",
    Fase.AGUARDANDO_RETORNO.value: "devolva_slot",
    Fase.RETORNO_PENDENTE.value: "aviso_retorno",
    Fase.FALHA.value: "falha",
}


def _fluxo(chave: str) -> str:
    """Informa à UI como desenhar: fluxo da dose, repouso ou alerta."""
    if chave in _CHAVES_REPOSO:
        return "reposo"
    return "dose" if passo_de(chave) is not None else "alerta"


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
        verificador_relogio: VerificadorRelogio | None = None,
    ) -> None:
        self._config = config
        self._db = db
        self._agenda_fonte = agenda_fonte
        self._ponte = ponte
        self._sync = sync or SyncService(db)
        self._publicador_ui = publicador_ui or PublicadorLog()
        self._relogio = relogio or _relogio_padrao
        # O notificador compartilha a fila do `sync`: um aviso por ocorrência,
        # entregue pelo `Sincronizador` (Fase 6, ADR 010).
        self._notificador = notificador or Notificador(db, self._sync, self._relogio)
        self._agendador = Agendador()
        self._verificador = verificador_relogio or VerificadorRelogio(
            self._relogio,
            data_minima=ler_data_minima(config.data_minima),
            tolerancia_s=config.tolerancia_salto_s,
        )
        self._trava = RLock()
        self._fila_ponte: list[dict] = []
        self._ativa: dict | None = None
        self._gaveta = False
        self._slots: dict[int, bool] = {}
        self._envio_outbox: Callable[[dict], bool] | None = None
        self._ultima_tela: dict | None = None
        self._dia_publicado: str | None = None
        self._agenda_sujeja = False
        self._ultimo_alerta: str | None = None
        self._ui: object | None = None
        self._retrato_cache: list[dict] = []
        self._relogio_confiavel = True
        self._relogio_tela_publicada = False
        self._ultimo_codigo: str | None = None

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

    def definir_publicador_ui(self, publicador: object) -> None:
        """Troca o destino das mensagens de tela (socket da UI, no boot)."""
        self._publicador_ui = publicador

    def definir_agenda_fonte(self, fonte: object) -> None:
        """Troca a fonte da agenda depois do provisionamento (Fase 3b, Fase 7).

        O app pareia por Bluetooth com o core já no ar; quando o arquivo de
        configuração aparece, o core passa a ler a agenda da nuvem sem reiniciar.
        A dose em andamento não é tocada — só a fonte das próximas ocorrências.
        """
        with self._trava:
            self._agenda_fonte = fonte
            self._agenda_sujeja = True
            self._dia_publicado = None

    @property
    def fonte_agenda(self) -> object:
        """Fonte da agenda em uso (testes e diagnóstico no journal)."""
        return self._agenda_fonte

    def tick(self) -> None:
        with self._trava:
            if not self._relogio_pode_disparar():
                return
            self._sincronizar_ocorrencias_do_dia()
            self._marcar_doses_passar()
            self._publicar_agenda_se_precisa()
            if self._ativa is None:
                self._carregar_ativa()
            self._escolher_proxima()
            self._drenar_ui()
            self._processar_timeouts()
            self._drenar_ponte()
            self._avaliar_retorno()
            self._publicar_reposo_se_precisa()
            self._atualizar_retrato()

    # --- confiabilidade do relógio (Fase 7, ADR 012) -----------------------

    def _relogio_pode_disparar(self) -> bool:
        """Confere o relógio antes de qualquer decisão de dose.

        Com hora não confiável o `tick` para inteiro: não sincroniza a agenda,
        não dispara e não conta timeout. A tela avisa o paciente. Decisão do
        usuário na Fase 7 — avisar por horário errado é pior que atrasar a dose.
        """
        avaliacao = self._verificador.avaliar()
        if avaliacao.confiavel:
            if not self._relogio_confiavel:
                self._ao_confiar_relogio(avaliacao)
            return True

        if self._relogio_confiavel:  # primeira leitura ruim da sessão
            self._db.registrar_log(
                estado_para_notificacao(avaliacao.estado), detalhe=avaliacao.motivo
            )
            if self._ativa is not None:
                # Não deixa o alarme tocar às cegas: sem hora confiável o
                # paciente não consegue saber a hora, e o barulho infinito
                # só cansa. A dose em andamento fica parada, sem timeout.
                self._ponte.buzzer("off")
        self._relogio_confiavel = False
        if not self._relogio_tela_publicada:
            self._publicar_tela("", None, {"chave": chave_tela(avaliacao.estado)})
            self._relogio_tela_publicada = True
        self._atualizar_retrato()
        return False

    def _ao_confiar_relogio(self, avaliacao) -> None:
        """O horário voltou a valer: retoma o fluxo e fecha a janela perdida."""
        self._db.registrar_log("relogio_confiavel")
        self._relogio_confiavel = True
        self._relogio_tela_publicada = False
        self._sincronizar_ocorrencias_do_dia()
        perdidas = self._marcar_doses_passar()
        if perdidas:
            # Um aviso por indisponibilidade, não um por dose: 3 dias sem NTP
            # não podem virar dezenas de avisos para o cuidador.
            self._notificador.notificar_relogio(
                len(perdidas), inicio=avaliacao.inicio, durou_s=avaliacao.durou_s
            )
        if self._ativa is not None:
            # O paciente não ouviu nada na janela: os temporizadores recomeçam
            # agora em vez de estourar retroativamente por causa do relógio.
            self._db.atualizar_ocorrencia(self._ativa["id"])
        self._republicar_tela()

    def _republicar_tela(self) -> None:
        """Repinta a tela depois do aviso de relógio (só apresentação).

        A máquina de estados não mudou nada; sem isto o paciente ficaria olhando
        o aviso de relógio mesmo com a hora corrigida.
        """
        ativa = self._ativa
        chave = _CHAVE_POR_FASE.get(ativa["estado"]) if ativa is not None else None
        if chave is None:
            if ativa is not None and ativa["estado"] == Fase.FALHA.value:
                if not self._ultimo_codigo:
                    # Sem o código original (ex.: reinício dentro de FALHA) não
                    # inventamos número de falha: registra e segue.
                    self._db.registrar_log("tela_nao_republicada:FALHA")
            self._ultima_tela = None
            return
        dados: dict = {
            "chave": chave,
            "slot": ativa["slot"],
            "nome": ativa["medicamento_nome"],
            "dosagem": ativa["dosagem"],
            "proxima": self._proxima_dose(excepto=ativa["id"]),
        }
        if chave == "falha":
            dados["codigo"] = self._ultimo_codigo or "?"
        self._publicar_tela(ativa["id"], ativa["estado"], dados)

    def _marcar_doses_passar(self) -> list[str]:
        """Fecha as doses cujo horário passou além da janela de atraso.

        Disparar em fila doses de horas atrás não ajuda ninguém e ainda toca
        alarme num horário que o paciente não reconhece. A ocorrência vai para
        `NAO_ATENDIDA` por persistence (a máquina de estados não roda: aqui o
        registro é o de "não houve lembrete") e o cuidadoor recebe um aviso
        agregado quando a causa foi o relógio (ADR 012).
        """
        hoje = self._relogio().date().isoformat()
        agora = self._relogio()
        janela = timedelta(seconds=self._config.janela_atraso_s)
        perdidas: list[str] = []
        for occ in self._db.proximas_ocorrencias_aguardando(dia=hoje):
            hh, mm = (int(p) for p in occ["horario"].split(":"))
            agendada = datetime.combine(date.fromisoformat(occ["dia"]), time(hh, mm))
            if agendada + janela < agora:
                perdidas.append(occ["id"])
        if perdidas:
            self._db.marcar_nao_atendida(perdidas)
            # Sem nome de medicamento no log (LGPD).
            self._db.registrar_log("doses_passadas", detalhe=str(len(perdidas)))
        return perdidas

    def definir_envio_outbox(self, envio: Callable[[dict], bool]) -> None:
        self._envio_outbox = envio

    def tentar_envio(self) -> int:
        if self._envio_outbox is None:
            return 0
        return self._sync.envia_emitidos(self._envio_outbox)

    # --- agendamento -------------------------------------------------------

    def _sincronizar_ocorrencias_do_dia(self) -> None:
        hoje = self._relogio().date()
        novas = False
        for occ in self._agendador.ocorrencias_do_dia(self._agenda_fonte.agenda(), hoje):
            novas = self._db.inserir_ocorrencia_se_nova(occ) or novas
        if novas:
            self._agenda_sujeja = True

    def _publicar_agenda_se_precisa(self) -> None:
        """Republica a agenda do dia quando ela muda (virada do dia/novas doses)."""
        hoje = self._relogio().date().isoformat()
        if self._dia_publicado != hoje or self._agenda_sujeja:
            self.publicar_agenda()

    # --- interface com a UI --------------------------------------------------

    def _drenar_ui(self) -> None:
        """Processa a entrada vinda da UI (fila alimentada pelo socket).

        A entrada chega pela fila, nunca direto do socket: assim todo o
        estado do core — e o banco SQLite — continuam em uma thread só.
        """
        if self._ui is None:
            return
        for msg in self._ui.entradas():
            self.entrada_ui(msg)

    def definir_ui(self, ui: object | None) -> None:
        """Liga/desliga a fonte de mensagens da UI (socket) no boot."""
        self._ui = ui

    def entrada_ui(self, msg: dict) -> bool:
        """Trata uma mensagem da UI. A UI só informa intenção; o core decide."""
        tipo = msg.get("type")
        if tipo == "input":
            return self._acao_ui(str(msg.get("acao") or ""))
        if tipo == "comando":
            self._db.registrar_log(f"ui_comando:{msg.get('cmd', '')}")
            return True
        if tipo == "health":
            return True
        return False

    def _acao_ui(self, acao: str) -> bool:
        with self._trava:
            if acao != "confirma":
                # Política aprovada: sem soneca. Qualquer outra ação é ignorada.
                self._db.registrar_log(f"ui_acao_ignorada:{acao}")
                return False
            if self._ativa is None:
                self._db.registrar_log("ui_confirma_sem_dose")
                return False
            self._emitir_para(self._ativa, "ok")
            return True

    def _publicar_reposo_se_precisa(self) -> None:
        """Mantém a tela de repouso na UI quando não há dose em andamento.

        Sem isso a UI ficaria em "conectando" para sempre: o core precisa dizer
        explicitamente que está ocioso e qual é a próxima dose.
        """
        if self._ativa is not None:
            return
        atual = self._ultima_tela
        if atual is not None and atual.get("chave") not in _CHAVES_REPOSO:
            return  # tela de dose/aviso: não sobrescreve nada
        proxima = self._proxima_dose()
        chave = "reposo" if proxima else "reposo_sem_dose"
        if atual is not None and atual.get("chave") == chave and (
            atual.get("proxima", "") == (proxima or "")
        ):
            return  # nada mudou: não repinta a tela
        self._publicar_tela(
            "",
            None,
            {"chave": chave, "proxima": proxima or ""},
        )

    def _msg_agenda(self) -> dict:
        hoje = self._relogio().date().isoformat()
        return envelope(
            "agenda",
            self._relogio,
            dia=hoje,
            ocorrencias=[
                {
                    "id": o["id"],
                    "medicamento": o["medicamento_nome"],
                    "dosagem": o["dosagem"],
                    "slot": o["slot"],
                    "horario": o["horario"],
                    "estado": o["estado"],
                }
                for o in self._db.ocorrencias_do_dia(hoje)
            ],
        )

    def publicar_agenda(self) -> None:
        hoje = self._relogio().date().isoformat()
        self._dia_publicado = hoje
        self._agenda_sujeja = False
        self._publicador_ui.publicar(self._msg_agenda())

    def retrato(self) -> list[dict]:
        """Estado completo para a UI que acabou de (re)conectar."""
        mensagens = [
            envelope(
                "rotulos",
                self._relogio,
                rotulos=ROTULOS_UI,
                totalPassos=TOTAL_PASSOS,
            )
        ]
        mensagens.append(self._msg_agenda())
        if self._ultima_tela is not None:
            mensagens.append(self._ultima_tela)
        return mensagens

    def _atualizar_retrato(self) -> None:
        """Cache do retrato para a thread do socket nunca tocar o banco."""
        self._retrato_cache = self.retrato()

    def retrato_cache(self) -> list[dict]:
        """Retrato pronto (gerado no `tick`), seguro de ler de outra thread."""
        if not self._retrato_cache:
            self._retrato_cache = self.retrato()
        return list(self._retrato_cache)

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
            # Só o botão "confirma" avança a dose: avanca/volta/ajuda da placa
            # existem para a navegação da tela e não confirmam a tomada.
            botao = evento.get("id")
            if botao in (None, _BOTAO_CONFIRMA):
                self._emite("ok")
            else:
                self._db.registrar_log(f"botao_sem_efeito:{botao}")
        elif tipo == "falha":
            codigo = str(evento.get("codigo") or "F000")
            self._ultimo_codigo = codigo
            self._emite("falha", {"codigo": codigo})
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
        if evento == "falha":
            # Falha com ocioso (ex.: perda de heartbeat da placa) não pode ser
            # descartada: a tela de repouso precisa avisar (AGENTS.md).
            self._falha_sem_dose(str((dados or {}).get("codigo") or "F000"))
            return
        if evento == "gaveta_aberta":
            hoje = self._relogio().date().isoformat()
            base = self._db.proxima_ocorrencia_aguardando(dia=hoje)
            if base is not None:
                self._emitir_para(base, evento, dados)
            else:
                self._db.registrar_log("gaveta_fora_de_horario")

    def _falha_sem_dose(self, codigo: str) -> None:
        self._db.registrar_log(f"falha_sem_dose:{codigo}")
        if codigo == self._ultimo_alerta:
            return  # mesmo alerta repetido: não republisha nem notifica de novo
        self._ultimo_alerta = codigo
        self._ultimo_codigo = codigo
        self._publicador_ui.publicar(
            envelope(
                "alerta",
                self._relogio,
                codigo=codigo,
                mensagem=texto("falha_sensor", codigo=codigo),
            )
        )
        self._notificador.notificar_falha(codigo)

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
            self._executar_acao(acao, occ_id, nova_fase.value)
        nova = self._db.obter_ocorrencia(occ_id)
        self._ativa = nova if nova["estado"] in _FASES_ATIVAS else None

    def _proxima_dose(self, excepto: str | None = None) -> str:
        hoje = self._relogio().date().isoformat()
        candidatas = self._db.proximas_ocorrencias_aguardando(dia=hoje)
        if excepto is not None:
            candidatas = [o for o in candidatas if o["id"] != excepto]
        return candidatas[0]["horario"] if candidatas else ""

    def _executar_acao(self, acao: Acao, occ_id: str, fase: str | None = None) -> None:
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
            self._publicar_tela(occ_id, fase, dados)
        elif acao.tipo == "registrar":
            self._registrar(occ_id, dados.get("tipo", ""), dados)
        elif acao.tipo == "notificar":
            self._notificar(occ_id, dados)

    def _publicar_tela(self, occ_id: str, fase: str | None, dados: dict) -> None:
        """Renderiza a frase em pt-BR e publica o passo para a UI.

        A frase é montada aqui (fonte única `core/textos.py`); a UI exibe
        `mensagem` como veio e não conhece a máquina de estados.
        """
        chave = dados.get("chave")
        variante = ""
        if chave in ("retire_medicamento", "devolva_slot", "aviso_retorno") and dados.get("slot") is None:
            variante = "_sem_slot"
        elif chave == "tudo_certo" and not dados.get("proxima"):
            variante = "_fim"
        params = {k: v for k, v in dados.items() if k != "chave"}
        mensagem = texto(f"{chave}{variante}", **params)
        passo = passo_de(chave)
        msg = envelope(
            "estado",
            self._relogio,
            fase=fase,
            ocorrenciaId=occ_id,
            chave=chave,
            mensagem=mensagem,
            passo=passo,
            totalPassos=TOTAL_PASSOS,
            slot=dados.get("slot"),
            proxima=dados.get("proxima") or "",
            esperaBotao=fase in _FASES_ESPERAM_BOTAO,
            fluxo=_fluxo(chave),
        )
        self._ultima_tela = msg
        self._publicador_ui.publicar(msg)

    def _registrar(self, occ_id: str, tipo: str, dados: dict) -> None:
        payload = {
            "ocorrencia_id": occ_id,
            # Momento do evento: o aviso do cuidador (Fase 6) mostra quando
            # aconteceu, mesmo fora de qualquer dose tomada.
            "horario_real": self._relogio().isoformat(timespec="seconds"),
        }
        if tipo == "falha":
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
            self._notificador.notificar_falha(dados.get("codigo", "?"), occ_id)
