"""Regra 9 do AGENTS.md: um único arquivo de textos em pt-BR.

A UI Flutter tem uma cópia local de `ROTULOS_UI` (`ui/lib/src/rotulos.dart`)
para poder falar alguma coisa antes do primeiro retrato do core — exatamente
quando o core está fora do ar. Este teste garante que a cópia não diverge.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.textos import ROTULOS_UI, TOTAL_PASSOS

DART = Path(__file__).resolve().parents[1] / "ui" / "lib" / "src" / "rotulos.dart"

_PADRAO_ENTRADA = re.compile(r"'([^']+)'\s*:\s*'((?:[^'\\]|\\.)*)'")
_PADRAO_ENTRADA_DUPLA = re.compile(r'^\s*"([^"]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', re.MULTILINE)


def _dart_para_python(texto: str) -> str:
    return texto.replace("\\'", "'").replace('\\"', '"')


def _rotulos_dart() -> dict[str, str]:
    fonte = DART.read_text(encoding="utf-8")
    corpo = fonte.split("kRotulosPadrao", 1)[1]
    corpo = corpo[corpo.index("{") :]
    pares = _PADRAO_ENTRADA.findall(corpo) or _PADRAO_ENTRADA_DUPLA.findall(corpo)
    return {chave: _dart_para_python(valor) for chave, valor in pares}


def test_arquivo_de_rotulos_da_ui_existe():
    assert DART.is_file(), f"faltou {DART}"


def test_rotulos_da_ui_batem_com_o_core():
    assert _rotulos_dart() == ROTULOS_UI


def test_todo_texto_de_dominio_da_ui_vem_do_core():
    """A UI não pode ter frase de dose própria fora de `kRotulosPadrao`."""
    pasta = DART.parent
    # Frases em pt-BR dentro das telas só podem ser rótulos do core (ou o nome
    # de arquivos). Qualquer frase solta aqui é texto de domínio no lugar errado.
    proibido = ("Tome o medicamento", "Abra a gaveta", "Retire", "Devolva", "Tudo certo")
    for arquivo in pasta.glob("*.dart"):
        if arquivo.name == "rotulos.dart":
            continue
        fonte = arquivo.read_text(encoding="utf-8")
        for frase in proibido:
            assert frase not in fonte, f"texto de domínio em {arquivo.name}: {frase!r}"


def test_total_de_passos_unico():
    assert TOTAL_PASSOS == 6
