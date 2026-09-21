# Ponte de hardware e protocolo com a placa

## Regras
- Todo acesso a hardware passa por `HardwareBridge`. Duas implementações: **real** (serial/I2C) e **simulada** (controlável por script/CLI para reproduzir todo o fluxo sem o dispensador).
- Porta serial por caminho estável (`/dev/serial/by-id/...`) com regra udev; nunca `/dev/ttyUSB0` fixo.
- Reconexão automática se a placa for desconectada ou reiniciada.
- Se já existir firmware, o protocolo real dele manda: leia o código e documente. Se não existir, proponha um protocolo e peça aprovação antes de implementar.

## Protocolo (proposta, se não houver firmware)
- Formato simples, legível e versionado (linhas JSON ou comandos ASCII), com número de versão no handshake.
- Todo comando recebe `ack`; defina **timeout** e nº limitado de retentativas.
- **Heartbeat** nos dois sentidos; perda de heartbeat = estado de falha.
- Debounce dos sensores: definir se é na placa ou na ponte e documentar.

### Comandos mínimos (adaptar ao firmware real)
liberar/travar gaveta (só se houver trava), acender/apagar LED por slot, acionar buzzer com padrão (dose, lembrete de retorno, falha), consultar estado dos sensores.

### Eventos mínimos
`gaveta_aberta`, `gaveta_fechada`, `slot_presente(n)`, `slot_ausente(n)`, `botao(id)`, `falha(codigo)`.

## Entregáveis
- `dispenser/docs/PROTOCOLO.md` (mensagens, tempos, códigos de falha).
- `dispenser/docs/HARDWARE.md` (ligações, pinos, sensores, alimentação).
- Simulador com cenários: fluxo feliz, sem resposta, medicamento não devolvido, gaveta aberta fora de hora, falha de sensor, placa desconectada.
