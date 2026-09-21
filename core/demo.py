"""Demonstração do fluxo completo no simulador (sem hardware).

Executa o coordenador com ponte simulada e relógio real, agenda uma dose
para daqui a alguns segundos e injeta os eventos de usuário na ordem do
fluxo feliz, imprimindo as mensagens de tela produzidas.

Uso: python -m core.demo
"""

from __future__ import annotations

import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from core.agendador import abrev_dia_semana
from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador, PublicadorLog
from hardware.bridge.bridge_simulada import PonteSimulada


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
    pub = PublicadorLog()
    ponte = PonteSimulada()
    coord = Coordenador(
        config,
        db,
        AgendaMemo(_agenda_para_hora(horario)),
        ponte,
        publicador_ui=pub,
    )
    coord.conectar()
    print(f"▶ dose agendada para {horario} (aguardando ~5s)", flush=True)

    script = {
        "hora_remedio": ("botao", None),
        "abra_gaveta": ("gaveta_aberta", None),
        "retire_medicamento": ("slot_ausente", {"slot": 0}),
        "tome_e_ok": ("botao", None),
        "devolva_slot": [("slot_presente", {"slot": 0}), ("gaveta_fechada", None)],
    }
    processadas = 0
    try:
        while True:
            coord.tick()
            novas = pub.mensagens[processadas:]
            for msg in novas:
                chave = msg.get("chave")
                if chave is None:
                    continue
                print(f"▶ tela: {msg['mensagem']}", flush=True)
                if chave == "tudo_certo":
                    print("✓ fluxo concluído no simulador", flush=True)
                    time.sleep(0.5)
                    return
                passos = script.get(chave)
                if passos is None:
                    continue
                if isinstance(passos, list):
                    for e, d in passos:
                        ponte.simular({"e": e, **(d or {})})
                else:
                    e, d = passos
                    ponte.simular({"e": e, **(d or {})})
            processadas = len(pub.mensagens)
            time.sleep(config.tick_s)
    finally:
        coord.finalizar()


if __name__ == "__main__":
    main()