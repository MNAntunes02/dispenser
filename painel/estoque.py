"""Operações manuais de estoque por slot (excluir/limpar e consumir).

Uso:
    .venv/bin/python -m painel.estoque excluir --slot 12
    .venv/bin/python -m painel.estoque consumir --slot 12 --quantidade 1

Fala o mesmo protocolo da UI/painel no socket do core. As alterações são
aplicadas pelo core (com log e publicação do estoque para a UI).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from painel.comandos import ComandosCore
from painel.configuracao import DIR_DEV


def _logar(fluxo: str, mensagem: str) -> None:
    destino = sys.stderr if fluxo == "erro" else sys.stdout
    print(mensagem, file=destino, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exclui ou consome medicamentos de um slot via core"
    )
    parser.add_argument(
        "--socket",
        type=Path,
        default=DIR_DEV / "core.sock",
        help="socket do core (padrão: %(default)s)",
    )
    acoes = parser.add_subparsers(dest="acao", required=True)

    excluir = acoes.add_parser("excluir", help="esvazia o slot (remove medicamento)")
    excluir.add_argument("--slot", type=int, required=True)

    limpar = acoes.add_parser("limpar", help="alias de excluir")
    limpar.add_argument("--slot", type=int, required=True)

    consumir = acoes.add_parser("consumir", help="desconta comprimidos do slot")
    consumir.add_argument("--slot", type=int, required=True)
    consumir.add_argument("--quantidade", type=int, default=1)

    args = parser.parse_args(argv)
    comandos = ComandosCore(args.socket, ao_logar=_logar)

    if args.acao in ("excluir", "limpar"):
        enviado = comandos.limpar_slot(args.slot, assincrono=False)
        mensagem = f"slot {args.slot} esvaziado"
    else:
        enviado = comandos.consumir_slot(
            args.slot, args.quantidade, assincrono=False
        )
        mensagem = f"consumo enviado: slot {args.slot}, quantidade {args.quantidade}"

    if not enviado:
        return 1
    print(mensagem, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
