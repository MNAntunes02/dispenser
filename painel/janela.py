"""Janela Tkinter do painel de desenvolvimento.

A janela só desenha e delega: quem sabe iniciar/parar processos é
`painel.gerenciador.Servico`; quem guarda o histórico é `painel.log_buffer`.
As threads dos processos nunca tocam em widgets — elas colocam eventos numa
`queue.Queue` que a thread principal drena a cada 100 ms.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from painel.comandos import ComandosCore
from painel.configuracao import (
    DIR_DEV,
    PASTA_UI,
    RAIZ,
    ambiente_core,
    ambiente_ui,
    avisos_ambiente,
    comando_core,
    comando_ui,
    gerar_agenda_demo,
    preparar_diretorio_dev,
)
from painel.gerenciador import (
    EstadoServico,
    FalhaAoIniciar,
    JaRodando,
    Servico,
)
from painel.log_buffer import BufferLog, LinhaLog, formatar
from painel.textos import TEXTOS, texto
from hardware.bridge.bridge_simulada import SLOTS_PADRAO

#: Tempo entre drenagens da fila de eventos (ms).
_INTERVALO_FILA_MS = 100
#: Espera antes de re-renderizar o log quando o filtro muda (ms).
_DEBOUNCE_FILTRO_MS = 250


def _tag_do_fluxo(fluxo: str) -> str:
    if fluxo == "erro":
        return "erro"
    if fluxo == "painel":
        return "painel"
    return "saida"


class Aplicacao:
    """Monta a janela e conecta os serviços aos widgets."""

    def __init__(
        self,
        servicos: dict[str, Servico],
        fila: queue.Queue[tuple],
    ) -> None:
        self._servicos = servicos
        self._fila = fila
        self._buffers: dict[str, BufferLog] = {
            nome: BufferLog() for nome in servicos
        }
        self._widgets_log: dict[str, tk.Text] = {}
        self._filtros: dict[str, tk.StringVar] = {}
        self._auto_rolagem: dict[str, tk.BooleanVar] = {}
        self._status: dict[str, ttk.Label] = {}
        self._botoes: dict[str, dict[str, ttk.Button]] = {}
        self._render_agendado: dict[str, str | None] = {
            nome: None for nome in servicos
        }
        self._em_parada: set[str] = set()
        self._em_reinicio: set[str] = set()
        self._fechando = False
        # Simulador de hardware (ADR 015): envia eventos de sensor ao core
        # pelo mesmo socket da UI. Log de erro chega pela fila de eventos,
        # pois o envio roda em thread — nunca toca widgets direto.
        self._comandos = ComandosCore(
            DIR_DEV / "core.sock",
            ao_logar=lambda fluxo, msg: self._fila.put(
                ("log", "core", fluxo, msg)
            ),
        )
        self._botoes_simulador: list[ttk.Button] = []
        self._seletor_slot: ttk.Combobox | None = None

        self._janela = tk.Tk()
        self._agenda_demo = tk.BooleanVar(master=self._janela, value=False)
        self._janela.title(TEXTOS["titulo"])
        self._janela.geometry("1150x760")
        self._janela.minsize(900, 600)
        self._janela.columnconfigure(0, weight=1)
        self._janela.rowconfigure(2, weight=1)

        self._configurar_estilos()
        self._construir_cabecalho()
        self._construir_servicos()
        self._construir_logs()
        self._construir_rodape()

        self._janela.protocol("WM_DELETE_WINDOW", self._fechar)
        self._atualizar_todos_status()
        self._janela.after(_INTERVALO_FILA_MS, self._drenar_eventos)

    # --- montagem da janela ------------------------------------------------

    def _configurar_estilos(self) -> None:
        estilo = ttk.Style(self._janela)
        estilo.configure("StatusParado.TLabel", foreground="#6b7280")
        estilo.configure("StatusRodando.TLabel", foreground="#15803d")
        estilo.configure("StatusAtencao.TLabel", foreground="#b45309")
        estilo.configure("StatusErro.TLabel", foreground="#b91c1c")

    def _construir_cabecalho(self) -> None:
        cabecalho = ttk.Frame(self._janela, padding=(12, 12, 12, 4))
        cabecalho.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            cabecalho,
            text=TEXTOS["titulo"],
            font=("TkDefaultFont", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(cabecalho, text=TEXTOS["subtitulo"]).pack(anchor="w")

    def _construir_servicos(self) -> None:
        quadro = ttk.Frame(self._janela, padding=(12, 4, 12, 4))
        quadro.grid(row=1, column=0, sticky="ew")
        quadro.columnconfigure(0, weight=1)
        quadro.columnconfigure(1, weight=1)

        for coluna, nome in enumerate(("core", "ui")):
            self._construir_cartao(quadro, nome, coluna)

        barra = ttk.Frame(quadro)
        barra.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(
            barra,
            text=TEXTOS["iniciar_tudo"],
            command=self._iniciar_tudo,
        ).pack(side="left")
        ttk.Button(
            barra,
            text=TEXTOS["parar_tudo"],
            command=self._parar_tudo,
        ).pack(side="left", padx=(6, 0))

        simulador = ttk.LabelFrame(
            quadro,
            text=TEXTOS["simulador"],
            padding=8,
        )
        simulador.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._construir_simulador(simulador)

    def _construir_cartao(self, pai: ttk.Frame, nome: str, coluna: int) -> None:
        cartao = ttk.LabelFrame(
            pai,
            text=TEXTOS[f"servico_{nome}"],
            padding=8,
        )
        cartao.grid(
            row=0,
            column=coluna,
            sticky="nsew",
            padx=(0, 6) if coluna == 0 else (6, 0),
        )
        cartao.columnconfigure(0, weight=1)

        status = ttk.Label(
            cartao,
            text=TEXTOS["estado_parado"],
            style="StatusParado.TLabel",
            font=("TkDefaultFont", 11, "bold"),
        )
        status.grid(row=0, column=0, sticky="w")
        self._status[nome] = status

        if nome == "core":
            ttk.Checkbutton(
                cartao,
                text=TEXTOS["agenda_demo"],
                variable=self._agenda_demo,
            ).grid(row=0, column=1, sticky="e")

        botoes = ttk.Frame(cartao)
        botoes.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        iniciar = ttk.Button(
            botoes,
            text=TEXTOS["iniciar"],
            command=lambda n=nome: self._iniciar(n),
        )
        iniciar.pack(side="left")
        parar = ttk.Button(
            botoes,
            text=TEXTOS["parar"],
            command=lambda n=nome: self._parar(n),
        )
        parar.pack(side="left", padx=(6, 0))
        reiniciar = ttk.Button(
            botoes,
            text=TEXTOS["reiniciar"],
            command=lambda n=nome: self._reiniciar(n),
        )
        reiniciar.pack(side="left", padx=(6, 0))
        self._botoes[nome] = {
            "iniciar": iniciar,
            "parar": parar,
            "reiniciar": reiniciar,
        }

    def _construir_simulador(self, pai: ttk.LabelFrame) -> None:
        """Botões que injetam eventos de sensor no core (ADR 015).

        Sem hardware os passos 2, 3 e 5 do fluxo não avançam — a gaveta e
        os slots só existem na ponte simulada. Os botões enviam o comando
        `simular` pelo mesmo socket da UI; com ponte real o core recusa (o
        sensor físico é a única fonte de verdade em produção).
        """
        ttk.Label(pai, text=TEXTOS["simulador_dica"]).pack(anchor="w")

        linha = ttk.Frame(pai)
        linha.pack(fill="x", pady=(6, 0))

        ttk.Label(linha, text=TEXTOS["simular_slot"]).pack(side="left")
        self._seletor_slot = ttk.Combobox(
            linha,
            state="readonly",
            width=4,
            values=[str(i) for i in range(SLOTS_PADRAO)],
        )
        self._seletor_slot.set("0")
        self._seletor_slot.pack(side="left", padx=(4, 12))

        acoes: tuple[tuple[str, str, bool], ...] = (
            (TEXTOS["simular_abrir_gaveta"], "gaveta_aberta", False),
            (TEXTOS["simular_fechar_gaveta"], "gaveta_fechada", False),
            (TEXTOS["simular_retirar"], "slot_ausente", True),
            (TEXTOS["simular_devolver"], "slot_presente", True),
        )
        for rotulo, evento, com_slot in acoes:
            botao = ttk.Button(
                linha,
                text=rotulo,
                command=lambda e=evento, c=com_slot, r=rotulo: self._simular(
                    e, c, r
                ),
            )
            botao.pack(side="left", padx=(0, 6))
            self._botoes_simulador.append(botao)

    def _simular(self, evento: str, com_slot: bool, rotulo: str) -> None:
        """Um botão do simulador foi clicado: envia e registra no log do core."""
        slot = self._slot_selecionado() if com_slot else None
        self._comandos.simular(evento, slot)
        if slot is None:
            self._registrar_linha(
                "core", "painel", texto("simulado", acao=rotulo)
            )
        else:
            self._registrar_linha(
                "core",
                "painel",
                texto("simulado_slot", acao=rotulo, slot=slot),
            )

    def _slot_selecionado(self) -> int:
        try:
            return int(self._seletor_slot.get())  # type: ignore[union-attr]
        except ValueError:  # pragma: no cover - combobox é readonly
            return 0

    def _construir_logs(self) -> None:
        caderno = ttk.Notebook(self._janela)
        caderno.grid(row=2, column=0, sticky="nsew", padx=12, pady=4)
        for nome in ("core", "ui"):
            self._construir_aba_log(caderno, nome)

    def _construir_aba_log(self, caderno: ttk.Notebook, nome: str) -> None:
        aba = ttk.Frame(caderno, padding=6)
        caderno.add(aba, text=TEXTOS[f"log_{nome}"])

        barra = ttk.Frame(aba)
        barra.pack(fill="x", pady=(0, 4))
        ttk.Label(barra, text=TEXTOS["filtrar"]).pack(side="left")
        filtro = tk.StringVar()
        ttk.Entry(barra, textvariable=filtro, width=32).pack(
            side="left", padx=(4, 10)
        )
        filtro.trace_add("write", lambda *_, n=nome: self._agendar_render(n))
        self._filtros[nome] = filtro

        auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            barra,
            text=TEXTOS["auto_rolagem"],
            variable=auto,
        ).pack(side="left")
        self._auto_rolagem[nome] = auto

        ttk.Button(
            barra,
            text=TEXTOS["salvar"],
            command=lambda n=nome: self._salvar(n),
        ).pack(side="right")
        ttk.Button(
            barra,
            text=TEXTOS["limpar"],
            command=lambda n=nome: self._limpar(n),
        ).pack(side="right", padx=(0, 6))

        area = ttk.Frame(aba)
        area.pack(fill="both", expand=True)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)

        widget = tk.Text(
            area,
            wrap="none",
            state="disabled",
            font=("TkFixedFont", 10),
            background="#0f172a",
            foreground="#e2e8f0",
            insertbackground="#e2e8f0",
            selectbackground="#334155",
            relief="flat",
            padx=6,
            pady=4,
        )
        barra_y = ttk.Scrollbar(area, orient="vertical", command=widget.yview)
        barra_x = ttk.Scrollbar(area, orient="horizontal", command=widget.xview)
        widget.configure(
            yscrollcommand=barra_y.set,
            xscrollcommand=barra_x.set,
        )
        widget.grid(row=0, column=0, sticky="nsew")
        barra_y.grid(row=0, column=1, sticky="ns")
        barra_x.grid(row=1, column=0, sticky="ew")

        widget.tag_configure("saida", foreground="#e2e8f0")
        widget.tag_configure("erro", foreground="#fca5a5")
        widget.tag_configure("painel", foreground="#93c5fd")
        self._widgets_log[nome] = widget

    def _construir_rodape(self) -> None:
        rodape = ttk.Frame(self._janela, padding=(12, 0, 12, 10))
        rodape.grid(row=3, column=0, sticky="ew")
        ttk.Label(
            rodape,
            text=texto("pasta_dev", caminho=DIR_DEV),
        ).pack(side="left")
        ttk.Label(
            rodape,
            text=texto("socket_core", caminho=DIR_DEV / "core.sock"),
        ).pack(side="right")

        avisos = avisos_ambiente()
        if avisos:
            mensagens = [texto(f"aviso_{aviso}") for aviso in avisos]
            ttk.Label(
                rodape,
                text=" ".join(mensagens),
                style="StatusAtencao.TLabel",
            ).pack(side="left", padx=(16, 0))

    # --- ciclo de vida -----------------------------------------------------

    def executar(self) -> None:
        self._janela.mainloop()

    def _fechar(self) -> None:
        if not messagebox.askyesno(
            TEXTOS["titulo_fechar"],
            TEXTOS["aviso_fechar"],
            parent=self._janela,
        ):
            return
        self._fechando = True
        self._janela.config(cursor="watch")
        self._janela.update_idletasks()
        for servico in self._servicos.values():
            try:
                servico.parar_sincrono(timeout_s=10.0)
            except Exception:
                pass
        self._janela.destroy()

    # --- eventos das threads ----------------------------------------------

    def _drenar_eventos(self) -> None:
        if self._fechando:
            return
        try:
            while True:
                evento = self._fila.get_nowait()
                tipo = evento[0]
                if tipo == "log":
                    _, nome, fluxo, mensagem = evento
                    if nome in self._buffers:
                        self._registrar_linha(
                            str(nome), str(fluxo), str(mensagem)
                        )
                elif tipo == "estado":
                    _, nome = evento
                    if nome in self._status:
                        self._atualizar_status(str(nome))
                elif tipo == "acao":
                    _, nome = evento
                    self._em_parada.discard(str(nome))
                    self._em_reinicio.discard(str(nome))
                    if nome in self._status:
                        self._atualizar_status(str(nome))
        except queue.Empty:
            pass
        self._janela.after(_INTERVALO_FILA_MS, self._drenar_eventos)

    def _registrar_linha(self, nome: str, fluxo: str, mensagem: str) -> None:
        linha = self._buffers[nome].adicionar(nome, fluxo, mensagem)
        if self._corresponde_ao_filtro(nome, linha):
            widget = self._widgets_log[nome]
            widget.configure(state="normal")
            widget.insert(
                "end",
                formatar(linha) + "\n",
                (_tag_do_fluxo(fluxo),),
            )
            widget.configure(state="disabled")
            if self._auto_rolagem[nome].get():
                widget.see("end")

    def _corresponde_ao_filtro(self, nome: str, linha: LinhaLog) -> bool:
        termo = self._filtros[nome].get().strip().casefold()
        if not termo:
            return True
        return termo in formatar(linha).casefold()

    def _agendar_render(self, nome: str) -> None:
        anterior = self._render_agendado[nome]
        if anterior is not None:
            try:
                self._janela.after_cancel(anterior)
            except tk.TclError:
                pass
        self._render_agendado[nome] = self._janela.after(
            _DEBOUNCE_FILTRO_MS,
            lambda n=nome: self._renderizar(n),
        )

    def _renderizar(self, nome: str) -> None:
        self._render_agendado[nome] = None
        termo = self._filtros[nome].get()
        linhas = self._buffers[nome].filtrar(termo)
        widget = self._widgets_log[nome]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for linha in linhas:
            widget.insert(
                "end",
                formatar(linha) + "\n",
                (_tag_do_fluxo(linha.fluxo),),
            )
        widget.configure(state="disabled")
        if self._auto_rolagem[nome].get():
            widget.see("end")

    # --- ações dos botões --------------------------------------------------

    def _iniciar(self, nome: str) -> None:
        if nome in self._em_parada or nome in self._em_reinicio:
            return
        servico = self._servicos[nome]
        if nome == "core" and not servico.ativo:
            if self._agenda_demo.get():
                agenda = gerar_agenda_demo()
                servico.ambiente["DISPENSER_AGENDA_JSON"] = str(agenda.caminho)
                self._registrar_linha(
                    nome,
                    "painel",
                    texto("agenda_demo_gerada", horario=agenda.horario),
                )
            else:
                servico.ambiente.pop("DISPENSER_AGENDA_JSON", None)

        try:
            servico.iniciar()
        except JaRodando as erro:
            self._registrar_linha(nome, "painel", str(erro))
        except FalhaAoIniciar:
            # O próprio serviço já publicou a linha de erro e o estado.
            pass
        self._atualizar_status(nome)

    def _parar(self, nome: str) -> None:
        if nome in self._em_parada or nome in self._em_reinicio:
            return
        self._em_parada.add(nome)
        threading.Thread(
            target=self._parar_em_thread,
            args=(nome,),
            name=f"painel-parar-{nome}",
            daemon=True,
        ).start()

    def _parar_em_thread(self, nome: str) -> None:
        try:
            self._servicos[nome].parar_sincrono(timeout_s=10.0)
        except Exception as erro:  # pragma: no cover - defesa da thread
            self._fila.put(
                ("log", nome, "erro", texto("erro_parar", erro=erro))
            )
        finally:
            self._fila.put(("acao", nome))

    def _reiniciar(self, nome: str) -> None:
        if nome in self._em_reinicio or nome in self._em_parada:
            return
        self._em_reinicio.add(nome)
        threading.Thread(
            target=self._reiniciar_em_thread,
            args=(nome,),
            name=f"painel-reiniciar-{nome}",
            daemon=True,
        ).start()

    def _reiniciar_em_thread(self, nome: str) -> None:
        servico = self._servicos[nome]
        try:
            servico.parar_sincrono(timeout_s=10.0)
            servico.iniciar()
        except (JaRodando, FalhaAoIniciar):
            pass
        except Exception as erro:  # pragma: no cover - defesa da thread
            self._fila.put(
                ("log", nome, "erro", texto("erro_reiniciar", erro=erro))
            )
        finally:
            self._fila.put(("acao", nome))

    def _iniciar_tudo(self) -> None:
        for nome in self._servicos:
            self._iniciar(nome)

    def _parar_tudo(self) -> None:
        for nome in self._servicos:
            self._parar(nome)

    # --- status ------------------------------------------------------------

    def _atualizar_todos_status(self) -> None:
        for nome in self._servicos:
            self._atualizar_status(nome)

    def _atualizar_status(self, nome: str) -> None:
        servico = self._servicos[nome]
        estado = servico.estado

        if estado is EstadoServico.PARADO:
            rotulo = TEXTOS["estado_parado"]
            estilo = "StatusParado.TLabel"
        elif estado is EstadoServico.INICIANDO:
            rotulo = TEXTOS["estado_iniciando"]
            estilo = "StatusAtencao.TLabel"
        elif estado is EstadoServico.RODANDO:
            rotulo = texto("estado_rodando", pid=servico.pid or "?")
            estilo = "StatusRodando.TLabel"
        elif estado is EstadoServico.PARANDO:
            rotulo = TEXTOS["estado_parando"]
            estilo = "StatusAtencao.TLabel"
        else:
            if servico.codigo_saida is None:
                rotulo = TEXTOS["estado_encerrado_sem_codigo"]
            else:
                rotulo = texto("estado_encerrado", codigo=servico.codigo_saida)
            if servico.codigo_saida == 3:
                rotulo = f"{rotulo} — {TEXTOS['dica_codigo_3']}"
            if servico.erro:
                rotulo = f"{rotulo}: {servico.erro}"
            estilo = "StatusErro.TLabel"

        self._status[nome].configure(text=rotulo, style=estilo)
        botoes = self._botoes[nome]
        pode_iniciar = estado in (EstadoServico.PARADO, EstadoServico.ENCERRADO)
        pode_parar = estado in (EstadoServico.RODANDO, EstadoServico.INICIANDO)
        pode_reiniciar = estado in (EstadoServico.RODANDO, EstadoServico.ENCERRADO)
        botoes["iniciar"].configure(
            state="normal" if pode_iniciar else "disabled"
        )
        botoes["parar"].configure(state="normal" if pode_parar else "disabled")
        botoes["reiniciar"].configure(
            state="normal" if pode_reiniciar else "disabled"
        )
        if nome == "core":
            # O simulador fala com o core pelo socket: só faz sentido (e só
            # evita erros de conexão) com o processo de pé.
            pode_simular = estado is EstadoServico.RODANDO
            estado_simulador = "normal" if pode_simular else "disabled"
            for botao in self._botoes_simulador:
                botao.configure(state=estado_simulador)
            if self._seletor_slot is not None:
                self._seletor_slot.configure(
                    state="readonly" if pode_simular else "disabled"
                )

    # --- log: limpar e salvar ---------------------------------------------

    def _limpar(self, nome: str) -> None:
        self._buffers[nome].limpar()
        self._renderizar(nome)

    def _salvar(self, nome: str) -> None:
        conteudo = self._buffers[nome].texto(self._filtros[nome].get())
        caminho = filedialog.asksaveasfilename(
            parent=self._janela,
            title=TEXTOS["salvar"],
            defaultextension=".log",
            filetypes=[
                (TEXTOS["tipo_log"], "*.log"),
                (TEXTOS["tipo_todos"], "*.*"),
            ],
            initialfile=(
                f"dispenser-{nome}-{datetime.now():%Y%m%d-%H%M%S}.log"
            ),
        )
        if not caminho:
            return
        try:
            Path(caminho).write_text(conteudo, encoding="utf-8")
        except OSError as erro:
            messagebox.showerror(
                TEXTOS["titulo_erro"],
                texto("erro_salvar", erro=erro),
                parent=self._janela,
            )
            return
        messagebox.showinfo(
            TEXTOS["titulo_log_salvo"],
            texto("log_salvo", caminho=caminho),
            parent=self._janela,
        )


def main() -> None:
    """Ponto de entrada de `python -m painel`."""
    preparar_diretorio_dev()
    fila: queue.Queue[tuple] = queue.Queue()
    servicos = {
        "core": Servico(
            "core",
            comando_core(),
            RAIZ,
            ambiente_core(),
            fila.put,
        ),
        "ui": Servico(
            "ui",
            comando_ui(),
            PASTA_UI,
            ambiente_ui(),
            fila.put,
        ),
    }
    aplicacao = Aplicacao(servicos, fila)
    aplicacao.executar()
