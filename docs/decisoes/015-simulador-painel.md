# ADR 015 — Simulador de hardware no painel de desenvolvimento

Status: implementada (2026-11-09).

## Contexto

Sem o dispensador físico (Fase 4 pendente), o fluxo da dose trava nos passos
2, 3 e 5: só a placa gera `gaveta_aberta`, `slot_ausente`, `slot_presente` e
`gaveta_fechada`. O painel do ADR 014 já sobe core e UI num clique, mas
percorrer uma dose inteira exigia injetar `PonteSimulada.simular` por código
— impossível para quem usa só a janela.

O tipo `comando` do protocolo core↔UI (ADR 003/009) existia no contrato, mas
nenhum `cmd` era tratado: virava apenas log.

Restrição de segurança: o simulador não pode virar backdoor. A simulação
jamais confirma dose (eventos `ok`/`botao` são do paciente), jamais fabrica
falha de sensor e, com ponte real (produção), nada pode ser injetado por tela.

## Opções consideradas

- **Segundo socket só para o painel** — isolaria os comandos de depuração,
  mas criava superfície nova (outro arquivo em `/run`, outro watchdog e mais
  um contrato para manter). Rejeitado.
- **Painel chamando a ponte direto** — o painel é outro processo; exigiria
  RPC paralelo ao socket que já existe. Rejeitado.
- **Comando `simular` pelo socket da UI** — o painel vira mais um cliente do
  contrato vigente (ADR 003), com whitelist validada no core. Escolhido.

## Escolha

- Mensagem: `{"v":1,"type":"comando","cmd":"simular","args":{"evento":...,"slot":N}}`
  (`slot` apenas em `slot_presente`/`slot_ausente`), montada por
  `core.protocolo_ui.comando_simular` — fonte única do formato.
- Whitelist no protocolo (`EVENTOS_SIMULAVEIS`): cobre **só** sensores de
  gaveta e slot. `ok`/`botao`/`falha` são recusados tanto pelo construtor
  quanto pelo core; recusa gera `ui_comando_ignorado:*` no log e não levanta
  exceção (quem injeta é ferramenta de desenvolvimento).
- `HardwareBridge.simular` devolve `bool`: a base devolve `False` — e a
  ponte real **nunca** deve sobrescrever isso, pois hardware de verdade não
  fabrica leitura de sensor. Só a `PonteSimulada` aceita, validando o slot
  contra o número de slots do hardware.
- O coordenador injeta o evento na fila normal da ponte: mesmo caminho de um
  sensor físico, drenado no mesmo `tick()`. A FSM continua exigindo o OK do
  paciente e a sequência completa de sensores para `dose_tomada`.
- Painel: `painel/comandos.py` — cliente *one-shot* em thread daemon
  (conecta, envia, faz meia-fechadura e drena/descarta a resposta, para o
  servidor não sofrer `ECONNRESET`); a janela ganha o LabelFrame "Simulador
  de hardware" com seletor de slot e botões habilitados só com o core
  RODANDO. Sem reconexão: o próximo clique abre outra conexão.

## Motivo

- Mesmo socket e contrato da UI: zero superfície nova e o core continua o
  único decisor (ADR 009) — o painel só "aperta sensores".
- Whitelist + ponte que recusa: em produção o comando é inócuo; o sensor
  físico permanece a única fonte de verdade. A simulação nunca substitui o
  OK do paciente nem inventa estado de dose.
- Aproveitamento da Fase 2: a `PonteSimulada` já era injetável por código;
  o comando apenas a alcança pelo socket.
- Efeito colateral necessário e aceito: `ServidorUI._loop_cliente` passou a
  ler a entrada **antes** de enviar (e a drenar o buffer no EOF). Antes, um
  cliente que só envia (o painel) não era lido até o próximo `health` (até
  2 s) e, se fechasse antes disso, o comando se perdia no `EPIPE` do envio.
