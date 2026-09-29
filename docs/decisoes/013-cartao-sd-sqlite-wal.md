# ADR 013 — Cartão SD: SQLite em WAL, journal volátil e trilha com retenção

Status: implementada (Fase 7, 2026-09-29).

## Contexto
O Raspberry Pi 3 usa cartão SD. Dois custos do cartão dominam o desgaste:

1. **Escrita por transação.** O modo padrão do SQLite (journal de rollback)
   cria, escreve e apaga um arquivo de journal a cada commit. Um commit por
   evento de dose multiplica as escritas no cartão.
2. **Log sem teto.** O journald por padrão guarda tudo, para sempre, e o
   `log_eventos` do SQLite cresce junto. Meses de uso matam o cartão — e o
   cartão morto derruba a memória de doses.

Ao mesmo tempo, o AGENTS.md é rígido: "Idempotência: a mesma ocorrência de dose
nunca é aberta duas vezes" e "Falta de rede nunca impede alarme". Ou seja, não
se pode trocar integridade por flash NAND.

## Opções consideradas
- **Nulo de journal, `PRAGMA synchronous=FULL`** — durability máximo, mas cada
  commit dá `fsync` no cartão. Aprovado como base do WAL, rejeitado sozinho.
- **Gravar o estado em arquivo texto** — semântica de fsync/journal impossível de
  replicar com a idempotência exigida. Rejeitado.
- **Base no cartão, estado em RAM com snapshot periódico** — perde o evento
  entre snapshots; uma dose tomada sem registro é exatamente o que o cuidador
  não pode receber. Rejeitado.
- **WAL + `synchronous=NORMAL` + retenção + journald volátil** — escolhido.
- **Rotacionar para disco externo** — resolve, mas o aparelho passa a depender
  de outro hardware e do orçamento do usuário. Fora do escopo.

## Escolha
- **WAL** (`journal_mode=WAL`): a transação escreve uma vez no `-wal` em vez de
  criar/apagar journal. Ganho grande no cartão, e leitores (uma tela de
  diagnóstico) não bloqueiam a escrita.
- **`synchronous=NORMAL`**: com WAL, o SO só precisa ordenar as escritas; numa
  queda de energia perde-se **no máximo a última transação**, e o próprio banco
  se recupera. A fila `outbox` e a ocorrência são gravadas em transações
  distintas justamente para que perder a última não apague o que já era
  verdade. `busy_timeout=5000` faz um leitor concorrente esperar em vez de
  falhar com "database is locked".
- **`wal_checkpoint(TRUNCATE)` no encerramento**: o core fecha consolidando o
  WAL, então um `SIGTERM` (e um boot seguinte) não deixa fragmentação
  acumulada.
- **Retenção da trilha**: `log_eventos` é cortado depois de
  `DISPENSER_RETENCAO_LOG_DIAS` (padrão 90), no máximo **uma vez por dia**
  (guarda em memória), para não escrever no cartão a cada tick de 5 s. `0`
  desliga a purga.
- **A fila `outbox` NUNCA é purgada.** É o que garante não perder um aviso na
  falta de rede: enquanto o cuidador não recebeu, o registro fica. Cortar a fila
  por idade seria, na prática, descartar a notícia de que o paciente não tomou
  o remédio.
- **journald volátil** (`/etc/systemd/journald.conf.d/10-dispenser.conf`):
  `Storage=volatile` com `RuntimeMaxUse=32M` e teto por tempo. O log de uma
  partida não vira escrita permanente; o que importa para auditoria fica no
  SQLite e no Firestore.
- **Lock e socket em `/run`** (tmpfs): some no boot e não gasta o cartão.

## Consequências
- O desgaste do cartão cai bastante: o idle não escreve nada, o watchdog pulsa
  de 15 em 15 s em RAM, e o banco grava por transação em vez de journal+commit.
- A janela de perda é de **um evento**: o que foi confirmado na tela e na máquina
  de estados, mas ainda não commitado, pode sumir numa queda de energia. A
  sequência de confirmação (usuário + sensores) é commitada antes de o evento
  ser enfileirado, então o cuidador nunca recebe "tomada" para algo que o
  aparelho não registrou.
- Se a auditoria de longo prazo for necessária, ela está no Firestore
  (`Historico` e `Notificacoes`), não no cartão.
- A retenção de 90 dias é um número de projeto, não medido. Em um aparelho real,
  vale olhar o tamanho do banco depois de algumas semanas de uso e ajustar
  `DISPENSER_RETENCAO_LOG_DIAS`.
- Se o cartão corromper (`state.db` ilegível), o core ainda sobe e mostra a tela
  de repouso, mas perde a fila: **essa recuperação ainda não está implementada**
  e é o próximo candidato a fase (ver `docs/PROGRESSO.md`).
