#!/usr/bin/env bash
# Sobe a UI no Pi via flutter-pi carregando do .env apenas o necessário para a
# detecção de consumo do passo 4 (ADR 016) e o socket do core. Credenciais do
# backend ficam de fora: o painel também não as repassa para a UI.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${DISPENSER_ENV_PATH:-$RAIZ/.env}"
BUNDLE="${DISPENSER_UI_BUNDLE:-$RAIZ/ui/pi3-64}"

if [[ -r "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source <(grep -E '^(export[[:space:]]+)?(DISPENSER_VISAO_[A-Za-z0-9_]+|DISPENSER_SOCKET)=' "$ENV_FILE")
  set +a
fi

cd "$BUNDLE"
exec flutter-pi --release "$BUNDLE"
