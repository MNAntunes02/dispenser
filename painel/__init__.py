"""Painel de desenvolvimento do dispensador.

Abre uma janela Tkinter que inicia/para o `dispenser-core` e a UI Flutter em
processos locais e mostra os logs dos dois. Não usa `sudo`, não fala com o
systemd e mantém o estado em `.run/` (fora do repositório).

Uso:
    .venv/bin/python -m painel
"""

from __future__ import annotations

__all__ = ["main"]


def main() -> None:
    """Atalho para a entrada real, importável nos testes e em scripts."""
    from painel.janela import main as _main

    _main()
