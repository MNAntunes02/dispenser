"""Serviço GATT do provisionamento BLE (Fase 3b).

Contrato definido em `docs/BLUETOOTH.md`. `ServicoGattSimulado` exercita o
fluxo sem hardware; `ServicoGattBlueZ` roda no Pi (BlueZ via D-Bus) e só é
executável quando o adaptador BLE existir.
"""

from __future__ import annotations

import json
from typing import Callable

from core.provisionamento import MontadorChunks, ProvisionamentoErro

SERVICO_UUID = "9a40d000-1dd1-11b2-80c0-00805f9b34fb"
CHAR_ID_UUID = "9a40d001-1dd1-11b2-80c0-00805f9b34fb"
CHAR_CONFIG_UUID = "9a40d002-1dd1-11b2-80c0-00805f9b34fb"
CHAR_STATUS_UUID = "9a40d003-1dd1-11b2-80c0-00805f9b34fb"

CONFIG_PECA = "org.optiblister.config.peca"
CONFIG_COMPLETA = "org.optiblister.config.completa"


class ControladorGatt:
    """Interface implementada pelo `Provisionador`."""

    def identidade(self) -> dict:
        raise NotImplementedError

    def status(self) -> dict:
        raise NotImplementedError

    def definir_ao_mudar(self, fn: Callable[[], None]) -> None:
        raise NotImplementedError

    def receber_carga(self, carga: dict) -> None:
        raise NotImplementedError


class ServicoGatt:
    """Interface do serviço BLE exposto pelo dispensador."""

    def iniciar(self, controlador: ControladorGatt) -> None:
        raise NotImplementedError

    def parar(self) -> None:
        raise NotImplementedError


class ReceptorCarga:
    """Remonta pedaços de configuração (chunking) e entrega a carga JSON."""

    def __init__(self, destino: Callable[[dict], None]) -> None:
        self._destino = destino
        self._montador = MontadorChunks()

    def empurrar(self, peca: object) -> None:
        montado = self._montador.adicionar(peca)
        if montado is None:
            return
        try:
            carga = json.loads(montado)
        except ValueError as erro:
            raise ProvisionamentoErro(f"JSON inválido: {erro}") from erro
        if not isinstance(carga, dict):
            raise ProvisionamentoErro("carga não é um objeto")
        self._destino(carga)


class ServicoGattSimulado(ServicoGatt):
    """GATT em memória: permite simular identidade, carga e notificações."""

    def __init__(self) -> None:
        self.controlador: ControladorGatt | None = None
        self.notificacoes: list[dict] = []
        self._ativo = False
        self._receptor: ReceptorCarga | None = None

    @property
    def ativo(self) -> bool:
        return self._ativo

    def iniciar(self, controlador: ControladorGatt) -> None:
        self.controlador = controlador
        self._receptor = ReceptorCarga(controlador.receber_carga)
        controlador.definir_ao_mudar(self._degustar_status)
        self._ativo = True
        self._degustar_status()

    def parar(self) -> None:
        self._ativo = False

    def ler_identidade(self) -> dict:
        if self.controlador is None:
            raise ProvisionamentoErro("serviço não iniciado")
        return self.controlador.identidade()

    def escrever_carga(self, carga: dict) -> None:
        """Equivalente à escrita da característica `config`."""
        if self.controlador is None or self._receptor is None:
            raise ProvisionamentoErro("serviço não iniciado")
        self._receptor.empurrar({"seq": 0, "total": 1, "dados": json.dumps(carga)})

    def escrever_pedacos(self, pedacos: list[dict]) -> None:
        for pedaco in pedacos:
            if self._receptor is not None:
                self._receptor.empurrar(pedaco)

    def _degustar_status(self) -> None:
        if self.controlador is not None:
            self.notificacoes.append(dict(self.controlador.status()))