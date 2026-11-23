#!/usr/bin/env bash
# Sobe o core em desenvolvimento com a mesma configuração usada pelo app.
# Uso: ./run-core.sh   (Ctrl+C para parar)
set -euo pipefail
cd "$(dirname "$0")"

# --- sockets / lock / banco -------------------------------------------------
export DISPENSER_SOCKET=/run/dispenser/core.sock
export DISPENSER_LOCK_PATH=/run/dispenser/core.lock
export DISPENSER_DB_PATH=/tmp/dispenser-state.db

# --- Firebase ---------------------------------------------------------------
export FIREBASE_PROJECT_ID=app-saude-8fba1
export DISPENSER_USER_ID=tlcnVtjFeZcZqAsCvW7RqgLvDIK2
export DISPENSER_FIREBASE_API_KEY=AIzaSyDn0djbF9d4s3RjylOgHV50tp6SXGb7wfU
export DISPENSER_CREDENTIALS_PATH="$HOME/.dispenser-credencial.json"

# A credencial 600 não tem o campo "uid"; isto ativa a ponte Firestore.
export DISPENSER_ID=iBIxfP10HgZsmQGo6C15sAk1X9V2

# --- prepara /run -----------------------------------------------------------
sudo mkdir -p /run/dispenser
sudo chown -R "$USER:$USER" /run/dispenser
chmod 700 /run/dispenser

# --- checagem de processo órfão ---------------------------------------------
# Dois cores no mesmo socket = o novo cai no fallback silencioso e a tela
# continua falando com o processo antigo. Melhor parar aqui com erro claro.
if pgrep -f 'core[.]dispenser_main' >/dev/null; then
  echo "ERRO: já existe um core rodando. Mate-o antes:" >&2
  pgrep -af 'core[.]dispenser_main' >&2 || true
  echo "  pkill -f 'core[.]dispenser_main'" >&2
  exit 1
fi

# Sem processo vivo, qualquer socket/lock restante é resíduo de queda.
rm -f "$DISPENSER_SOCKET" "$DISPENSER_LOCK_PATH"
echo "Socket: $DISPENSER_SOCKET"
echo "Banco:  $DISPENSER_DB_PATH"
echo

exec .venv/bin/python -m core.dispenser_main
