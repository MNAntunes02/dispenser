"""Entrypoint do dispenser-core (executável `dispenser-core`).

Monta Config + banco + coordenador + ponte e roda o loop de `tick`.
Sem backend ainda (Fase 3): a agenda pode vir de `DISPENSER_AGENDA_JSON`
(demonstração) ou ser vazia. Ponte simulada até a Fase 4.
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


def main() -> None:
    config = Config.de_env()
    caminho_db = Path(os.environ.get("DISPENSER_DB_PATH", str(PADRAO_ESTADO)))
    db = Database(caminho_db)
    db.conectar()

    coord = Coordenador(
        config,
        db,
        AgendaMemo(_agenda_inicial()),
        PonteSimulada(),
        publicador_ui=PublicadorLog(),
    )
    coord.conectar()
    print("dispenser-core: iniciado (ponte simulada; backend na Fase 3)", flush=True)

    parar = False

    def _finaliza(sinal, _quadro):
        nonlocal parar
        parar = True

    signal.signal(signal.SIGTERM, _finaliza)
    signal.signal(signal.SIGINT, _finaliza)

    try:
        while not parar:
            coord.tick()
            coord.tentar_envio()
            time.sleep(config.tick_s)
    finally:
        coord.finalizar()
        print("dispenser-core: encerrado", flush=True)


if __name__ == "__main__":
    main()