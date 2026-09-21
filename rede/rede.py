"""Interface de conexão Wi-Fi do dispensador (Fase 3b).

Alvo: NetworkManager via `nmcli` (reconfigura sem reboot); fallback:
configuração netplan. Senha nunca aparece em logs próprios; no fallback ela
fica no arquivo do gestor de rede do sistema (como wpa_supplicant faz).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

NETPLAN_ALVO = Path("/etc/netplan/99-dispenser.yaml")
PING_ALVO = "8.8.8.8"


def _executar_padrao(comando: list[str], timeout: int) -> int:
    try:
        return subprocess.run(
            comando, capture_output=True, text=True, timeout=timeout
        ).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


class Rede:
    """Interface para conectar o Pi a uma rede Wi-Fi."""

    def conectar_wifi(self, ssid: str, senha: str) -> bool:
        raise NotImplementedError

    def pingar(self) -> bool:
        raise NotImplementedError


class RedeSimulada(Rede):
    """Controlável nos testes; registra o que seria enviado."""

    def __init__(self, sucesso: bool = True, ping: bool = True) -> None:
        self.sucesso = sucesso
        self.ping = ping
        self.conexoes: list[tuple[str, str]] = []

    def conectar_wifi(self, ssid: str, senha: str) -> bool:
        self.conexoes.append((ssid, senha))
        return self.sucesso

    def pingar(self) -> bool:
        return self.ping


class RedeLinux(Rede):
    """Implementação real: nmcli com fallback netplan.

    `executor` recebe a lista de argumentos e o timeout em segundos e devolve o
    returncode — injetável nos testes. O comando de rede só é executado no Pi.
    """

    def __init__(
        self,
        executor: Callable[[list[str], int], int] | None = None,
        timeout: int = 60,
    ) -> None:
        self._executor = executor or _executar_padrao
        self._timeout = timeout

    def conectar_wifi(self, ssid: str, senha: str) -> bool:
        if self._nmcli_conectar(ssid, senha):
            return True
        return self._netplan_conectar(ssid, senha)

    def pingar(self) -> bool:
        return self._executor(["ping", "-c", "1", "-W", "3", PING_ALVO], 8) == 0

    def _nmcli_conectar(self, ssid: str, senha: str) -> bool:
        codigo = self._executor(
            ["nmcli", "-t", "device", "wifi", "connect", ssid, "password", senha],
            self._timeout,
        )
        return codigo == 0

    def _netplan_conectar(self, ssid: str, senha: str) -> bool:
        try:
            NETPLAN_ALVO.parent.mkdir(parents=True, exist_ok=True)
            NETPLAN_ALVO.write_text(
                "network:\n"
                "  version: 2\n"
                "  wifis:\n"
                "    wlan0:\n"
                "      access-points:\n"
                f'        "{ssid}":\n'
                f'          password: "{senha}"\n'
                "      dhcp4: true\n",
                encoding="utf-8",
            )
        except OSError:
            return False
        return self._executor(["netplan", "apply"], self._timeout) == 0