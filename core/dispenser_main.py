"""Entrypoint do dispenser-core (executável `dispenser-core`).

Monta Config + banco + coordenador + ponte e roda o loop de `tick`.
Fase 3: com credencial própria configurada, a agenda vem da nuvem (Firestore)
via `Sincronizador` + `FonteAgendaLocal`; sem ela, mantém `DISPENSER_AGENDA_JSON`
(demonstração). Ponte simulada até a Fase 4.
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
from core.sync import FonteAgendaLocal, Sincronizador
from core.transporte import TransporteFirestore
from hardware.bridge.bridge_simulada import PonteSimulada

PADRAO_ESTADO = Path("/var/lib/dispenser/state.db")


def _agenda_inicial() -> list[dict]:
    caminho = os.environ.get("DISPENSER_AGENDA_JSON")
    if not caminho:
        return []
    try:
        with open(caminho, encoding="utf-8") as fh:
            dados = json.load(fh)
    except (OSError, ValueError) as erro:
        print(f"dispenser-core: agenda de demonstração inválida: {erro}", file=sys.stderr)
        return []
    return dados if isinstance(dados, list) else [dados]


def _ler_credenciais(caminho: Path) -> dict | None:
    try:
        with open(caminho, encoding="utf-8") as fh:
            dados = json.load(fh)
    except (OSError, ValueError) as erro:
        print(f"dispenser-core: credencial inválida em {caminho}: {erro}", file=sys.stderr)
        return None
    email, senha = dados.get("email"), dados.get("senha")
    if not email or not senha:
        print("dispenser-core: credencial sem email/senha", file=sys.stderr)
        return None
    return {"email": email, "senha": senha}


def _transporte_de_env() -> dict | None:
    """Constrói o transporte se a configuração da Fase 3 estiver presente."""
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


def main() -> None:
    config = Config.de_env()
    caminho_db = Path(os.environ.get("DISPENSER_DB_PATH", str(PADRAO_ESTADO)))
    db = Database(caminho_db)
    db.conectar()

    transporte_cfg = _transporte_de_env()
    if transporte_cfg is not None:
        sincronizador = Sincronizador(db, TransporteFirestore(**transporte_cfg))
        coord = Coordenador(
            config,
            db,
            FonteAgendaLocal(db),
            PonteSimulada(),
            publicador_ui=PublicadorLog(),
        )
        print("dispenser-core: iniciado (agenda via Firestore; ponte simulada)", flush=True)
    else:
        sincronizador = None
        coord = Coordenador(
            config,
            db,
            AgendaMemo(_agenda_inicial()),
            PonteSimulada(),
            publicador_ui=PublicadorLog(),
        )
        print("dispenser-core: iniciado (ponte simulada; sem backend)", flush=True)
    coord.conectar()

    parar = False

    def _finaliza(sinal, _quadro):
        nonlocal parar
        parar = True

    signal.signal(signal.SIGTERM, _finaliza)
    signal.signal(signal.SIGINT, _finaliza)

    ultimo_sync = 0.0
    try:
        while not parar:
            coord.tick()
            coord.tentar_envio()
            if sincronizador is not None:
                agora = time.monotonic()
                if agora - ultimo_sync >= config.intervalo_sync_s:
                    ultimo_sync = agora
                    try:
                        sincronizador.ciclo()
                    except Exception as erro:
                        print(f"dispenser-core: sync falhou: {erro}", file=sys.stderr)
            time.sleep(config.tick_s)
    finally:
        coord.finalizar()
        print("dispenser-core: encerrado", flush=True)


if __name__ == "__main__":
    main()