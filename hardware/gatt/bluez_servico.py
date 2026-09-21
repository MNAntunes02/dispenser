"""Servidor GATT BlueZ para o provisionamento (roda no Pi).

Só é executável com adaptador BLE + BlueZ + `dbus-next` ativos. Nas demais
máquinas (dev/testes) esta classe levanta RuntimeError — o teste do fluxo usa
`ServicoGattSimulado`. Características definidas em `docs/BLUETOOTH.md`.
"""

from __future__ import annotations

import json
import logging
import threading

from hardware.gatt.servico_gatt import (
    CHAR_CONFIG_UUID,
    CHAR_ID_UUID,
    CHAR_STATUS_UUID,
    SERVICO_UUID,
    ControladorGatt,
    ReceptorCarga,
    ServicoGatt,
)

log = logging.getLogger("dispenser.gatt")

ID_PROPAGANDA = "OptiBlister-"
APP_PATH = "/org/dispenser/app"
SERVICO_PATH = "/org/dispenser/service0"
CHAR_ID_PATH = "/org/dispenser/service0/char0"
CHAR_CONFIG_PATH = "/org/dispenser/service0/char1"
CHAR_STATUS_PATH = "/org/dispenser/service0/char2"
DESC_CCC_PATH = "/org/dispenser/service0/char2/ccc0"
ADV_PATH = "/org/dispenser/adv0"

try:
    import dbus_next  # noqa: F401
    from dbus_next import Variant
    from dbus_next.service import ServiceInterface, method, property_
except ImportError:
    dbus_next = None  # type: ignore[assignment]
    log.warning("dbus-next ausente: servidor GATT BlueZ indisponível fora do Pi")


if dbus_next is None:

    class ServicoGattBlueZ(ServicoGatt):
        """Placeholder para máquinas sem BlueZ/dbus-next (dev/CI)."""

        def __init__(self, nome: str = "dispenser") -> None:
            self._nome = nome

        def iniciar(self, controlador: ControladorGatt) -> None:
            raise RuntimeError(
                "ServicoGattBlueZ só roda no Pi com dbus-next + BlueZ; "
                "use ServicoGattSimulado em dev/testes"
            )

        def parar(self) -> None:
            return None

