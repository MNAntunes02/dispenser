"""Registro de cartela pelo terminal (painel/script).

Uso:
    .venv/bin/python -m painel.registrar iniciar --medicamento "Losartana"
    .venv/bin/python -m painel.registrar manual --quantidade 10
    .venv/bin/python -m painel.registrar confirmar

O `registroId` é opcional: quando omitido, o comando vale para o registro em
andamento no core (a tela mostra o slot escolhido após a leitura).
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
    parser = argparse.ArgumentParser(description="Registra uma cartela no estoque")
    parser.add_argument(
        "--socket",
        type=Path,
        default=DIR_DEV / "core.sock",
        help="socket do core (padrão: %(default)s)",
    )
    acoes = parser.add_subparsers(dest="acao", required=True)

    iniciar = acoes.add_parser("iniciar", help="posiciona a cartela na detecção")
    iniciar.add_argument("--medicamento", default="")

    manual = acoes.add_parser("manual", help="informa a quantidade sem câmera")
    manual.add_argument("--quantidade", type=int, required=True)
    manual.add_argument("--id", default="")

    confirmar = acoes.add_parser("confirmar", help="confirma a colocação no slot")
    confirmar.add_argument("--id", default="")

    args = parser.parse_args(argv)
    comandos = ComandosCore(args.socket, ao_logar=_logar)

    if args.acao == "iniciar":
        enviado = comandos.iniciar_registro(args.medicamento, assincrono=False)
        mensagem = "registro iniciado"
    elif args.acao == "manual":
        enviado = comandos.registrar_manual(
            args.id, args.quantidade, assincrono=False
        )
        mensagem = "quantidade enviada ao core"
    else:
        enviado = comandos.confirmar_registro(args.id, assincrono=False)
        mensagem = "confirmação enviada ao core"

    if not enviado:
        return 1
    print(mensagem, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
