# Boot, operação e diagnóstico (Fase 7)

Guia de quem vai operar o aparelho: o que sobe no boot, como conferir se está
saudável, o que fazer quando algo não está, e o que esperar de uma queda de
energia. Decisões e alternativas: `docs/decisoes/011-*.md` (boot),
`012-*.md` (relógio) e `013-*.md` (cartão SD).

## O que sobe no boot

Ordem real, do systemd:

```
multi-user.target
├── dispenser-core.service        obrigatório (Type=notify, watchdog 45 s)
├── dispenser-provision.service   só se ainda não foi pareado
└── dispenser-ui.service          só se o bundle arm64 estiver instalado
```

O core **não espera a rede**: `Wants=network-online.target` é desejo, não
exigência. Sem internet ele sobe com a agenda em cache, continua guiando a dose
por alarme/LED/tela e acumula a fila de eventos para enviar depois. Com a rede
voltando, a fila sai sozinha.

O provisionamento tem `ConditionPathExists=!/var/lib/dispenser/dispenser.env`:
enquanto o aparelho não foi pareado com o app, ele fica esperando; assim que o
arquivo aparece, a unit é pulada para sempre.

A UI usa `Wants=dispenser-core.service`, **não** `Requires=`: se o core cair e
voltar, a tela não morre junto — ela reconecta sozinha, com espera progressiva
(1 s até 15 s, com jitter).

## Como saber que está saudável

```bash
systemctl status dispenser-core          # active (running) há N dias
systemctl is-enabled dispenser-core      # enabled
journalctl -u dispenser-core -f          # log ao vivo
journalctl -u dispenser-core --since today | grep -i erro
```

Sinais de que está tudo bem:

- `dispenser-core: iniciado (fuso America/Sao_Paulo)` no log;
- a tela mostra a próxima dose (`reposo`), não "conectando" e não o aviso de
  relógio;
- `systemctl show dispenser-core -p WatchdogTimestampMonotonic` não está
  zerado: enquanto o watchdog estiver ativo, o systemd anota a hora do último
  pulso.

Teste rápido do watchdog (o core deve ser morto e voltar sozinho):

```bash
sudo systemctl kill --kill-whom=main --signal=SIGSTOP dispenser-core
# espere ~45 s: o systemd reinicia o core
systemctl status dispenser-core
```

## Quando a tela diz "relógio não confiável"

O Pi não tem RTC. Se a hora estiver abaixo de 2024-01-01 ou tiver saltado mais
de 5 minutos, o core **não dispara dose** e avisa na tela. É o comportamento
esperado (ADR 012): alarme em horário impossível não ajuda ninguém.

O que fazer, em ordem:

```bash
timedatectl status                        # NTP synchronized?
sudo timedatectl set-ntp true             # liga o NTP
sudo timedatectl set-timezone America/Sao_Paulo
sudo systemctl restart systemd-timesyncd
```

Com a hora de volta, o core retoma sozinho: retoma os temporizadores da dose em
andamento, marca como não atendidas as doses mais de 15 min atrasadas e manda
**um** aviso ao cuidador. Se o aviso de `relogio` aparecer no app, o cuidador
precisa saber que o dia ficou sem lembrete — vale checar se o aparelho está com
internet (o aviso fica na fila enquanto não há rede).

## Quando a tela fica "conectando" / a UI não mostra dose

A UI só desenha o que o core manda. "Conectando" significa socket do core
ausente ou core fora:

```bash
ls -l /run/dispenser/core.sock           # existe?
systemctl status dispenser-core
journalctl -u dispenser-core -n 50
systemctl status dispenser-ui
```

Se o core estiver `active (running)` e o socket existir, o problema é da UI
(reconexão é automática; se não resolver, `sudo systemctl restart
dispenser-ui`). A dose continua sendo guiada por alarme e LED: a UI é auxiliar
(ADR 006).

## Sem backend: o aparelho ainda serve

