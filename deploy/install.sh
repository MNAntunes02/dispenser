#!/usr/bin/env bash
# Instalação do dispensador no Raspberry Pi (Fase 7/8).
#
# ALTERA O SISTEMA. Rode somente no Pi, e somente com a confirmação do usuário
# (regra 7 do AGENTS.md). Por isso o padrão é **não fazer nada**: sem
# `--executar`, o script imprime o plano e sai.
#
#   ./deploy/install.sh                    # só mostra o plano
#   ./deploy/install.sh --executar         # instala de verdade
#   ./deploy/install.sh --executar --prefixo /opt/dispenser
#
# Idempotente: rodar duas vezes não muda o resultado e não sobrescreve
# configuração já existente (nem o arquivo de provisionamento do app).
set -euo pipefail

# --- padrões -----------------------------------------------------------------
PREFIXO=/opt/dispenser
USUARIO=dispenser
ESTADO=/var/lib/dispenser
ETC=/etc/dispenser
BIN=/usr/local/bin
EXECUTAR=0
COM_BLUETOOTH=1
BINARIO_UI=""
SEM_VENV=0

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# --- saída -------------------------------------------------------------------
info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
aviso() { printf '\033[1;33maviso:\033[0m %s\n' "$*" >&2; }
erro() { printf '\033[1;31merro:\033[0m %s\n' "$*" >&2; exit 1; }
passo() {
  if [[ $EXECUTAR -eq 1 ]]; then
    info "$*"
  else
    printf '  [plano] %s\n' "$*"
  fi
}
executar() {
  if [[ $EXECUTAR -eq 1 ]]; then
    "$@"
  else
    printf '  [plano] %s\n' "$*"
  fi
}

uso() {
  cat <<'FIM'
uso: install.sh [opções]

  --executar            faz a instalação (sem esta flag, só mostra o plano)
  --prefixo DIR         raiz do código e do venv (padrão /opt/dispenser)
  --binario-ui CAMINHO bundle arm64 já compilado (padrão: ui/build/linux/arm64/bundle)
  --sem-bluetooth       não instala bluez nem o grupo bluetooth
  --sem-venv            não cria venv (imagem já traz dependências)
  -h, --help            esta ajuda
FIM
}

# --- argumentos --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --executar) EXECUTAR=1 ;;
    --prefixo) PREFIXO="${2:?--prefixo exige um caminho}"; shift ;;
    --binario-ui) BINARIO_UI="${2:?--binario-ui exige um caminho}"; shift ;;
    --sem-bluetooth) COM_BLUETOOTH=0 ;;
    --sem-venv) SEM_VENV=1 ;;
    -h|--help) uso; exit 0 ;;
    *) erro "opção desconhecida: $1 (use --help)" ;;
  esac
  shift
done

# --- checagens ---------------------------------------------------------------
checar_ambiente() {
  [[ $(id -u) -eq 0 ]] || erro "precisa de root: rode com sudo"
  [[ -f /etc/os-release ]] || erro "sistema não parece Ubuntu (/etc/os-release ausente)"
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" || "${ID_LIKE:-}" == *debian* ]] ||
    aviso "distro não-Ubuntu (${ID:-desconhecida}); os passos apt podem variar"
  local arq
  arq=$(uname -m)
  case "$arq" in
    armv7l|aarch64) : ;;
    *) aviso "arquitetura ${arq} não é ARM do Raspberry Pi; a UI (arm64) não vai rodar" ;;
  esac
  [[ -d $RAIZ/core ]] || erro "não achei core/ em ${RAIZ}; rode de dentro do repositório"
}

pacotes() {
  local lista=(python3 python3-venv python3-pip)
  [[ $COM_BLUETOOTH -eq 1 ]] && lista+=(bluez bluez-tools)
  passo "apt-get install: ${lista[*]}"
  exportar DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq "${lista[@]}"
}

criar_usuario() {
  if id -u "$USUARIO" >/dev/null 2>&1; then
    passo "usuário ${USUARIO} já existe"
  else
    executar useradd --system --no-create-home --shell /usr/sbin/nologin "$USUARIO"
  fi
  # dialout: placa por USB serial. video/input/render: LCD, DRM e touchscreen.
  # bluetooth: pareamento Fase 3b.
  local grupos=(dialout video input render)
  [[ $COM_BLUETOOTH -eq 1 ]] && grupos+=(bluetooth)
  passo "grupos: ${grupos[*]}"
  for g in "${grupos[@]}"; do
    getent group "$g" >/dev/null || executar groupadd "$g"
    executar usermod -aG "$g" "$USUARIO"
  done
}

