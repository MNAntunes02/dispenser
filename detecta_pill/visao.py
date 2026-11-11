"""Contagem de detecções e saída NDJSON para a UI (detecção de consumo).

Módulo **puro**: não importa cv2, picamera2 nem ultralytics. Assim pode ser
testado fora do Raspberry Pi (a parte pesada fica nos scripts de câmera) e é a
fonte única do formato lido pela UI Flutter (`ui/lib/src/visao.dart`).

Contrato com a UI: uma linha JSON por frame processado, sempre com as chaves
`pill` e `no_pill` (0 quando ausentes), terminada em newline:

    {"pill": 3, "no_pill": 1}

A UI confirma o consumo (passo 4) quando a mesma leitura se repete por N
frames e há ao menos um `pill` — ver `ui/lib/src/visao.dart`.
"""

from __future__ import annotations

import json
from typing import Callable, Iterable

#: Classes que a UI entende (o modelo `best.pt` é treinado em pill/no_pill).
CLASSES = ("pill", "no_pill")


def contar_classes(
    deteccoes: Iterable[tuple],
    nome_da_classe: Callable[[object], str],
) -> dict[str, int]:
    """Conta quantas detecções há de cada classe conhecida.

    `deteccoes` é a lista produzida pelo script de câmera: cada item tem o id
    da classe no índice 4 (formato `x1,y1,x2,y2,classe_id,conf`). `nome_da_classe`
    traduz o id para o nome ("pill"/"no_pill"). Classes fora de `CLASSES` são
    ignoradas; o resultado sempre traz as duas chaves (0 quando não há).
    """
    contagem = {classe: 0 for classe in CLASSES}
    for deteccao in deteccoes:
        nome = nome_da_classe(deteccao[4])
        if nome in contagem:
            contagem[nome] += 1
    return contagem


def linha_ndjson(contagem: dict[str, int]) -> str:
    """Serializa a contagem em uma linha NDJSON (contrato com a UI).

    Garante as duas chaves mesmo quando a detecção não trouxe nenhuma classe
    (a UI usa isso para exigir ao menos um comprimido e não confirmar com a
    câmera ligada sem ler cartela).
    """
    linha = {classe: int(contagem.get(classe, 0)) for classe in CLASSES}
    return json.dumps(linha, ensure_ascii=False)