O core sobe sem provisionamento e avisa no log `sem backend (aguardando
provisionamento)`. Ele toca alarme pela agenda em cache (`agenda_cache`) e
acumula os eventos em `outbox`. Quando o app parear, o core passa a sincronizar
**sem reiniciar**: a unit detecta o mtime do arquivo de provisionamento a cada
volta do loop, e `systemctl reload dispenser-core` força.

Para ver a fila:

```bash
sqlite3 /var/lib/dispenser/state.db \
  "SELECT id, tipo, ocorrencia_id, criado_em FROM outbox WHERE enviado_em IS NULL;"
```

Item que fica na fila com o aparelho "saudável" e com internet normalmente
significa regra do Firestore ou credencial errada: ver
`docs/firestore-integracao.md` (passo 2 do vínculo).

## Placa não aparece

```bash
ls -l /dev/dispenser-board /dev/serial/by-id/  # nome estável
sudo /opt/dispenser/detectar-placa.sh          # imprime a regra certa
```

A regra em `/etc/udev/rules.d/99-dispenser-usb.rules` vem com placeholder
(`XXXX`); ela só cria `/dev/dispenser-board` depois de preenchida com os IDs
reais. Enquanto isso, o aparelho funciona pelo `/dev/ttyUSB*` — que muda de
nome conforme o boot, e por isso não deve ser a configuração final.

## Queda de energia

O que acontece ao religar:

- o lock de instância única e o socket são recriados (moram em `/run`, que é
  tmpfs);
- o banco abre com WAL; se o cartão foi removido no meio de uma escrita, o
  SQLite se recupera e o core sobe (perdendo, no pior caso, a última
  transação);
- a dose que estava em andamento é retomada do estado salvo, sem voltar ao
  início e **sem duplicar**: a `outbox` tem chave única por ocorrência+tipo e o
  `Historico` no backend tem `docId` determinístico;
- eventos ainda não enviados saem assim que houver rede.

O que **não** é coberto ainda: se o `state.db` ficar ilegível de vez, o core sobe
sem histórico local e a fila é perdida. É o próximo candidato a fase
(`docs/PROGRESSO.md`).

## Disco

```bash
df -h /                     # espaço livre no cartão
du -sh /var/lib/dispenser   # tamanho do estado
journalctl --disk-usage      # journal (volátil, teto de 32 MB)
```

Se `/var/lib/dispenser` crescer além do esperado, o que pesa é a `outbox`
pendente (o que o cuidador ainda não recebeu) e a trilha `log_eventos` (90 dias
por padrão, `DISPENSER_RETENCAO_LOG_DIAS`). A `outbox` **não** é purgada por
projeto: se estiver grande, a causa é rede ou credencial, não o instalador.

## Manutenção

```bash
sudo systemctl restart dispenser-core   # recarrega código novo sem perder a dose
sudo systemctl reload dispenser-core     # relê o provisionamento (SIGHUP)
journalctl --disk-usage
sudo ./deploy/uninstall.sh --executar   # remove (mantém /var/lib/dispenser)
```

Atualizar o código: `./deploy/install.sh --executar` de novo. Ele é
idempotente e **não** sobrescreve `dispenser.conf` nem o arquivo de
provisionamento; depois, `sudo systemctl restart dispenser-core`.

## O que ainda falta validar no Pi

Estas partes foram implementadas e testadas em máquina x86, mas precisam do
aparelho real antes de serem consideradas aprovadas:

- `Type=notify` e `WatchdogSec` (o teste real do reinício automático);
- a regra udev com os IDs da placa escolhida;
- `timedatectl` sincronizando e o caminho offline até 1970 (pode ser feito
  desligando a rede e definindo uma data antiga, sem desligar a rede de verdade);
- grupos do usuário `dispenser` para o kiosk (video/input/render) e `dialout`;
- queda de energia física (retirar o cartão) e integridade do banco depois;
- o bundle Flutter arm64 no LCD (falta toolchain clang/ninja/GTK no snap);
- NTP sincronizando de verdade depois de alguns dias sem rede.
