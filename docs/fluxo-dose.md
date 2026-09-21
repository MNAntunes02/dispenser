# Fluxo da dose: política operacional

Documenta a política escolhida e validada com o usuário (Fase 2) e os
parâmetros configuráveis. A máquina de estados em si e cada transição
estão em `docs/spec/03-fluxo-dose.md`; a implementação é
`core/maquina_estados.py`.

## Parâmetros (valores iniciais aprovados)
| Parâmetro | Valor | Variável de ambiente |
|---|---|---|
| Passo do loop principal | 5 s | `DISPENSER_TICK_S` |
| Repetição do alarme | 2 min | `DISPENSER_ALARME_INTERVALO_S` |
| Máximo de tentativas | 5 | `DISPENSER_MAX_TENTATIVAS` |
| Soneca | desativada | — |
| Tempo para abrir a gaveta | 2 min | `DISPENSER_TIMEOUT_GAVETA_S` |
| Tempo para devolver | 2 min → `RETORNO_PENDENTE` | `DISPENSER_TIMEOUT_RETORNO_S` |
| Limite de "não devolvido" | 30 min → notificar | `DISPENSER_LIMITE_RETORNO_S` |

Na última tentativa sem resposta a dose passa a `NAO_ATENDIDA`: registra
perdida e notifica o cuidador; não reabre (idempotência por ocorrência).

## Doses simultâneas ou sobrepostas
Política aprovada: **uma ocorrência por vez, em fila ordenada por horário**
(e por medicamento, para empates). A próxima só é liberada quando a atual
termina (`CONCLUIDA`, `NAO_ATENDIDA` ou `FALHA`). Validada com o usuário.

## Sensores fora de expectativa
- `gaveta_aberta` sem ocorrência em andamento: não é dose; registra evento
  e alerta na tela (LED piscando).
- `falha(codigo)` ou estado incoerente: a ocorrência vai a `FALHA`, avisa na
  tela e **nunca** marca a dose como tomada. `FALHA` fica bloqueada até
  intervenção manual (reset no cadastro/reinício com estado persistido).
- Eventos de sensores que não se aplicam à fase atual são ignorados e
  registrados na trilha (sem tratamento de falha indevido). O sinal de
  retorno (`retorno_ok`) é sintético: exige slot presente **e** gaveta
  fechada.

## Retomada após reinício
O estado da ocorrência ativa persiste em SQLite (`ocorrencias.estado`).
No boot o coordenador recarrega a ativa, reavalia o retorno a partir dos
sensores e recomputa os timeouts pelo relógio, sem duplicar eventos (fila
outbox com chave única por ocorrência+tipo).

## Notificação
Notificações ao cuidador usam o mecanismo do app; nesta fase são apenas
registradas localmente (Fase 6 implementa o envio).