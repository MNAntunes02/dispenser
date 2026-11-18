"""Estoque de cartelas por slot (registro, reposição e baixa de comprimidos).

Regras do protótipo:
- 12 slots rotulados de 1 a 12 (ver `core/slots.py`);
- uma cartela por slot, com a quantidade de comprimidos lida pela câmera ou
  informada manualmente no painel/CLI;
- registro novo prefere o slot vazio de maior número;
- a baixa acontece quando a dose é liberada, e só uma vez por ocorrência
  (a tabela `estoque_baixas` torna a operação idempotente).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.armazenamento import Database
from core.slots import SLOTS, coluna_slot, linha_slot, rotulo_slot, validar_slot

#: Limite de comprimidos por cartela (protege contra leitura absurda).
MAX_COMPRIMIDOS = 999


@dataclass(frozen=True)
class ItemEstoque:
    """Estado de um slot no grid do LCD."""

    slot: int
    medicamento: str = ""
    quantidade: int = 0
    atualizado_em: str | None = None

    @property
    def vazio(self) -> bool:
        return self.quantidade <= 0

    def para_mensagem(self) -> dict:
        """Campos publicados na mensagem `estoque` (a UI só desenha)."""
        return {
            "slot": self.slot,
            "rotulo": rotulo_slot(self.slot),
            "linha": linha_slot(self.slot),
            "coluna": coluna_slot(self.slot),
            "medicamento": self.medicamento,
            "quantidade": self.quantidade,
            "vazio": self.vazio,
        }


def validar_quantidade(quantidade: object) -> int:
    """Converte e valida a contagem de comprimidos (1..999)."""
    try:
        numero = int(quantidade)
    except (TypeError, ValueError) as erro:
        raise ValueError(f"quantidade inválida: {quantidade!r}") from erro
    if not 1 <= numero <= MAX_COMPRIMIDOS:
        raise ValueError(f"quantidade fora da faixa 1..{MAX_COMPRIMIDOS}: {numero}")
    return numero


class ServicoEstoque:
    """Operações de estoque sobre o banco local (sem estado em memória)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def itens(self) -> list[ItemEstoque]:
        """Devolve os 12 slots, inclusive os vazios, na ordem física do grid."""
        por_slot = {
            int(linha["slot"]): ItemEstoque(
                slot=int(linha["slot"]),
                medicamento=str(linha["medicamento"] or ""),
                quantidade=max(0, int(linha["quantidade"])),
                atualizado_em=linha["atualizado_em"],
            )
            for linha in self._db.conexao.execute(
                "SELECT slot, medicamento, quantidade, atualizado_em FROM estoque"
            ).fetchall()
            if int(linha["slot"]) in SLOTS
        }
        return [por_slot.get(slot, ItemEstoque(slot=slot)) for slot in SLOTS]

    def mensagem(self) -> list[dict]:
        """Retrato do estoque para a UI."""
        return [item.para_mensagem() for item in self.itens()]

    def slot_vazio_maior(self) -> int | None:
        """Maior slot sem comprimidos; `None` quando os 12 estão ocupados."""
        vazios = [item.slot for item in self.itens() if item.vazio]
        return max(vazios) if vazios else None

    def registrar(self, slot: object, quantidade: object, medicamento: str = "") -> ItemEstoque:
        """Grava/substitui a cartela de um slot e devolve o estado final."""
        numero = validar_slot(slot)
        comprimidos = validar_quantidade(quantidade)
        nome = str(medicamento or "").strip()
        agora = self._db._agora()
        self._db.conexao.execute(
            """
            INSERT INTO estoque (slot, medicamento, quantidade, atualizado_em)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(slot) DO UPDATE SET
                medicamento = excluded.medicamento,
                quantidade = excluded.quantidade,
                atualizado_em = excluded.atualizado_em
            """,
            (numero, nome, comprimidos, agora),
        )
        self._db.conexao.commit()
        return ItemEstoque(numero, nome, comprimidos, agora)

    def baixar(self, slot: object, ocorrencia_id: str) -> bool:
        """Desconta um comprimido na liberação da dose.

        Devolve `True` só na primeira chamada de cada ocorrência: reconexões e
        repetição de evento não descontam duas vezes. Nunca fica negativo.
        """
        numero = validar_slot(slot)
        conn = self._db.conexao
        agora = self._db._agora()
        with conn:
            marcador = conn.execute(
                "INSERT OR IGNORE INTO estoque_baixas (ocorrencia_id, slot) VALUES (?, ?)",
                (ocorrencia_id, numero),
            )
            if marcador.rowcount == 0:
                return False
            conn.execute(
                "INSERT OR IGNORE INTO estoque (slot, medicamento, quantidade, atualizado_em) "
                "VALUES (?, '', 0, ?)",
                (numero, agora),
            )
            conn.execute(
                "UPDATE estoque SET quantidade = MAX(0, quantidade - 1), "
                "atualizado_em = ? WHERE slot = ?",
                (agora, numero),
            )
        return True
