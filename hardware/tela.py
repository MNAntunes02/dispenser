"""Interface de exibição simples (LCD/terminal) para o provisionamento.

Fase 5 traz a tela real via `publicador_ui`; aqui ficam a interface e duas
implementações: terminal (uso real imediato) e simulada (testes).
"""

from __future__ import annotations


class Tela:
    """Interface mínima de exibição de texto ao usuário."""

    def mostrar(self, texto: str) -> None:
        raise NotImplementedError


class TelaTerminal(Tela):
    """Exibe na saída padrão (funciona sem hardware)."""

    def mostrar(self, texto: str) -> None:
        print(texto, flush=True)


class TelaSimulada(Tela):
    """Acumula o que seria exibido, para testes herméticos."""

    def __init__(self) -> None:
        self.exibido: list[str] = []

    def mostrar(self, texto: str) -> None:
        self.exibido.append(texto)