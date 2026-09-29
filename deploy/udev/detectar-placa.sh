#!/usr/bin/env bash
# detectar-placa.sh — descobre a placa do dispensador e imprime a regra udev.
#
# Só leitura: não instala nada, não precisa de root. Use com a placa conectada
# e passe a linha gerada para /etc/udev/rules.d/99-dispenser-usb.rules.
set -euo pipefail

if [[ ! -d /sys/class/tty ]]; then
  echo "sem /sys/class/tty: rode no Raspberry Pi (ou em contêiner com /sys)" >&2
  exit 1
fi

# TTYs de USB sem Conversor: o caminho que a placa realmente usa.
mapfile -t candidatas < <(
  for dev in /sys/class/tty/ttyACM* /sys/class/tty/ttyUSB*; do
    [[ -e "$dev" ]] || continue
    # Ignora o módulo CDC do próprio Raspberry Pi (gpio-shutdown, ttyS).
    nome=$(cat "$dev/device/../of_node/compatible" 2>/dev/null | tr -d '\0' || true)
    [[ "$nome" == *"raspberrypi"* ]] && continue
    echo "${dev##*/}"
  done
)

if [[ ${#candidatas[@]} -eq 0 ]]; then
  echo "nenhuma placa USB-serial encontrada."
  echo "conecte a placa e rode de novo; se ela for SPI/GPIO, não há regra udev"
  exit 1
fi

for tty in "${candidatas[@]}"; do
  sys="/sys/class/tty/$tty/device"
  vid=$(cat "$sys/../idVendor" 2>/dev/null | tr -d '\0' || echo "????")
  pid=$(cat "$sys/../idProduct" 2>/dev/null | tr -d '\0' || echo "????")
  fab=$(cat "$sys/../manufacturer" 2>/dev/null | tr -d '\0' || echo "desconhecido")
  mod=$(cat "$sys/../product" 2>/dev/null | tr -d '\0' || echo "desconhecido")
  serial=$(cat "$sys/../serial" 2>/dev/null | tr -d '\0' || echo "")
  porta=$(basename "$(readlink -f "$sys")")

  echo "# ${fab} ${mod} em ${porta} (tty ${tty})"
  if [[ -n "$serial" ]]; then
    echo "SUBSYSTEM==\"tty\", ATTRS{serial}==\"${serial}\", SYMLINK+=\"dispenser-board\", MODE=\"0660\", GROUP=\"dispenser\", TAG+=\"uaccess\""
  fi
  echo "SUBSYSTEM==\"tty\", ATTRS{idVendor}==\"${vid}\", ATTRS{idProduct}==\"${pid}\", SYMLINK+=\"dispenser-board\", MODE=\"0660\", GROUP=\"dispenser\", TAG+=\"uaccess\""
  echo
done

echo "Após editar a regra: sudo udevadm control --reload-rules && sudo udevadm trigger"