diretorios() {
  executar install -d -o root -g "$USUARIO" -m 0750 "$ETC"
  executar install -d -o "$USUARIO" -g "$USUARIO" -m 0750 "$ESTADO"
  # O lock e o socket vivem em /run (tmpfs): somem no boot, sem escrita no SD.
  executar install -d -o "$USUARIO" -g "$USUARIO" -m 0755 /run/dispenser
}

copiar_codigo() {
  passo "copia core/, hardware/, rede/ e requirements para ${PREFIXO}"
  executar install -d -o root -g root -m 0755 "$PREFIXO"
  for d in core hardware rede; do
    executar rm -rf "${PREFIXO:?}/${d}"
    executar cp -a "$RAIZ/$d" "$PREFIXO/$d"
  done
  executar cp -a "$RAIZ/docs" "$PREFIXO/docs"
  [[ -f $RAIZ/README.md ]] && executar cp -a "$RAIZ/README.md" "$PREFIXO/README.md"
  # __pycache__ do dev não vai para o Pi.
  executar find "$PREFIXO" -name '__pycache__' -type d -prune -exec rm -rf {} +
  # Código do usuário não deve ser editável em runtime.
  executar chown -R root:root "$PREFIXO"
  executar find "$PREFIXO" -type d -exec chmod 0755 {} +
  executar find "$PREFIXO" -type f -exec chmod 0644 {} +
}

venv() {
  [[ $SEM_VENV -eq 1 ]] && { passo "pulando venv (--sem-venv)"; return; }
  passo "cria venv e instala dependências em ${PREFIXO}/.venv"
  executar python3 -m venv "$PREFIXO/.venv"
  executar "$PREFIXO/.venv/bin/pip" install --quiet --upgrade pip
  # dbus-next só é usado no Pi (BlueZ); em x86 o wheel não existe.
  executar "$PREFIXO/.venv/bin/pip" install --quiet -r "$PREFIXO/core/requirements.txt"
  executar chown -R root:root "$PREFIXO/.venv"
}

ui() {
  local bundle="${BINARIO_UI:-$RAIZ/ui/build/linux/arm64/bundle}"
  if [[ ! -x $bundle/dispenser_ui ]]; then
    aviso "bundle da UI não encontrado em ${bundle}."
    aviso "compile antes:  cd ui && flutter build linux --target-platform linux-arm64"
    aviso "ou passe --binario-ui CAMINHO. O core funciona sem a UI."
    return
  fi
  passo "instala o bundle da UI em ${PREFIXO}/ui"
  executar install -d -o root -g root -m 0755 "$PREFIXO/ui"
  executar cp -a "$bundle/." "$PREFIXO/ui/"
  executar chown -R root:root "$PREFIXO/ui"
}

wrappers() {
  # Um wrapper por entrypoint: o systemd não deve depender do PATH nem do cwd.
  passo "cria wrappers em ${BIN}"
  executar install -d -m 0755 "$BIN"

  cat >/tmp/dispenser-core.$$ <<'FIM'
#!/usr/bin/env bash
# Gerado por deploy/install.sh — não edite à mão.
set -euo pipefail
cd /opt/dispenser
exec /opt/dispenser/.venv/bin/python -m core.dispenser_main "$@"
FIM
  executar install -m 0755 -o root -g root /tmp/dispenser-core.$$ "$BIN/dispenser-core"

  cat >/tmp/dispenser-provision.$$ <<'FIM'
#!/usr/bin/env bash
# Gerado por deploy/install.sh — não edite à mão.
set -euo pipefail
cd /opt/dispenser
exec /opt/dispenser/.venv/bin/python -m core.provision_main "$@"
FIM
  executar install -m 0755 -o root -g root /tmp/dispenser-provision.$$ "$BIN/dispenser-provision"

  cat >/tmp/dispenser-ui.$$ <<'FIM'
#!/usr/bin/env bash
# Gerado por deploy/install.sh — não edite à mão.
set -euo pipefail
cd /opt/dispenser/ui
# DISPENSER_KIOSK_TTY diz em qual console o kiosk abre (tela do LCD).
exec /opt/dispenser/ui/dispenser_ui
FIM
  executar install -m 0755 -o root -g root /tmp/dispenser-ui.$$ "$BIN/dispenser-ui"
  rm -f /tmp/dispenser-core.$$ /tmp/dispenser-provision.$$ /tmp/dispenser-ui.$$
}

configuracao() {
  # Configuração não secreta: versionada, pode ser editada e regerada.
  if [[ -f $ETC/dispenser.conf ]]; then
    aviso "${ETC}/dispenser.conf já existe; mantido como está"
  else
    passo "cria ${ETC}/dispenser.conf a partir de config/.env.example"
    executar install -m 0640 -o root -g "$USUARIO" "$RAIZ/config/.env.example" \
      "$ETC/dispenser.conf"
    aviso "revise ${ETC}/dispenser.conf (fuso, socket, caminho da placa)"
  fi
  # Provisionamento do app: segredo, 600, nunca sobrescrito.
  if [[ -f $ESTADO/dispenser.env ]]; then
    passo "${ESTADO}/dispenser.env já existe (pareado); preservado"
  else
    passo "cria ${ESTADO}/dispenser.env vazio, permissão 600 (modo 600)"
    executar install -m 0600 -o "$USUARIO" -g "$USUARIO" /dev/null "$ESTADO/dispenser.env"
  fi
}

