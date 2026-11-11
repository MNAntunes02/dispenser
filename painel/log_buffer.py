"""Buffer circular dos logs do painel.

O Tkinter não é thread-safe: as threads que leem stdout/stderr dos processos
não podem tocar no widget. Elas entregam as linhas por uma `queue.Queue`, a
thread principal drena a fila e este buffer guarda o histórico para filtro,
re-renderização e exportação.

O limite evita que um `flutter run` barulhento consuma memória sem teto.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime

#: Sequências ANSI (cores, limpeza de linha, cursor) que o Flutter emite.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def limpar_ansi(texto: str) -> str:
    """Remove códigos ANSI para o `tk.Text` não mostrar lixo como `[2K`."""
    return _ANSI.sub("", texto).replace("\r", "")


@dataclass(frozen=True)
class LinhaLog:
    momento: datetime
    servico: str
    fluxo: str  # "saida", "erro" ou "painel"
    texto: str


def formatar(linha: LinhaLog) -> str:
    """Formato único usado na tela e no arquivo salvo."""
    if linha.fluxo == "saida":
        etiqueta = linha.servico
    else:
        etiqueta = f"{linha.servico}/{linha.fluxo}"
    return f"{linha.momento:%Y-%m-%d %H:%M:%S} [{etiqueta}] {linha.texto}"


class BufferLog:
    """Histórico limitado de linhas de um serviço."""

    def __init__(self, limite: int = 5000) -> None:
        if limite < 1:
            raise ValueError("o limite do buffer precisa ser >= 1")
        self._linhas: deque[LinhaLog] = deque(maxlen=limite)

    @property
    def limite(self) -> int:
        return self._linhas.maxlen or 0

    def adicionar(
        self,
        servico: str,
        fluxo: str,
        texto: str,
        *,
        momento: datetime | None = None,
    ) -> LinhaLog:
        linha = LinhaLog(
            momento=momento or datetime.now(),
            servico=servico,
            fluxo=fluxo,
            texto=limpar_ansi(texto).rstrip("\r\n"),
        )
        self._linhas.append(linha)
        return linha

    def linhas(self) -> list[LinhaLog]:
        return list(self._linhas)

    def filtrar(self, termo: str = "") -> list[LinhaLog]:
        """Filtra pelo texto completo (data, serviço e mensagem), sem caixa.

        Incluir a data/serviço no filtro deixa buscar `core/erro` ou um dia
        específico sem precisar de outra caixa de busca.
        """
        termo = termo.strip().casefold()
        if not termo:
            return self.linhas()
        return [linha for linha in self._linhas if termo in formatar(linha).casefold()]

    def texto(self, termo: str = "") -> str:
        return "".join(formatar(linha) + "\n" for linha in self.filtrar(termo))

    def limpar(self) -> None:
        self._linhas.clear()

    def __len__(self) -> int:
        return len(self._linhas)
