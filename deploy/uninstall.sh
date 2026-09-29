#!/usr/bin/env bash
# Remoção do dispensador (Fase 7/8).
#
# ALTERA O SISTEMA. O padrão é **não fazer nada**: sem `--executar`, mostra o
# plano e sai. Sem `--apagar-dados`, NUNCA toca em /var/lib/dispenser.
#
# Por que o cuidado: em /var/lib/dispenser estão o histórico de adesão e a fila
# de eventos que ainda não chegaram ao cuidador. Apagar o banco para "deixar
# limpo" faria o cuidador receber a notícia de que a dose foi tomada — ou
# perdesse a de que não foi. Quem apaga, apaga sabendo.
set -euo pipefail

PREFIXO=/opt/dispenser
USUARIO=dispenser
ESTADO=/var/lib/dispenser
ETC=/etc/dispenser
EXECUTAR=0
APAGAR_DADOS=0
MANTER_USUARIO=0

info() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
aviso() { printf '\033[1;33maviso:\033[0m %s\n' "$*" >&2; }
erro() { printf '\033[1;31merro:\033[0m %s\n' "$*" >&2; exit 1; }
passo() {
  if [[ $EXECUTAR -eq 1 ]]; then info "$*"; else printf '  [plano] %s\n' "$*"; fi
}
executar() {
  if [[ $EXECUTAR -eq 1 ]]; then "$@"; else printf '  [plano] %s\n' "$*"; fi
}

uso() {
  cat <<'FIM'
uso: uninstall.sh [opções]

  --executar          faz a remoção (sem esta flag, só mostra o plano)
  --apagar-dados      também apaga /var/lib/dispenser (histórico e fila!)
  --manter-usuario    não remove o usuário nem os grupos
  --prefixo DIR       raiz do código (padrão /opt/dispenser)
  -h, --help          esta ajuda
FIM
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --executar) EXECUTAR=1 ;;
    --apagar-dados) APAGAR_DADOS=1 ;;
    --manter-usuario) MANTER_USUARIO=1 ;;
    --prefixo) PREFIXO="${2:?--prefixo exige um caminho}"; shift ;;
    -h|--help) uso; exit 0 ;;
    *) erro "opção desconhecida: $1 (use --help)" ;;
  esac
  shift
done

servicos() {
  for u in dispenser-ui dispenser-provision dispenser-core; do
    passo "desabilita ${u}.service"
    executar systemctl disable --now "$u.service" || true
  done
  passo "remove as units e o drop-in do journald"
  executar rm -f /etc/systemd/system/dispenser-{core,ui,provision}.service
  executar rm -f /etc/systemd/journald.conf.d/10-dispenser.conf
  executar systemctl daemon-reload
  executar systemctl restart systemd-journald
}

arquivos() {
  passo "remove wrappers, código e regra udev"
  executar rm -f /usr/local/bin/dispenser-{core,ui,provision}
  executar rm -f /etc/udev/rules.d/99-dispenser-usb.rules
  executar udevadm control --reload-rules || true
  executar rm -rf "${PREFIXO:?}"
  passo "remove a configuração não secreta (${ETC})"
  executar rm -rf "${ETC:?}"
}

dados() {
  if [[ $APAGAR_DADOS -eq 1 ]]; then
    aviso "APAGANDO ${ESTADO}: histórico de adesão e fila pendente serão perdidos"
    executar rm -rf "${ESTADO:?}"
    executar rm -f /run/dispenser/core.lock
  else
    aviso "${ESTADO} mantido (histórico + fila de eventos)."
    aviso "Para apagar de verdade: --apagar-dados"
  fi
}

usuario() {
  [[ $MANTER_USUARIO -eq 1 ]] && { aviso "usuário ${USUARIO} mantido"; return; }
  passo "remove o usuário do sistema ${USUARIO}"
  executar userdel "$USUARIO" 2>/dev/null || true
  # Grupos dialout/video/input/render/bluetooth são do sistema: só removemos
  # se ficaram vazios, porque o usuário da sessão gráfica também os usa.
  for g in dispenser; do
    getent group "$g" >/dev/null && executar groupdel "$g" || true
  done
}

main() {
  if [[ $EXECUTAR -eq 0 ]]; then
    cat <<FIM
planejando a remoção (nada será alterado)

  serviços ..... dispenser-{ui,provision,core}.service
  arquivos ..... ${PREFIXO}, /etc/dispenser, wrappers, regra udev
  dados ........ ${ESTADO} SERÁ MANTIDO
  usuário ...... ${USUARIO}$([[ $MANTER_USUARIO -eq 1 ]] && printf ' (mantido)')

Para remover:            sudo ./deploy/uninstall.sh --executar
Para apagar tudo:       sudo ./deploy/uninstall.sh --executar --apagar-dados
FIM
    return
  fi
  [[ $(id -u) -eq 0 ]] || erro "precisa de root: rode com sudo"
  servicos
  arquivos
  dados
  usuario
  info "remoção concluída"
}

main "$@"
