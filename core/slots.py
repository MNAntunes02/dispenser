"""Numeração e posição física dos 12 slots do dispensador.

Os slots são rotulados de 1 a 12 (o hardware legado usa índice 0..11, mas
todo texto exibido ao usuário e todo registro de estoque usa 1..12). No LCD,
os ímpares ficam na coluna esquerda e os pares na direita, em ordem crescente
de cima para baixo:

    esquerda    direita
    1           2
    3           4
    5           6
    7           8
    9           10
    11          12
"""

from __future__ import annotations

TOTAL_SLOTS = 12
SLOTS = tuple(range(1, TOTAL_SLOTS + 1))


def validar_slot(slot: object) -> int:
    """Converte e valida um número de slot (1..12). Levanta `ValueError`."""
    try:
        numero = int(slot)
    except (TypeError, ValueError) as erro:
        raise ValueError(f"slot inválido: {slot!r}") from erro
    if numero not in SLOTS:
        raise ValueError(f"slot fora da faixa 1..{TOTAL_SLOTS}: {numero}")
    return numero


def coluna_slot(slot: int) -> str:
    """`esquerda` para ímpares, `direita` para pares."""
    return "esquerda" if slot % 2 else "direita"


def linha_slot(slot: int) -> int:
    """Linha 0..5 no grid: 1/2 na primeira, 11/12 na última."""
    return (slot - 1) // 2


def rotulo_slot(slot: int) -> str:
    """Texto curto do slot para o grid do LCD."""
    return f"Slot {slot}"


def posicoes_slots() -> list[dict]:
    """Lista ordenada por linha/coluna para a UI desenhar sem regra própria."""
    return [
        {
            "slot": slot,
            "rotulo": rotulo_slot(slot),
            "linha": linha_slot(slot),
            "coluna": coluna_slot(slot),
        }
        for slot in sorted(SLOTS, key=lambda s: (linha_slot(s), s % 2 == 0))
    ]