else:
    from dbus_next.aio import MessageBus

    class _App(ServiceInterface):
        """org.freedesktop.DBus.ObjectManager do aplicativo GATT."""

        interface_name = "org.freedesktop.DBus.ObjectManager"

        def __init__(self) -> None:
            super().__init__()
            self.path = APP_PATH
            self.objects: dict = {}

        @method()
        def GetManagedObjects(self):
            return self.objects

    class _Servico(ServiceInterface):
        interface_name = "org.bluez.GattService1"

        def __init__(self, uuid: str) -> None:
            super().__init__()
            self.path = SERVICO_PATH
            self._uuid = uuid

        @property
        def UUID(self):
            return self._uuid

        @property
        def Primary(self):
            return True

    class _Caracteristica(ServiceInterface):
        """org.bluez.GattCharacteristic1 com suporte a notify."""

        interface_name = "org.bluez.GattCharacteristic1"

        def __init__(
            self,
            path: str,
            uuid: str,
            flags: list[str],
            ao_escrever=None,
        ) -> None:
            super().__init__()
            self.path = path
            self._uuid = uuid
            self._flags = flags
            self._valor: bytes = b""
            self._notificando = False
            self.ao_escrever = ao_escrever

        @property
        def UUID(self):
            return self._uuid

        @property
        def Service(self):
            return SERVICO_PATH

        @property
        def Flags(self):
            return self._flags

        @property
        def Notifying(self):
            return self._notificando

        @property
        def valor(self) -> bytes:
            return self._valor

        def definir_valor(self, dados: bytes) -> None:
            self._valor = dados

        @method()
        async def ReadValue(self, options):
            return list(self._valor)

        @method()
        async def WriteValue(self, value, options):
            self._valor = bytes(value)
            if self.ao_escrever is not None:
                self.ao_escrever(self._valor)

        def notificar(self, valor: bytes) -> None:
            if not self._notificando:
                return
            self.emit_properties_changed(
                self.interface_name,
                {"Value": Variant("ay", list(valor))},
                [],
            )

        @method()
        async def StartNotify(self):
            self._notificando = True
            self.emit_properties_changed(
                self.interface_name, {"Notifying": Variant("b", True)}, []
            )

        @method()
        async def StopNotify(self):
            self._notificando = False
            self.emit_properties_changed(
                self.interface_name, {"Notifying": Variant("b", False)}, []
            )

    class _DescricaoCCC(ServiceInterface):
        """org.bluez.GattDescriptor1 (Client Characteristic Configuration)."""

        interface_name = "org.bluez.GattDescriptor1"

        def __init__(self) -> None:
            super().__init__()
            self.path = DESC_CCC_PATH

        @property
        def UUID(self):
            return "2902"

        @property
        def Characteristic(self):
            return CHAR_STATUS_PATH

        @method()
        async def ReadValue(self, options):
            return [0x00, 0x00]

    class _Propaganda(ServiceInterface):
        """org.bluez.LEAdvertisement1 anunciando o serviço de provisionamento."""

        interface_name = "org.bluez.LEAdvertisement1"

        def __init__(self, nome: str) -> None:
            super().__init__()
            self.path = ADV_PATH
            self._nome = nome[:10]

        @property
        def LocalName(self):
            return f"{ID_PROPAGANDA}{self._nome}"

        @property
        def Includes(self):
            return []

        @property
        def ServiceUUIDs(self):
            return [SERVICO_UUID]

        @property
        def Type(self):
            return "peripheral"

    class ServicoGattBlueZ(ServicoGatt):
        """Servidor GATT real apoiado em BlueZ/D-Bus (executa no Pi)."""

        def __init__(self, nome: str = "dispenser") -> None:
            self._nome = nome
            self._controlador: ControladorGatt | None = None
            self._thread: threading.Thread | None = None
            self._pronto = threading.Event()
            self._encerrar = threading.Event()
            self._char_status: _Caracteristica | None = None

        def iniciar(self, controlador: ControladorGatt) -> None:
            self._controlador = controlador
            self._thread = threading.Thread(
                target=self._rodar, name="gatt-ble", daemon=True
            )
            self._thread.start()
            if not self._pronto.wait(timeout=20):
                raise RuntimeError("timeout ao iniciar o servidor GATT")

        def parar(self) -> None:
            self._encerrar.set()
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=5)

        def _rodar(self) -> None:
            import asyncio

            asyncio.run(self._executar(self._controlador))

        async def _executar(self, controlador: ControladorGatt) -> None:
            from dbus_next import Variant

            receptor = ReceptorCarga(controlador.receber_carga)

            def ao_escrever_config(valor: bytes) -> None:
                try:
                    peca = json.loads(valor.decode("utf-8"))
                    receptor.empurrar(peca)
                except Exception as erro:
                    log.warning("config rejeitada: %s", erro)

            bus = await MessageBus().connect()
            self._app = _App()
            self._servico = _Servico(SERVICO_UUID)
            self._char_id = _Caracteristica(CHAR_ID_PATH, CHAR_ID_UUID, ["read"])
            self._char_config = _Caracteristica(
                CHAR_CONFIG_PATH, CHAR_CONFIG_UUID, ["write"], ao_escrever_config
            )
            self._char_status = _Caracteristica(
                CHAR_STATUS_PATH, CHAR_STATUS_UUID, ["read", "notify"]
            )
            self._ccc = _DescricaoCCC()
            self._propaganda = _Propaganda(self._nome)

            for objeto in (
                self._app,
                self._servico,
                self._char_id,
                self._char_config,
                self._char_status,
                self._ccc,
                self._propaganda,
            ):
                bus.export(objeto.path, objeto)

            self._app.objects = {
                SERVICO_PATH: {"org.bluez.GattService1": {}},
                CHAR_ID_PATH: {"org.bluez.GattCharacteristic1": {}},
                CHAR_CONFIG_PATH: {"org.bluez.GattCharacteristic1": {}},
                CHAR_STATUS_PATH: {"org.bluez.GattCharacteristic1": {}},
                DESC_CCC_PATH: {"org.bluez.GattDescriptor1": {}},
                ADV_PATH: {"org.bluez.LEAdvertisement1": {}},
            }

            def ao_mudar() -> None:
                cabos = json.dumps(controlador.status()).encode("utf-8")
                if self._char_status is not None:
                    self._char_status.definir_valor(cabos)
                    self._char_status.notificar(cabos)

            controlador.definir_ao_mudar(ao_mudar)

            self._char_id.definir_valor(
                json.dumps(controlador.identidade()).encode("utf-8")
            )
            self._char_status.definir_valor(
                json.dumps(controlador.status()).encode("utf-8")
            )

            adv_mgr = bus.get_proxy_object(
                "org.bluez", "/org/bluez/hci0", "org.bluez.LEAdvertisingManager1"
            )
            gatt_mgr = bus.get_proxy_object(
                "org.bluez", "/org/bluez/hci0", "org.bluez.GattManager1"
            )
            await adv_mgr.call_register_advertisement(ADV_PATH, {})
            await gatt_mgr.call_register_application(APP_PATH, {})
            self._pronto.set()
            log.info("GATT BlueZ ativo (serviço %s)", SERVICO_UUID)
            while not self._encerrar.wait(1.0):
                pass