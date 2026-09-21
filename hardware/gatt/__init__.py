"""Serviço GATT de provisionamento: simulado (testes/dev) e BlueZ (Pi)."""

from hardware.gatt.servico_gatt import (  # noqa: F401
    CHAR_CONFIG_UUID,
    CHAR_ID_UUID,
    CHAR_STATUS_UUID,
    SERVICO_UUID,
    ControladorGatt,
    ServicoGatt,
    ServicoGattSimulado,
)