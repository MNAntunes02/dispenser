# Hardware — ligações, pinos, sensores e alimentação

> **Estado**: proposta da Fase 1, a validar quando o hardware chegar. Pi e placa ainda não estão disponíveis.
> Decisões fixas: gaveta de abertura livre (sem trava), um medicamento por slot, devolução do recipiente inteiro, LCD HDMI sem touch, placa por USB serial.

## Visão geral

- **Host**: Raspberry Pi 3 B+ (Ubuntu), 1 GB RAM.
- **Placa controladora**: Arduino-compatível ou ESP32 com USB nativo (CDC-ACM), ligada ao Pi por **USB serial** (`/dev/serial/by-id/...`, regra udev).
- **Tela**: LCD HDMI sem touch (conteúdo renderizado por `dispenser-ui`, Flutter em kiosk).
- **Alarme**: buzzer na placa (padrões em PROTOCOLO.md) + tela; opcionalmente áudio do Pi.
- **Gaveta**: abertura manual livre; sensores apenas detectam aberta/fechada.

## Componentes e ligações (proposta a validar)

| Sinal | Tipo | Interface | Observação |
|---|---|---|---|
| Gaveta aberta/fechada | Entrada digital (fim de curso ou IR) | Pino GPIO da placa | Um por gaveta (ou comum a todas, se físico único) |
| Presença do recipiente | Entrada digital (micro switch/IR) | Pino GPIO | **Um por slot** |
| Botão OK | Entrada digital (com pull-up) | Pino GPIO | Único botão: confirma ("OK") |
| Botão ajuda (opcional) | Entrada digital (com pull-up) | Pino GPIO | **Só dia com cuidador por perto**: avisa que o sensor falhou e a dose precisa ser conferida. Não confirma dose. |
| LED por slot | Saída (via driver/transistor) | Pino GPIO + transistor | Indica gaveta a abrir |
| Buzzer | Saída (transistor) | Pino PWM/GPIO | Padrões: dose, retorno, falha |
| Alimentação | 5 V | USB/painel da placa | LEDs/buzzer não devem puxar do pino |

### Botões na UI do LCD
- A tela do LCD (sem touch) é renderizada por `dispenser-ui` e tem **um botão "OK" na
  tela**. Ele só aparece quando o core publica `esperaBotao: true` e envia
  `{"type":"input","acao":"confirma"}` — a UI não decide nada (ADR 009).
- Não há botão "pular", "adiar" nem "silenciar": a política aprovada (Fase 0) é repetir o
  alarme a cada 2 min, até 5 tentativas, **sem soneca**.
- O botão físico **OK** da placa produz o mesmo efeito (`botao` com `botao:"confirma"`):
  a dose não exige touchscreen.
- O botão de **ajuda** é lido pelo core só para o caso de falha de sensor: mostra na tela
  que algo está errado e a dose precisa ser conferida manualmente. Ele **nunca** marca a
  dose como tomada.

### Sensores por slot
- **Presença**: recipiente (blister/frasco) presente ou ausente — define retorno pendente e guia de adesão.
- **Gaveta**: estado aberta/fechada — dispara a janela de "abrir & ingerir & devolver".

## Mapeamento slot → medicamento
- Ordem definida pelo app no vínculo Bluetooth (Fase 3b): o app envia a lista de
  medicamentos, e o **slot é o índice na ordem recebida** (0 = primeiro). Persistir essa
  ordem no SQLite local, senão uma reordenação no app muda a gaveta de um medicamento.
- Pendência da Fase 4: com o mapeamento ausente, o core ainda publica `slot` em branco
  (`null`) e a tela usa a variante `_sem_slot` ("devolva ao compartimento"), e o passo de
  retorno aceita **qualquer** slot. Isso é seguro para a adesão (o paciente devolve) e
  impreciso para a auditoria por slot — corrigir quando a placa chegar.

## Tabela de pinos (a preencher com a placa real)
| Objeto | Slot/ID | Pino | Nota |
|---|---|---|---|
| (a definir) | | | |

## Testes de hardware
Checklist e cenários em `TESTE_HARDWARE.md` (Fase 4/8).