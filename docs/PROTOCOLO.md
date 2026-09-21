# Protocolo com a placa e comunicação core ↔ UI

Versão de protocolo: **1**. Referência: ADR 001, 003, 004. Firmware ainda não existe; este documento é a contrato a implementar (a placa deve segui-lo).

## 1. Protocolo com a placa (USB serial CDC)

### Transporte
- USB serial (CDC-ACM), **115200 baud, 8N1**, identificado por caminho estável (`/dev/serial/by-id/...` via regra udev).
- **Linhas JSON**: UTF-8, um objeto por linha (`\n`), limite de **512 bytes** por linha.
- Todo comando do host recebe `ack`; ver "Tempos e retentativas".

### Mensagens comuns
| Campo | Tipo | Descrição |
|---|---|---|
| `v` | int | Versão do protocolo (1) |
| `seq` | int | Id da requisição (único por conexão) |
| `cmd` | string | Comando (ver abaixo) |
| `t` | string | Tipo (`comando`/`evento`/`hb`) em eventos e heartbeat |

### Handshake (`ident`)
1. Host → placa: `{"v":1,"seq":1,"cmd":"ident"}`
2. Placa → host:
   - ok: `{"v":1,"seq":1,"ack":true,"cmd":"ident","fw":"0.1.0","placa":"esp32","slots":4}`
   - erro: `{"v":1,"seq":1,"ack":false,"cmd":"ident","erro":"mgs"}`
3. Sem resposta: 2 retentativas; depois `FALHA_F001` e reconexão.

### Ack geral (todo comando respondido com ack)
- `{"v":1,"seq":N,"ack":true,"cmd":"<cmd>"}` ou `{"v":1,"seq":N,"ack":false,"cmd":"<cmd>","erro":"..."}`.

### Comandos (host → placa)
| Comando | Payload | Resposta |
|---|---|---|
| `ident` | — | fw, placa, slots |
| `status` | — | sensores atuais: `{"sensores":{"gaveta":0|1,"slots":{"0":{"presente":0|1},"1":{...}}}}` |
| `led` | `slot` (int; `-1` = todos), `estado` (`on`/`off`/`pisca`) | ack |
| `buzzer` | `padrao` (`dose`/`retorno`/`falha`/`off`) | ack |

Não há comando de liberar/travar: a gaveta é de abertura livre.

### Eventos (placa → host)
Formato: `{"v":1,"t":"evento","e":"<evento>", ...}`
- `gaveta_aberta`, `gaveta_fechada`
- `slot_presente` com `slot`: N
- `slot_ausente` com `slot`: N
- `botao` com `id`: `"confirma"`/`"avanca"`/`"volta"`/etc.
- `falha` com `codigo`: `F0xx` e `info` (opcional)

### Debounce
- **Na placa (firmware)**: transições somente após estado estável por **≥ 50 ms**; eventos são **de borda** (um por transição). A ponte só traduz.

### Heartbeat
- `{"v":1,"t":"hb"}` em **ambos os sentidos a cada 2 s**, sem payload adicional.
- Sem nenhuma mensagem (hb ou outra) por **5 s** → `FALHA_F004`, fecha porta, reconecta e re-faz handshake.

### Tempos e retentativas
- Timeout de resposta a comando: **500 ms**.
- Retentativas por comando: **2** (total de 3 tentativas); ao esgotar → `FALHA_F002`.
- Reconexão: aguardar **2 s**, com backoff até **30 s**; re-handshake obrigatório.

### Códigos de falha
| Código | Significado |
|---|---|
| F001 | Handshake sem resposta (após 3 tentativas) |
| F002 | Timeout de resposta a comando |
| F003 | Sensor incoerente (ex.: gaveta aberta + slot presente impossível; leitura flutuante) |
| F004 | Perda de heartbeat |
| F005 | Mensagem inválida (parse/tamanho/seq fora de ordem) |
| F006 | Falha interna reportada pela placa |

## 2. Comunicação core ↔ UI (Unix socket)

Ref.: ADR 003.

### Transporte
- Unix domain socket **`/run/dispenser/core.sock`**, permissão **600**, newline-delimited JSON, reconexão automática dos dois lados (UI reconecta ao abrir o socket; core notifica por `health`).

### Envelope
`{"v":1,"type":"<tipo>", "ts":"<ISO-8601 local>", ...}`

### Core → UI
| type | Campos | Uso |
|---|---|---|
| `agenda` | `ocorrencias:[{id,medicamento,dosagem,slot,horario}]` | Telas de agenda (Fase 5) |
| `ocorrencia` | `id,medicamento,dosagem,slot,horario,fase` | Início/retomada de guia de dose |
| `estado` | `fase,ocorrenciaId` | Mudança de fase da máquina de estados |
| `alerta` | `codigo,mensagem` | Falha/sensor incoerente/relógio inválido |
| `health` | — | Heartbeat do core |

### UI → Core
| type | Campos | Uso |
|---|---|---|
| `input` | `acao` (`confirma`/`cancela`/`silenciar`) | Confirmações da tela |
| `resposta` | `ids:[...]` | Ack de eventos recebidos |
| `comando` | `cmd,args` | Manual/depuração (ex.: iniciar simulação) |
| `health` | — | Heartbeat da UI |

Este conjunto é o contrato base e será extendido conforme Fases 2 e 5 (sempre versionado por `v`).