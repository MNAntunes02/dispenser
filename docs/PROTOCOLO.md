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

Ref.: ADR 003 (transporte) e ADR 009 (a UI nunca decide o estado da dose).

### Transporte
- Unix domain socket **`/run/dispenser/core.sock`**, permissão **600**, diretório `/run/dispenser` com `700`.
- **Newline-delimited JSON** (NDJSON): uma mensagem por linha, UTF-8, `
` como separador, máximo de 65536 bytes por linha.
- Reconexão automática dos dois lados. A UI reconecta sozinha quando o core cai; o core mantém o fluxo de dose **mesmo sem UI** (a UI é opcional por projeto, ver `dispenser_main.py`).
- O core envia `health` a cada 2 s. Se a UI parar de recebê-lo por mais de 6 s, mostra "core não responde" em vez de deixar uma tela parada fingindo que a dose está em dia.
- O `dart:io` do Flutter não expõe AF_UNIX: a UI usa `dart:ffi` (`socket/connect/send/recv/poll`) numa isolate separada — ver `ui/lib/src/canal.dart`.

### Envelope
`{"v":1,"type":"<tipo>","ts":"<ISO-8601 local>","<campo>":<valor>,...}`

Campos com valor `null` **não são enviados** (envelope mínimo).

### Core → UI

| type | Campos | Uso |
|---|---|---|
| `rotulos` | `rotulos:{<chave>:<texto>}`, `totalPassos` | Textos de domínio + nº de passos; enviado logo na conexão |
| `agenda` | `dia`, `ocorrencias:[{id,medicamento,dosagem,slot,horario,estado}]` | Próxima dose da tela de repouso |
| `estado` | `chave,mensagem,passo,totalPassos,fase,ocorrenciaId,slot,proxima,esperaBotao,fluxo` | Tela atual (ver abaixo) |
| `alerta` | `codigo,mensagem` | Falha de sensor, gaveta fora de horário, retorno pendente |
| `health` | — | Heartbeat |

#### Mensagem `estado`
- `mensagem`: **texto pronto**, renderizado no core a partir de `core/textos.py`. A UI não monta nem traduz frase de domínio.
- `chave`: identificador estável da tela (para testes e depuração).
- `passo`: 1..6 no fluxo guiado; **ausente** fora dele (repouso/aviso).
- `totalPassos`: sempre 6.
- `esperaBotao`: `true` apenas onde a dose só avança com um OK do paciente (`ALARME` e `MEDICAMENTO_RETIRADO`).
- `fluxo`: `dose` | `reposo` | `alerta` — diz à UI qual moldura desenhar.
- `slot`: pode não vir (depende do mapeamento do slot, ainda ausente — ver HARDWARE.md).

Exemplo:
```json
{"v":1,"type":"estado","ts":"2026-09-29T08:00:00","chave":"tome_e_ok","mensagem":"Tome o medicamento e pressione OK","fase":"MEDICAMENTO_RETIRADO","ocorrenciaId":"med-1|2026-09-29|08:00","passo":4,"totalPassos":6,"slot":3,"proxima":"","esperaBotao":true,"fluxo":"dose"}
```

### UI → Core

| type | Campos | Uso |
|---|---|---|
| `input` | `acao` — apenas `confirma` | Intenção do paciente. A política aprovada **não tem soneca**: não existe `cancela` nem `silenciar`. |
| `comando` | `cmd,args` | Manual/depuração (ex.: `simular`) |
| `health` | — | Heartbeat da UI |

A UI **nunca** confirma uma dose sozinha: ela só devolve a intenção. Quem valida é o core, junto com os sensores, no `Coordenador.tick()`.

### Telas e fluxo
Fluxo guiado de 6 passos (spec 05):

| passo | chave | sensor que avança |
|---|---|---|
| 1 | `hora_remedio` | botão OK |
| 2 | `abra_gaveta` | sensor de gaveta aberta |
| 3 | `retire_medicamento` | slot sem o medicamento |
| 4 | `tome_e_ok` | botão OK |
| 5 | `devolva_slot` |(slot de volta) e gaveta fechada |
| 6 | `tudo_certo` | — (fim da dose) |

Fora do fluxo, o core publica `reposo` (com `proxima`) ou `reposo_sem_dose`, e `alerta` para falhas. Sem a tela de repouso a UI ficaria em "conectando" para sempre — por isso o core sempre publica uma delas quando está ocioso.

### Reexecução
- Ao (re)conectar, a UI recebe o retrato completo: `rotulos`, `agenda` e a `estado` atual.
- O retrato é servido de um cache em memória atualizado no `tick()` — a thread do socket **nunca** toca no SQLite nem na máquina de estados.
