#!/usr/bin/env python3
"""CLI de depuração: simula abertura/fechamento da gaveta via socket do core.

Uso:
  python debug/gaveta.py abrir
  python debug/gaveta.py fechar
  python debug/gaveta.py slot-ausente 3
  python debug/gaveta.py slot-presente 3
"""
import json
import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.protocolo_ui import comando_simular  # noqa: E402

SOCKET = os.environ.get(
    "DISPENSER_SOCKET",
    str(Path(__file__).resolve().parent.parent / ".run" / "core.sock"),
)

ACOES = {
    "abrir": ("gaveta_aberta", False),
    "fechar": ("gaveta_fechada", False),
    "slot-ausente": ("slot_ausente", True),
    "slot-presente": ("slot_presente", True),
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ACOES:
        print(__doc__)
        return 2
    evento, precisa_slot = ACOES[sys.argv[1]]
    slot = None
    if precisa_slot:
        if len(sys.argv) < 3:
            print("Informe o slot, ex.: slot-ausente 3")
            return 2
        slot = int(sys.argv[2])

    msg = comando_simular(evento, slot)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        s.connect(SOCKET)
        s.sendall((json.dumps(msg) + "\n").encode())
        print(f"> {json.dumps(msg)}")
        fim = time.time() + 1.5  # mostra o que o core responder
        buf = b""
        while time.time() < fim:
            try:
                dado = s.recv(4096)
            except socket.timeout:
                continue
            if not dado:
                break
            buf += dado
        for linha in buf.decode(errors="replace").splitlines():
            print(f"< {linha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
