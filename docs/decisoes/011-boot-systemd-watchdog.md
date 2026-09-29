# ADR 011 — Boot no systemd: watchdog, instância única e provisionamento separado

Status: implementada (Fase 7, 2026-09-29).

## Contexto
O dispensador é um aparelho de uso diário que segura a dose de um paciente. Duas
situações o fazem falhar de verdade em produção:

1. **O core trava e ninguém percebe.** Um `tick` preso em I/O (cartão SD
   corrompido, socket da UI bloqueado) deixa o aparelho em silêncio. O paciente
   acha que o remédio não está mais agendado; ninguém é notificado. Um serviço
   que "está de pé" para o systemd é apenas um processo vivo, não um
   functionality.
2. **Dois cores no mesmo banco.** A tela mostra "ouvindo o dispense" e, por
   baixo, dois agendadores disputam os mesmos horários. O paciente ouve o
   alarme em horário errado, que é pior do que não ouvir.

Além disso, o app pareia por Bluetooth **depois** que o core já sobe
(ADR 008): o aparelho precisa de credenciais para sincronizar, mas não pode
esperar por elas para tocar alarme.

O usuário confirmou nesta fase: venv em `/opt/dispenser` com wrappers em
`/usr/local/bin` fazem parte desta fase; o provisionamento roda como serviço
separado, condicionado à ausência do arquivo de configuração; e o core recarrega
o provisionamento sem reiniciar.

## Opções consideradas
- **Mypy/`sdnotify` do Python** (`python3-systemd`) — bonito, mas adiciona uma
  dependência ao venv do core justamente para enviar 20 bytes num socket.
  Rejeitado: o protocolo é um `sendto` de texto e já está testado.
- **Watchdog em script externo** (`while true; do systemctl ping; done`) — o
  script é que pode travar, e ele polui o journal. Rejeitado.
- **`Restart=always` sozinho** — cobre processo morto, não processo travado nem
  loop travado. Mantido, mas como complemento do watchdog.
- **Timer de usuário (`systemd-run --user`)** — o core morre junto com a sessão
  do usuário que logou. Rejeitado: o aparelho tem que subir sozinho, sem
  ninguém logado.
- **Provisionamento dentro do core** — simplifica units, mas amarra pareamento
  (que depende de rede e Bluetooth, e falha com frequência) ao core (que precisa
  estar no ar para o paciente). Rejeitado.

## Escolha
- **Watchdog nativo**: a unit do core é `Type=notify` com `WatchdogSec=45`; o
  core manda `READY=1` ao subir e `WATCHDOG=1` a cada 15 s
  (`DISPENSER_WATCHDOG_S`), pelo socket `NOTIFY_SOCKET`. Implementado em
  `core/saude.py` com `AF_UNIX` direto, sem dependência nova. Sem
  `NOTIFY_SOCKET` (dev, demo) o watchdog é no-op: é infraestrutura, nunca
  dependência do fluxo da dose.
- **Instância única por `flock`** em `/run/dispenser/core.lock`
  (`core/instancia.py`). Segundo core sai com código 3, antes de tocar no
  banco. O lock é do kernel: `SIGKILL` por queda de energia o libera, então o
  boot seguinte assume sem intervenção.
- **Três serviços**:
  - `dispenser-core` — obrigatório, `Type=notify`, usuário `dispenser`, sem
    privilégio, `ProtectSystem=strict` com escrita só em `/var/lib/dispenser`;
  - `dispenser-ui` — opcional, com `Wants=` (nunca `Requires=`) no core, para
    **sobreviver** ao reinício do core e reconectar sozinha;
  - `dispenser-provision` — `ConditionPathExists=!/var/lib/dispenser/dispenser.env`,
    ou seja, roda só enquanto não há pareamento; não exige o core.
- **Recarga sem reinício**: `systemctl reload` manda SIGHUP, e o loop também
  compara o mtime do arquivo de provisionamento a cada volta. `_aplicar_provisionamento`
  troca a fonte da agenda e liga a entrega da outbox; **se o pareamento estiver
  incompleto, mantém a agenda que estava funcionando** — trocar uma agenda boa
  por uma vazia seria pior do que esperar. A dose em andamento não é tocada.
- **Encerramento gracioso**: SIGTERM fecha socket e banco com checkpoint do WAL;
  `TimeoutStopSec=30`.
- **Fuso do paciente** aplicado no processo (`TZ` + `tzset`) no boot, a partir de
  `DISPENSER_TZ`, para a agenda não depender do fuso do SO.

## Consequências
- Um core travado é reiniciado sozinho em ~45 s, e o reinício não duplica dose:
  o estado vive no SQLite e a `outbox` é idempotente por chave.
- A UI continua de pé quando o core reinicia e reconecta em backoff
  (1 s → 15 s, com jitter), em vez de esperar intervalo fixo.
- Sem pareamento, o aparelho toca alarme normalmente e acumula a fila; ao
  parear, a fila sai. Nada se perde.
- `dispenser-ui` e `dispenser-provision` podem ficar inativos sem prejuízo: o
  core sozinho já guia a dose por alarme e LED (ADR 006).
- O watchdog não cobre falha silenciosa **sem travamento** (ex.: agenda vazia
  por erro de parse no backend). Isso é coberto pela notificação `dose_perdida`
  (ADR 010) e fica como ponto a observar na validação no Pi.
