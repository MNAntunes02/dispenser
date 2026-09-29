# ADR 012 — Relógio não confiável: não disparar, avisar na tela e avisar o cuidador uma vez

Status: implementada (Fase 7, 2026-09-29).

## Contexto
O Raspberry Pi não tem RTC de fábrica. Depois de uma queda de energia sem rede,
o sistema pode subir com a hora de 1970 — ou com um horário plausível, mas
errado, se a última sincronização NTP foi há semanas.

A agenda é feita de **horários** ("08:00 do remédio"). Com a hora errada, o
core tem três saídas ruins:

- disparar 08:00 de todo dia às 08:00 de algum dia de 1970: alarme impossível
  de obedecer e nenhum aviso ao cuidador;
- disparar em horário que o paciente não reconhece ("tocou às 3h da manhã");
- **não disparar e não dizer nada**: o pior de todos, porque o silêncio parece
  "hoje não tem remédio".

O AGENTS.md é explícito: "Relógio inválido (Pi sem RTC): não disparar por horário
não confiável; avisar." O usuário confirmou nesta fase que a política correta é
**avisar por horário errado é pior que atrasar a dose**, e que o cuidador deve
receber um aviso quando isso acontecer.

## Opções consideradas
- **Confiar sempre no relógio do SO** — comportamento atual antes da Fase 7.
  Rejeitado: alarme em horário impossível não é recuperável pelo paciente.
- **`ntpd`/RTC físico** — resolve a causa raiz, mas exige hardware adicional e
  não cobre queda de energia com o cartão removido. Mantido como item de
  instalação (o instalador não instala NTP porque a imagem do Ubuntu já tem
  `systemd-timesyncd`), mas **não** pode ser a única defesa.
- **Só validar no boot (faixa aceitável) e seguir** — mais simples, mas o
  relógio pode ficar ruim *depois* do boot (NTP perdido, salto de fuso, correção
  do usuário). Rejeitado.
- **Tratar a hora como dado não confiável, com estados explícitos** — escolhido.

## Escolha
- `core/relogio.py` classifica a hora em três estados:
  - `INVALIDO`: abaixo de `DISPENSER_DATA_MINIMA` (padrão `2024-01-01`) — o
    caso clássico do Pi sem RTC;
  - `INSTAVEL`: salto maior que `DISPENSER_TOLERANCIA_SALTO_S` (padrão 300 s)
    medido contra o relógio **monotônico**; assim uma correção de NTP não é
    confundida com o tempo passando;
  - `CONFIVEL`: o resto.
- Enquanto não for `CONFIVEL`, o `tick` **para inteiro**: não sincroniza agenda,
  não dispara, não conta timeout, não marca dose como tomada. É a única política
  que respeita "nunca marcar dose como tomada sem confirmação **e** sensores".
- O **alarme em andamento é desligado** (`buzzer("off")`) e a dose fica parada,
  sem timeout: barulho que o paciente não consegue localizar só gera cansaço.
- A **tela mostra o aviso** (`relogio_nao_confiavel` / `relogio_instavel`, em
  `core/textos.py`) com a orientação de pedir ajuda ao cuidador. A UI não decide
  nada: o core já manda a frase pronta (ADR 009).
- Ao voltar a ser confiável, o core: ressincroniza a agenda, retoma os
  temporizadores da dose ativa **a partir de agora** (não retroativamente),
  marca como `NAO_ATENDIDA` as doses mais de `DISPENSER_JANELA_ATRASO_S`
  (padrão 15 min) atrasadas — disparar em fila doses de horas atrás toca alarme
  num horário que ninguém reconhece — e repinta a tela.
- O cuidador recebe **um aviso agregado por indisponibilidade**, com motivo
  `relogio`, na coleção `Notificacoes` (ADR 010), com a contagem de doses
  perdidas e sem nome de medicamento no log local. Três dias sem NTP não viram
  dezenas de avisos.
- O fuso do paciente é explícito (`DISPENSER_TZ`, padrão `America/Sao_Paulo`) e
  aplicado no processo com `tzset`, para que "08:00" signifique 08:00 onde o
  paciente está, e não onde o SO do Pi estiver.

## Consequências
- Lost power + sem rede: o aparelho avisa na tela em vez de tocar alarme errado,
  e o cuidador fica sabendo por que o dia ficou sem lembrete.
- A dose do dia pode ser perdida de verdade — é o preço conscious escolhido
  pelo usuário. Por isso o aviso ao cuidador é obrigatório, não opcional.
- Um salto legítimo de relógio (usuário corrige a hora na mão) gera um aviso de
  `relogio`. É aceito: mais um aviso explicativo é melhor que dose em horário
  errado. Se incomodar no uso, a tolerância é configurável.
- O piso de 2024 é conservador de propósito: se o paciente usa o aparelho em
  2030, basta mover `DISPENSER_DATA_MINIMA` na configuração.
- Com NTP funcionando, nenhum desses estados ocorre; a validação no Pi precisa
  confirmar `timedatectl show -p NTPSynchronized` = `yes`.
