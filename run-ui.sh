#!/usr/bin/env bash
# Sobe a UI Linux apontando para o MESMO socket do run-core.sh.
# Uso: ./run-ui.sh   (requer o core já rodando)
set -euo pipefail
cd "$(dirname "$0")"

# Valor absoluto: não usar "$PWD" depois do `cd ui`.
export DISPENSER_SOCKET=/run/dispenser/core.sock

cd ui
exec flutter run -d linux \
  --dart-define=DISPENSER_SOCKET="$DISPENSER_SOCKET"
