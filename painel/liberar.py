"""Libera o passo de detecção do consumo pelo terminal.

Uso:
    .venv/bin/python -m painel.liberar [--socket CAMINHO]

Fala o mesmo protocolo da UI/painel no socket do core. A câmera é apoio
visual; a confirmação do consumo é esta ação explícita do operador.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from painel.comandos import ComandosCore
from painel.configuracao import DIR_DEV
from painel.textos import texto


def _logar(fluxo: str, mensagem: str) -> None:
    destino = sys.stderr if fluxo == "erro" else sys.stdout
    print(mensagem, file=destino, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Libera o próximo passo após o consumo do medicamento"
    )
    parser.add_argument(
        "--socket",
        type=Path,
        default=DIR_DEV / "core.sock",
        help="socket do core (padrão: %(default)s)",
    )
    args = parser.parse_args(argv)

    comandos = ComandosCore(args.socket, ao_logar=_logar)
    if not comandos.liberar_proximo(assincrono=False):
        return 1
    print(texto("liberado"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
