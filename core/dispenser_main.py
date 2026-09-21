"""Entrypoint do dispenser-core (executável `dispenser-core`).

Esqueleto da Fase 1: inicializa armazenamento e registra os serviços.
A coordenação completa (agendador + máquina de estados + ponte + sync +
notificador + socket core/UI) é montada nas Fases 2 e 3.
"""

from __future__ import annotations

import os
from pathlib import Path

from core.armazenamento import Database

PADRAO_ESTADO = Path("/var/lib/dispenser/state.db")


def main() -> None:
    caminho_db = Path(
        os.environ.get("DISPENSER_DB_PATH", str(PADRAO_ESTADO))
    )
    db = Database(caminho_db)
    db.conectar()
    try:
        print("dispenser-core: esqueleto da Fase 1 iniciado", flush=True)
    finally:
        db.fechar()


if __name__ == "__main__":
    main()