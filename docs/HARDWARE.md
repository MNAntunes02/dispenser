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
| Botão confirmar | Entrada digital (com pull-up) | Pino GPIO | Confirma ingesta |
| Botões navegação | Entrada digital | Pinos GPIO | Avançar/voltar (ou similar), conforme UI |
| LED por slot | Saída (via driver/transistor) | Pino GPIO + transistor | Indica gaveta a abrir |
| Buzzer | Saída (transistor) | Pino PWM/GPIO | Padrões: dose, retorno, falha |
| Alimentação | 5 V | USB/painel da placa | LEDs/buzzer não devem puxar do pino |

### Sensores por slot
- **Presença**: recipiente (blister/frasco) presente ou ausente — define retorno pendente e guia de adesão.
- **Gaveta**: estado aberta/fechada — dispara a janela de "abrir & ingerir & devolver".

## Mapeamento slot → medicamento
- Definição na Fase 3/4: mapeamento determinístico (ex.: 1ª gaveta = 1º medicamento cadastrado) ou etapa de configuração no boot. Pendência registrada.

## Tabela de pinos (a preencher com a placa real)
| Objeto | Slot/ID | Pino | Nota |
|---|---|---|---|
| (a definir) | | | |

## Testes de hardware
Checklist e cenários em `TESTE_HARDWARE.md` (Fase 4/8).