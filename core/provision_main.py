"""Entrypoint de provisionamento (executável `dispenser-provision`).

Roda no 1º boot (ou reforçado por CLI/botão) enquanto não existir
`/var/lib/dispenser/dispenser.env`: inicia o BLE/GATT, mostra o código na tela,
recebe Wi-Fi + config Firebase do app, valida, aplica a rede e persiste a
configuração. Ao sair, o systemd (Fase 7) reinicia `dispenser-core`, que aí já
sincroniza com o backend de forma normal.

Sem Pi/placa, use `--simulado` (dev/demo): GATT, rede e tela em memória.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path

from core.provisionamento import ARQUIVO_ENV_PADRAO, Provisionador
from hardware.gatt.bluez_servico import ServicoGattBlueZ
from hardware.gatt.servico_gatt import ServicoGattSimulado
from hardware.tela import TelaSimulada, TelaTerminal
from rede.rede import RedeLinux, RedeSimulada


def _ler_uid(caminho: Path) -> str:
    """UID do Firebase do dispensador, anotado na credencial 600 (Fase 3)."""
    try:
        with open(caminho, encoding="utf-8") as fh:
            dados = json.load(fh)
        uid = dados.get("uid")
    except (OSError, ValueError):
        uid = None
    return uid if isinstance(uid, str) else ""


def _montar(args: argparse.Namespace, prov: Provisionador):
    if args.simulado or os.environ.get("DISPENSER_GATT_SIMULADO") == "1":
        gatt = ServicoGattSimulado()
        tela = TelaSimulada()
    else:
        gatt = ServicoGattBlueZ(prov.identidade()["nome"])
        tela = TelaTerminal()
    gatt.iniciar(prov)
    return gatt, tela


def main() -> int:
    parser = argparse.ArgumentParser(prog="dispenser-provision")
    parser.add_argument("--simulado", action="store_true", help="sem hardware (dev/demo)")
    parser.add_argument(
        "--caminho-env",
        default=os.environ.get("DISPENSER_ENV_PATH", str(ARQUIVO_ENV_PADRAO)),
        help="onde gravar a configuração provisionada",
    )
    parser.add_argument(
        "--credencial",
        default=os.environ.get("DISPENSER_CREDENTIALS_PATH", ""),
        help="arquivo 600 com email/senha/uid do dispensador",
    )
    args = parser.parse_args()

    nome = socket.gethostname().split(".")[0][:10] or "dispenser"
    caminho_env = Path(args.caminho_env)
    if args.simulado or os.environ.get("DISPENSER_GATT_SIMULADO") == "1":
        rede, tela = RedeSimulada(), TelaSimulada()
    else:
        rede, tela = RedeLinux(), TelaTerminal()

    prov = Provisionador(
        rede=rede,
        tela=tela,
        caminho_env=caminho_env,
        uid=_ler_uid(Path(args.credencial)) if args.credencial else "",
        nome=nome,
    )
    if prov.provisionado:
        print("dispenser-provision: já provisionado; nada a fazer", flush=True)
        return 0

    gatt = ServicoGattSimulado() if (args.simulado
        or os.environ.get("DISPENSER_GATT_SIMULADO") == "1") else ServicoGattBlueZ(nome)
    gatt.iniciar(prov)
    print(
        f"dispenser-provision: aguardando pareamento (serviço BLE). "
        f"Provisionado: {prov.provisionado}",
        flush=True,
    )

    encerrar = False

    def _finaliza(_sinal, _quadro):
        nonlocal encerrar
        encerrar = True

    signal.signal(signal.SIGTERM, _finaliza)
    signal.signal(signal.SIGINT, _finaliza)

    try:
        while not encerrar and not prov.provisionado:
            time.sleep(0.5)
            if prov.estado == Provisionador.ESTADO_ERRO:
                print(
                    f"dispenser-provision: estado {prov.status()['erro']} — aguardando nova carga",
                    flush=True,
                )
                while not encerrar and not prov.provisionado:
                    if prov.estado != Provisionador.ESTADO_ERRO:
                        break
                    time.sleep(1.0)
    finally:
        gatt.parar()
    print(
        "dispenser-provision: provisionado — reinicie o serviço principal"
        if prov.provisionado
        else "dispenser-provision: encerrado sem provisionar",
        flush=True,
    )
    return 0 if prov.provisionado else 1


if __name__ == "__main__":
    sys.exit(main())