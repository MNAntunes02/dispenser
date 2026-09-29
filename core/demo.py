"""Demonstração do fluxo completo no simulador (sem hardware).

Executa o coordenador com ponte simulada e agenda uma dose para daqui a
alguns segundos. Com `--socket`, sobe o mesmo socket da Fase 5 e conecta
nele uma "mini UI" que faz exatamente o que a UI Flutter faz: ler as telas
publicadas e responder `input:confirma` quando o core pede um OK.

Uso:
    python -m core.demo              # só imprime as telas
    python -m core.demo --socket     # o OK do paciente sai pelo socket
"""

from __future__ import annotations

import argparse
import json
import socket
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from core.agendador import abrev_dia_semana
from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador
from core.servidor_ui import ServidorUI
from hardware.bridge.bridge_simulada import PonteSimulada

SOCKET_DEMO = Path("/run/dispenser/demo.sock")

#: Sensor que o paciente provoca em cada passo do fluxo feliz.
SCRIPT: dict[str, object] = {
    "hora_remedio": None,  # a mini UI responde com OK
    "abra_gaveta": {"e": "gaveta_aberta"},
    "retire_medicamento": {"e": "slot_ausente", "slot": 0},
    "tome_e_ok": None,  # a mini UI responde com OK
    "devolva_slot": [{"e": "slot_presente", "slot": 0}, {"e": "gaveta_fechada"}],
}


class PublicadorEspiao:
    """Acumula as mensagens (para o roteiro) e as repassa ao socket da UI."""

    def __init__(self) -> None:
        self.mensagens: list[dict] = []
        self.destino: object | None = None

    def publicar(self, msg: dict) -> None:
        self.mensagens.append(msg)
        if self.destino is not None:
            self.destino.publicar(msg)


class MiniUI:
    """Cliente do socket que só exibe telas e devolve o botão OK.

    Espelha o comportamento do `dispenser-ui`: nunca decide o estado da
    dose, apenas lê o que o core publica e envia a intenção do paciente.
    """

    def __init__(self, caminho: Path) -> None:
        self._caminho = caminho
        self._parar = threading.Event()
        self._thread = threading.Thread(target=self._rodar, name="mini-ui", daemon=True)

    def iniciar(self) -> None:
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        self._thread.join(timeout=2.0)

    def _rodar(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        deadline = time.monotonic() + 5
        while not self._parar.is_set() and time.monotonic() < deadline:
            try:
                sock.connect(str(self._caminho))
                break
            except OSError:
                time.sleep(0.05)
        buffer = b""
        try:
            while not self._parar.is_set():
                try:
                    pedaco = sock.recv(4096)
                except socket.timeout:
                    continue
                if not pedaco:
                    return
                buffer += pedaco
                partes = buffer.split(b"\n")
                buffer = partes.pop()
                for bruta in partes:
                    if bruta.strip():
                        self._tratar(json.loads(bruta.decode("utf-8")), sock)
        except OSError:
            return
        finally:
            sock.close()

    def _tratar(self, msg: dict, sock: socket.socket) -> None:
        if msg.get("type") != "estado":
            return
        print(f"[UI] {msg.get('mensagem')}", flush=True)
        if msg.get("esperaBotao"):
            sock.sendall(b'{"v":1,"type":"input","acao":"confirma"}\n')


def _agenda_para_hora(horario: str) -> list[dict]:
    return [
        {
            "id": "med-demo",
            "nome": "Medicamento de exemplo",
            "dosagem": "1 comprimido",
            "dias": [
                {
                    "dia_semana": abrev_dia_semana(datetime.now().date()),
                    "horario": [horario],
                }
            ],
        }
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Demonstra o fluxo de dose no simulador")
    parser.add_argument(
        "--socket",
        nargs="?",
        const=str(SOCKET_DEMO),
        default=None,
        help="sobe o socket da UI (padrão: %(const)s) e conecta a mini UI",
    )
    parser.add_argument(
        "--sem-mini-ui",
        action="store_true",
        help="sobe o socket mas não conecta a mini UI (usado pelo teste da UI real)",
    )
    args = parser.parse_args()

    agora = datetime.now().replace(second=0, microsecond=0)
    horario = (agora + timedelta(seconds=5)).strftime("%H:%M")
    config = Config(
        tick_s=0.2,
        intervalo_alarme_s=120,
        max_tentativas=5,
        timeout_gaveta_s=120,
        timeout_retorno_s=120,
        limite_retorno_s=1800,
    )
    db = Database(Path(tempfile.mkdtemp(prefix="dispenser-demo-")) / "demo.db")
    ponte = PonteSimulada()
    pub = PublicadorEspiao()
    coord = Coordenador(
        config,
        db,
        AgendaMemo(_agenda_para_hora(horario)),
        ponte,
        publicador_ui=pub,
    )
    coord.conectar()

    servidor = None
    mini_ui = None
    if args.socket:
        servidor = ServidorUI(args.socket, retrato=coord.retrato_cache)
        servidor.iniciar()
        # o espião publica no core e repassa no socket: o roteiro continua
        # vendo tudo o que a UI vê
        pub.destino = servidor
        coord.definir_ui(servidor)
        if not args.sem_mini_ui:
            mini_ui = MiniUI(Path(args.socket))
            mini_ui.iniciar()
            print(f"▶ mini UI conectada em {servidor.caminho}", flush=True)
        else:
            print(f"▶ socket pronto em {servidor.caminho} (sem mini UI)", flush=True)
    print(f"▶ dose agendada para {horario} (aguardando ~5s)", flush=True)

    processadas = 0
    try:
        while True:
            coord.tick()
            novas = pub.mensagens[processadas:]
            # avança só pelas mensagens vistas agora: o roteiro pode publicar
            # a próxima tela durante o laço e ela precisa ser lida no tick seguinte
            processadas += len(novas)
            for msg in novas:
                chave = msg.get("chave")
                if chave is None:
                    continue
                passo = msg.get("passo")
                rotulo = f"passo {passo}" if passo else chave
                print(f"▶ {rotulo}: {msg['mensagem']}", flush=True)
                if chave == "tudo_certo":
                    print("✓ fluxo concluído no simulador", flush=True)
                    time.sleep(2.0)
                    return
                acao = SCRIPT.get(chave)
                if acao is None:
                    continue  # a mini UI responde o OK
                for evento in acao if isinstance(acao, list) else [acao]:
                    ponte.simular(evento)
            if servidor is not None:
                servidor.aguardar_proxima(config.tick_s)
            else:
                time.sleep(config.tick_s)
    finally:
        if mini_ui is not None:
            mini_ui.parar()
        if servidor is not None:
            servidor.parar()
        coord.finalizar()


if __name__ == "__main__":
    main()
