# Fluxo da dose (máquina de estados)

A máquina de estados é **pura**: entrada = eventos, saída = ações. Sem acesso direto a serial, tela ou rede. Cada transição gera um evento com timestamp, gravado localmente e enviado ao backend por fila offline.

## Transições
| Estado | Evento | Próximo estado | Ações |
|---|---|---|---|
| AGUARDANDO | chegou o horário da dose | ALARME | buzzer, LED do slot, tela "Hora do remédio: {nome}, {dose}" |
| ALARME | usuário reconhece (botão OK/tela) | AGUARDANDO_GAVETA | parar buzzer; tela "Abra a gaveta" (destrava se houver trava) |
| ALARME | timeout sem resposta e tentativas < N | ALARME | repetir alarme, tentativa + 1 |
| ALARME | tentativas = N | NAO_ATENDIDA | registrar dose perdida; notificar cuidador/app |
| AGUARDANDO_GAVETA | `gaveta_aberta` | GAVETA_ABERTA | tela "Retire o medicamento do slot {n}" |
| AGUARDANDO_GAVETA | timeout | ALARME | conta como nova tentativa |
| GAVETA_ABERTA | `slot_ausente(n)` | MEDICAMENTO_RETIRADO | tela "Tome o medicamento e pressione OK" |
| MEDICAMENTO_RETIRADO | botão OK | AGUARDANDO_RETORNO | registrar ingestão confirmada; tela "Devolva ao slot {n} e feche a gaveta" |
| AGUARDANDO_RETORNO | `slot_presente(n)` e gaveta fechada | CONCLUIDA | registrar; tela "Tudo certo! Próxima dose às {hora}"; apagar LED |
| AGUARDANDO_RETORNO | timeout | RETORNO_PENDENTE | lembrete na tela, LED do slot aceso, aviso sonoro |
| RETORNO_PENDENTE | `slot_presente(n)` e gaveta fechada | CONCLUIDA | registrar |
| RETORNO_PENDENTE | persistir além do limite | RETORNO_PENDENTE | notificar cuidador/app com motivo "medicamento não devolvido" |
| NAO_ATENDIDA, CONCLUIDA | evento registrado | AGUARDANDO | aguardar próxima ocorrência |
| qualquer | `falha(codigo)` ou estado incoerente | FALHA | avisar na tela, registrar, notificar; NÃO assumir dose tomada |
| AGUARDANDO | `gaveta_aberta` fora de horário | AGUARDANDO | registrar evento, alerta LED/tela; não é dose |

## Regras
- Intervalo e número de repetições do alarme, janela de tolerância e política de soneca são **configuráveis**. Valores iniciais sugeridos (confirmar com o usuário): repetir a cada 2 min, até 5 tentativas, sem soneca.
- Idempotência por ID de ocorrência: dose já concluída não reabre.
- Doses simultâneas ou sobrepostas: fila ordenada por horário; documentar a política e validar com o usuário.
- Reinício no meio de uma dose (queda de energia): persistir o estado e retomar sem duplicar nem perder eventos.
- Notificação ao cuidador usa o mecanismo que o app já tem (descoberto na Fase 0); nunca criar um canal novo sem aprovação.
- Testes obrigatórios da máquina: fluxo feliz, alarme sem resposta, dose não tomada, medicamento não devolvido, gaveta aberta fora de horário, falha de sensor, reinício no meio da dose.
