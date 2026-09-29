"""Entrypoint do dispenser-core (executável `dispenser-core`).

Monta Config + banco + coordenador + ponte e roda o loop de `tick`.
Fase 3: com credencial própria configurada, a agenda vem da nuvem (Firestore)
via `Sincronizador` + `FonteAgendaLocal`; sem ela, mantém `DISPENSER_AGENDA_JSON`
(demonstração). Ponte simulada até a Fase 4.

Fase 7 (boot e robustez) acrescenta o que o sistema operacional exige:
- **fuso do paciente** aplicado no processo (`core/relogio.py`): a agenda não
  pode depender do fuso do SO;
- **instância única** por `flock`: dois cores no mesmo banco disparariam alarmes
  fora de hora;
- **watchdog** para o systemd (`core/saude.py`): se o loop travar, o systemd
  reinicia o processo;
- **recarga do provisionamento**: o app pareia por Bluetooth depois que o core
  já está no ar; com `SIGHUP` (ou com o arquivo de configuração aparecendo) o
  core passa a sincronizar sem precisar reiniciar.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador, PublicadorLog
from core.instancia import JaExisteInstancia, TravaDeInstancia
from core.relogio import aplicar_fuso_com_padrao
from core.saude import NotificadorSaude
from core.servidor_ui import ServidorUI
from core.sync import FonteAgendaLocal, Sincronizador
from core.transporte import TransporteFirestore
from hardware.bridge.bridge_simulada import PonteSimulada

PADRAO_ESTADO = Path("/var/lib/dispenser/state.db")
PADRAO_ENV = Path("/var/lib/dispenser/dispenser.env")
PADRAO_SOCKET = Path("/run/dispenser/core.sock")

#: Código de saída quando outro core já está rodando (systemdRestart=on-failure
#: não entra em laço; o log do journald mostra a causa).
SAIDA_INSTANCIA_DUPLICADA = 3


def _log(mensagem: str) -> None:
    print(f"dispenser-core: {mensagem}", flush=True)


def _erro(mensagem: str) -> None:
    print(f"dispenser-core: {mensagem}", file=sys.stderr, flush=True)


def _carregar_env_arquivo(forcar: bool = False) -> list[str]:
    """Sobe para o ambiente as variáveis provisionadas via Bluetooth (Fase 3b).

    O arquivo (permissão 600) contém FIREBASE_PROJECT_ID,
    DISPENSER_FIREBASE_API_KEY e DISPENSER_USER_ID.

    No boot (`forcar=False`) o ambiente do systemd tem precedência, para o
    instalador poder sobrepor valores numa emergência sem editar o arquivo.

    Na recarga por SIGHUP (`forcar=True`) o arquivo vence: ele foi reescrito
    pelo provisionamento **depois** do boot, e manter o valor antigo seria
    deixar o aparelho apontando para um backend que o paciente não usa mais.
    Sem estado global entre chamadas — quem chama decide o precedente.

    Devolve as chaves efetivamente alteradas, para o chamador saber se precisa
    reconstruir transporte/agenda.
    """
    caminho = Path(os.environ.get("DISPENSER_ENV_PATH", str(PADRAO_ENV)))
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    alteradas: list[str] = []
    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip()
        if not forcar and chave in os.environ:
            continue  # precedência do ambiente do systemd
        if os.environ.get(chave) == valor:
            continue
        os.environ[chave] = valor
        alteradas.append(chave)
    return alteradas


def _mtime_env() -> float | None:
    """Última alteração do arquivo de provisionamento (para saber se mudou)."""
    caminho = Path(os.environ.get("DISPENSER_ENV_PATH", str(PADRAO_ENV)))
    try:
        return caminho.stat().st_mtime
    except OSError:
        return None


#: Chaves do arquivo de provisionamento que exigem refazer o transporte.
_CHAVES_CRITICAS = (
    "FIREBASE_PROJECT_ID",
    "DISPENSER_USER_ID",
    "DISPENSER_FIREBASE_API_KEY",
    "DISPENSER_CREDENTIALS_PATH",
)


def _agenda_inicial() -> list[dict]:
    caminho = os.environ.get("DISPENSER_AGENDA_JSON")
    if not caminho:
        return []
    try:
        with open(caminho, encoding="utf-8") as fh:
            dados = json.load(fh)
    except (OSError, ValueError) as erro:
        _erro(f"agenda de demonstração inválida: {erro}")
        return []
    return dados if isinstance(dados, list) else [dados]


def _ler_credenciais(caminho: Path) -> dict | None:
    try:
        with open(caminho, encoding="utf-8") as fh:
            dados = json.load(fh)
    except (OSError, ValueError) as erro:
        _erro(f"credencial inválida em {caminho}: {erro}")
        return None
    email, senha = dados.get("email"), dados.get("senha")
    if not email or not senha:
        _erro("credencial sem email/senha")
        return None
    return {"email": email, "senha": senha}


def _transporte_de_env() -> dict | None:
    """Monta a configuração do transporte se a Fase 3 estiver presente."""
    projeto = os.environ.get("FIREBASE_PROJECT_ID")
    usuario_id = os.environ.get("DISPENSER_USER_ID")
    api_key = os.environ.get("DISPENSER_FIREBASE_API_KEY")
    caminho = os.environ.get("DISPENSER_CREDENTIALS_PATH")
    if not (projeto and usuario_id and api_key and caminho):
        return None
    credencial = _ler_credenciais(Path(caminho))
    if credencial is None:
        return None
    return {
        "projeto": projeto,
        "usuario_id": usuario_id,
        "api_key": api_key,
        **credencial,
    }


def _subir_servidor_ui(coord: Coordenador) -> ServidorUI | None:
    """Sobe o socket da UI (Fase 5). Sem socket, o core segue funcionando.

    A UI é opcional por desenho: o paciente pode tomar a dose guiado só pelo
    alarme/LEDs, e uma UI quebrada nunca impede o fluxo de dose.
    """
    caminho = Path(os.environ.get("DISPENSER_SOCKET", str(PADRAO_SOCKET)))
    servidor = ServidorUI(
        caminho,
        retrato=coord.retrato_cache,
        intervalo_health_s=float(os.environ.get("DISPENSER_UI_HEALTH_S", "2")),
    )
    try:
        servidor.iniciar()
    except (OSError, RuntimeError) as erro:
        _erro(f"UI não disponível em {caminho}: {erro}")
        return None
    coord.definir_publicador_ui(servidor)
    coord.definir_ui(servidor)
    return servidor


def _montar_agenda(db: Database) -> tuple[object, Sincronizador | None]:
    """Escolhe a fonte da agenda: nuvem provisionada ou agenda de demonstração."""
    transporte_cfg = _transporte_de_env()
    if transporte_cfg is None:
        return AgendaMemo(_agenda_inicial()), None
    return FonteAgendaLocal(db), Sincronizador(
        db, TransporteFirestore(**transporte_cfg)
    )


def _aplicar_provisionamento(coord: Coordenador, db: Database) -> bool:
    """Relê o arquivo provisionado e passa a agenda a vir da nuvem.

    Não derruba a dose em andamento: só troca a fonte das próximas
    ocorrências. Se o pareamento ainda estiver incompleto, mantém a fonte atual
    — trocar a agenda de uma que funciona por uma vazia seria pior que esperar.
    """
    alteradas = _carregar_env_arquivo(forcar=True)
    db.purgar_logs()
    if not any(chave in alteradas for chave in _CHAVES_CRITICAS):
        _log("provisionamento sem mudança relevante; mantendo a agenda")
        return False
    fonte, sincronizador = _montar_agenda(db)
    if sincronizador is None:
        _erro("provisionamento ainda incompleto; mantendo a agenda anterior")
        return False
    coord.definir_agenda_fonte(fonte)
    coord.definir_envio_outbox(sincronizador.enviar_item)
    _log("provisionamento aplicado: agenda via Firestore")
    return True


def main() -> None:
    trava = TravaDeInstancia(os.environ.get("DISPENSER_LOCK_PATH") or None)
    try:
        trava.adquirir()
    except JaExisteInstancia as erro:
        _erro(str(erro))
        raise SystemExit(SAIDA_INSTANCIA_DUPLICADA)

    try:
        _rodar()
    finally:
        trava.liberar()


def _rodar() -> None:
    _carregar_env_arquivo()
    config = Config.de_env()
    fuso, fuso_ok = aplicar_fuso_com_padrao(config.fuso)
    if not fuso_ok:
        _erro(f"fuso configurado inválido; usando {fuso}")
    _log(f"iniciado (fuso {fuso})")

    caminho_db = Path(os.environ.get("DISPENSER_DB_PATH", str(PADRAO_ESTADO)))
    db = Database(caminho_db, retencao_log_dias=config.retencao_log_dias)
    db.conectar()
    removidos = db.purgar_logs()
    if removidos:
        _log(f"trilha local: {removidos} registros antigos removidos")

    fonte_agenda, sincronizador = _montar_agenda(db)
    if sincronizador is None:
        _log("ponte simulada; sem backend (aguardando provisionamento)")
    else:
        _log("ponte simulada; agenda via Firestore")
    coord = Coordenador(
        config,
        db,
        fonte_agenda,
        PonteSimulada(),
        publicador_ui=PublicadorLog(),
    )
    coord.conectar()
    if sincronizador is not None:
        # Só existe entrega com o provisionamento feito; sem ele a outbox
        # acumula e é enviada assim que o app parear.
        coord.definir_envio_outbox(sincronizador.enviar_item)
    servidor = _subir_servidor_ui(coord)
    if servidor is not None:
        _log(f"UI em {servidor.caminho}")

    saude = NotificadorSaude(
        intervalo_s=float(os.environ.get("DISPENSER_WATCHDOG_S", "15")),
        ao_falhar=lambda motivo: _erro(f"watchdog indisponível ({motivo}); seguindo"),
    )
    saude.iniciar("core no ar")

    parar = False
    recarregar = False

    def _finaliza(sinal, _quadro):
        nonlocal parar
        parar = True

    def _recarrega(sinal, _quadro):
        # O app acabou de parear por Bluetooth: lê a configuração nova sem
        # derrubar a dose em andamento.
        nonlocal recarregar
        recarregar = True

    signal.signal(signal.SIGTERM, _finaliza)
    signal.signal(signal.SIGINT, _finaliza)
    signal.signal(signal.SIGHUP, _recarrega)

    ultimo_sync = 0.0
    mtime_env = _mtime_env()
    try:
        while not parar:
            coord.tick()
            coord.tentar_envio()
            agora = time.monotonic()
            if sincronizador is not None and agora - ultimo_sync >= config.intervalo_sync_s:
                ultimo_sync = agora
                try:
                    sincronizador.ciclo()
                except Exception as erro:  # rede: a fila fica pendente
                    _erro(f"sync falhou: {erro}")
            if recarregar or _mtime_env() != mtime_env:
                recarregar = False
                mtime_env = _mtime_env()
                _aplicar_provisionamento(coord, db)
            else:
                db.purgar_logs()
            saude.pulso()
            if servidor is not None:
                # Dorme até a UI mandar algo (botão) ou passar o tick.
                servidor.aguardar_proxima(config.tick_s)
            else:
                time.sleep(config.tick_s)
    finally:
        saude.parar("encerrando")
        saude.fechar()
        if servidor is not None:
            servidor.parar()
        coord.finalizar()
        _log("encerrado")


if __name__ == "__main__":
    main()