udev() {
  passo "instala regra udev e a regra da placa"
  executar install -m 0644 -o root -g root "$RAIZ/deploy/udev/99-dispenser-usb.rules" \
    /etc/udev/rules.d/99-dispenser-usb.rules
  executar install -m 0755 -o root -g root "$RAIZ/deploy/udev/detectar-placa.sh" \
    "$PREFIXO/detectar-placa.sh"
  executar udevadm control --reload-rules
  executar udevadm trigger --subsystem-match=tty
  if grep -q 'XXXX' /etc/udev/rules.d/99-dispenser-usb.rules 2>/dev/null; then
    aviso "regra udev ainda com placeholder: rode sudo ${PREFIXO}/detectar-placa.sh"
    aviso "com a placa conectada e cole os IDs reais."
  fi
}

systemd() {
  passo "instala as units e o drop-in do journald"
  for u in dispenser-core dispenser-ui dispenser-provision; do
    executar install -m 0644 -o root -g root \
      "$RAIZ/deploy/systemd/${u}.service" "/etc/systemd/system/${u}.service"
  done
  executar install -d -m 0755 /etc/systemd/journald.conf.d
  executar install -m 0644 -o root -g root \
    "$RAIZ/deploy/journald/10-dispenser.conf" \
    /etc/systemd/journald.conf.d/10-dispenser.conf
  executar systemctl daemon-reload
  executar systemctl restart systemd-journald
  # O core é obrigatório; UI e provisionamento são melhores-esforço: um
  # aparelho sem tela ou sem pareamento ainda entrega a dose com alarme.
  executar systemctl enable --now dispenser-core.service
  executar systemctl enable --now dispenser-provision.service || \
    aviso "dispenser-provision não subiu ( bluetooth indisponível?)"
  if [[ -x $PREFIXO/ui/dispenser_ui ]]; then
    executar systemctl enable --now dispenser-ui.service
  else
    aviso "UI não instalada: dispenser-ui.service não foi habilitada"
  fi
}

verificar() {
  passo "verifica o resultado"
  systemctl is-enabled dispenser-core.service
  systemctl is-active dispenser-core.service
  systemctl --no-pager --lines=15 status dispenser-core.service || true
  if systemctl is-active --quiet dispenser-ui.service; then
    echo "UI ativa"
  else
    echo "UI inativa (veja: journalctl -u dispenser-ui)"
  fi
  # NTP: sem ele o relógio do Pi não é confiável e o core avisa na tela (ADR 012).
  if command -v timedatectl >/dev/null; then
    timedatectl show -p NTPSynchronized -p Timezone --value 2>/dev/null || true
  fi
}

# --- fluxo -------------------------------------------------------------------
main() {
  if [[ $EXECUTAR -eq 0 ]]; then
    cat <<FIM
planejando a instalação (nada será alterado)

  prefixo ....... ${PREFIXO}
  usuário ....... ${USUARIO} (grupos: dialout, video, input, render$(
    [[ $COM_BLUETOOTH -eq 1 ]] && printf ', bluetooth'))
  estado ........ ${ESTADO} (SQLite, provisionamento 600)
  config ........ ${ETC}/dispenser.conf
  venv .......... ${PREFIXO}/.venv (Python do sistema)
  UI ........... bundle arm64 em ${BINARIO_UI:-$RAIZ/ui/build/linux/arm64/bundle}

depois disto:
  systemctl status dispenser-core
  journalctl -u dispenser-core -f
  sudo ${PREFIXO}/detectar-placa.sh    # nome estável da placa

Para realmente instalar:  sudo ./deploy/install.sh --executar
FIM
    return
  fi

  checar_ambiente
  pacotes
  criar_usuario
  diretorios
  copiar_codigo
  venv
  ui
  wrappers
  configuracao
  udev
  systemd
  verificar

  cat <<FIM

instalação concluída.

primeiros passos:
  1. confira o fuso:   sudoedit ${ETC}/dispenser.conf   (DISPENSER_TZ=America/Sao_Paulo)
  2. placa na serial:  sudo ${PREFIXO}/detectar-placa.sh
  3. pareie no app:    o core sobe sem backend; o app faz o pareamento (docs/BLUETOOTH.md)
  4. acompanhe:        journalctl -u dispenser-core -f
FIM
}

main "$@"
