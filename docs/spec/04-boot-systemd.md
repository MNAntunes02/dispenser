# Boot, systemd e robustez (Fase 7)

Confirme com o usuário antes de qualquer comando com `sudo`, `systemctl enable`, udev ou edição em `/etc`.

## Serviços
- Units systemd em `dispenser/deploy/systemd/`: `dispenser-core.service` e `dispenser-ui.service`.
- `Restart=always`, `After=network-online.target`, mas **sem depender da rede** para funcionar.
- Usuário dedicado sem privilégios de root; grupos necessários (`dialout`, `gpio`, `audio`, conforme o caso).
- Watchdog: `WatchdogSec` no core, com notificação periódica; reinício automático se travar.
- A UI reconecta ao core se ele reiniciar, e vice-versa.
- Regras udev em `dispenser/deploy/udev/` para nome estável da placa.

## Relógio e fuso
- O Raspberry Pi não tem RTC de fábrica: garantir NTP (`systemd-timesyncd`).
- Definir comportamento seguro com relógio inválido (não disparar por horário não confiável; avisar na tela).
- Fuso horário explícito em configuração (confirmar com o usuário; esperado Brasil).

## Logs e disco
- journald com níveis; rotação para não encher o cartão SD.
- Minimizar escritas frequentes no SD (gravar em lotes, cuidado com WAL do SQLite).

## Instalação
- `dispenser/deploy/install.sh` **idempotente**: instala dependências, cria usuário, udev, units, habilita serviços. `uninstall.sh` reverte.
- Segredos em arquivo de ambiente com permissão `600`; entregar `config/.env.example`.

## Queda de energia
Após religar, o sistema retoma o estado (dose em andamento, fila de eventos pendentes) sem duplicar nem perder eventos.
