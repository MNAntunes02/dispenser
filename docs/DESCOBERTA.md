# Descoberta (Fase 0)

Data: 2026-09-20. Leitura do app Flutter (`app-saude/`), ambiente do Pi e placa, ANTES do projeto. Nenhum código de sistema foi escrito nesta fase.

## Resumo

- O app é **Firebase** (Firestore NoSQL + Firebase Auth), projeto `app-saude-8fba1`, com dados médicos sensíveis (LGPD). Regras atuais exigem `request.auth.uid == userId`.
- O agendamento é **semanal por dia da semana + horário**, com vários horários por dia e por medicamento, gravado em `Medicamentos` e replicado em notificações **locais** no celular (sem FCM/push).
- O registro de adesão existente é só de **confirmação de dose tomada** (`Historico`); não existe estado perdida/pulada, nem slot/gaveta, nem modelagem de cuidador, nem integração com hardware (página "Dispositivo" é placeholder).
- Para o dispensador, os maiores pontos de atenção são: (1) credencial própria exige ajuste de `firestore.rules`; (2) sem RTC o Pi depende de NTP e pode ter relógio inválido no boot; (3) "notificar cuidador/app" hoje significaria depender do app aberto/logado, a menos que se adicione push.

## 1. App Flutter

Tudo em `app-saude/`. Somente leitura; nada fora de `dispenser/` foi alterado.

### Backend
- **Firebase**: Firestore + Auth. Pacotes em `pubspec.yaml`: `firebase_core`, `firebase_auth`, `cloud_firestore`; `flutter_local_notifications` + `timezone` para lembretes.
- Config do projeto: `firebase.json` e `.firebaserc` (`app-saude-8fba1`, appId android `1:105292621423:android:f75787246ef12748710f9a`). Credenciais em `lib/firebase_options.dart` e `android/app/google-services.json` (este último foi visto presente mas é segredo do repositório do app; **nunca copiar**).
- Inicialização Firebase: `lib/main.dart:14-16`.
- Regras Firestore (`firestore.rules:6-14`, 1 linha por regra):
  - `Usuarios/{userId}` e `UsuarioMedicamento/{userId}/{document=**}`: ler/escrever somente se `request.auth != null && request.auth.uid == userId`.
  - **Consequência**: um dispensador com credencial própria não consegue ler/escrever nos dados do paciente sem alterar estas regras (ação fora de `dispenser/`, requer autorização na Fase 3).

### Autenticação
- Email/senha: `FirebaseAuth.signInWithEmailAndPassword` (`lib/login/login_screen.dart:18`) e `createUserWithEmailAndPassword` (`lib/login/cadastro/cadastro_conta.dart:18`).
- Não há conta de serviço, token de dispositivo nem fluxo de "login não humano" no app.
- Decisão (Q9): dispensador usará **credencial própria** e a Fase 3 tratará o ajuste de regras com autorização explícita.

### Modelos (coleções Firestore)
- `Usuarios/{userId}` (criado em `cadastro_conta.dart:28`): `nome`, `raca`, `genero`, `dataNascimento`, `cep`, `endereco`, `numero`, `complemento`, `bairro`, `cidade`, `estado`, `doencas[]`{`nome`,`ano`}, `fisico`, `psicologico`, `nutricionista`, `peso`, `altura`, `circunferenciaQuadril`, `circunferenciaAbdominal`, `email`. (dados intermediários em `cadastro_dados_basicos.dart`, `cadastro_localidade.dart`, `cadastro_dados_saude.dart`).
- `UsuarioMedicamento/{userId}/Medicamentos/{medicamentoId}` (criado em `remedio_add_dia.dart:280-284`):
  - `nome` (string), `dosagem` (string, ex. "500").
  - `dias[]`: array de `{dia_semana: string, horario: [string "HH:mm", ...]}`.
  - `dia_semana` é a abreviação **pt_BR** de `DateFormat('EEE','pt_BR')` (ex.: `seg`, `ter`, `qua`, `qui`, `sex`, `sáb` com acento, `dom`). O `notificacao_service.dart:373-378` mapeia índice 0 => domingo.
  - Vários medicamentos por usuário; vários dias e vários horários por medicamento.
- `UsuarioMedicamento/{userId}/Historico/{docId}` (criado em `medicamentos_do_dia.dart:72-77`): `dia` ("dd/MM/yyyy"), `horario_previsto` ("HH:mm"), `horario_real` ("HH:mm"), `nome`. **Somente confirmação**; sem `medicamentoId` nem status — colisão possível entre medicamentos de mesmo nome e impossível saber "perdida".
- `UsuarioMedicamento/{userId}/Busca/{docId}` (criado em `remedio_add_busca.dart:188-192`): `nome`, `dia` (DateTime/Timestamp), `hora` ("HH:mm"). É "lembrete para buscar/comprar o remédio", **fora** do escopo de dose do dispensador (registrado para não confundir).

### Agendamento
- Recorrência **semanal fixa** (dia da semana + horário). Sem intervalos "a cada X horas", sem "se necessário", sem janela de tolerância, sem fuso horário armazenado (usa o relógio local do aparelho), sem dose única por dia limitada (permite múltiplos horários).
- Replicado em notificações locais: `notificacao_service.dart:127-175` (`syncMedicamentos`), agendamento repetitivo com `matchDateTimeComponents: DateTimeComponents.dayOfWeekAndTime` (`notificacao_service.dart:229`) e fuso via `FlutterTimezone` (`notificacao_service.dart:102-103`).
- **Consequência**: o dispensador deve reconstruir a agenda a partir de `Medicamentos` usando a mesma semântica (dia da semana abreviado + "HH:mm"), no relógio local do Pi.

### Registro de adesão
- Confirmação por checkbox/diálogo (`medicamentos_do_dia.dart:105-134`) ou pelo botão "Tomei" da notificação (persistido pendente em `SharedPreferences`, `notificacao_service.dart:337-366`), gravando em `Historico`.
- Não existe estado tomada/perdida/pulada no app; a Fase 6 precisará definir como o dispensador registra dose não tomada de forma compatível (ex.: campo `status` em `Historico`).

### Slots
- **Não existe** conceito de gaveta/compartimento/slot no app. Página "Dispositivo" (`lib/main/dispositivo.dart`) é placeholder sem integração.
- Decisões (Q1, Q2, Q3): gaveta abre livremente (sem trava); **um medicamento por slot**; devolução do **recipiente inteiro** (sem contagem de comprimidos). O mapeamento medicamento->slot será definido na Fase 1/4 (ex.: 1ª gaveta = 1º medicamento cadastrado, configurável).

### Notificações
- **Somente locais** (`flutter_local_notifications`); sem FCM, sem SMS/e-mail. Ações na notificação: "Tomei" e "Adiar 5 min" (`notificacao_service.dart:212-225`).
- Não há modelagem de cuidador no app.
- Decisão (Q8): dose perdida notifica pelo **mesmo mecanismo do app** — na prática o dispensador registra o evento no backend (Fase 6) e o app consumiria; push real é pendência (ver Riscos).

### Hardware
- Nenhuma integração (Bluetooth, MQTT, serial) no código do app.

### Regras de negócio a replicar de forma idêntica
- Identidade de "dose" = (medicamento, `dia_semana`, `HH:mm`) — é como o app reconhece confirmações (`_chaveConfirmacao(nome, horario)` em `medicamentos_do_dia.dart:21`).
- `dia` em `Historico` e notificações usa formato **"dd/MM/yyyy"** (texto), não ISO.
- Abreviações de dia da semana pt_BR com acento ("sáb").
- "Adiar" no app re-notifica em **+5 min** (`notificacao_service.dart:301`).

## 2. Ambiente do Raspberry

- **Não há Pi disponível ainda** (usuário confirmou). Ambiente de trabalho atual é a máquina dev (Linux), não o Pi; nada da seção 2 do spec foi executado.
- Suposições a validar quando o Pi chegar (checklist de comandos do spec 00 §2):
  - Ubuntu (esperado arm64, `uname -m`), RAM e disco (`free -h`, `df -h /`), `timedatectl`.
  - Portas seriais (`ls /dev/serial/by-id /dev/ttyUSB* /dev/ttyACM*`) e barramento (`i2cdetect -y 1`) para a placa controladora.
  - Áudio do alarme (`aplay -l`).
- Decisões (Q5, Q6): tela LCD **HDMI sem touch** (navegação por botões físicos); **sem RTC** — relógio vem de NTP; sem rede no boot, relógio pode ser inválido e o sistema deve avisar e não disparar (regra de segurança do paciente).

## 3. Placa controladora

- **Não existe firmware pronto** (usuário confirmou). Lacuna registrada; proposta de protocolo (comandos, eventos, baud rate, formato) na Fase 1 (`spec/02-hardware-protocolo.md`).
- Previsão de hardware (decisões fixas do AGENTS.md): Arduino/ESP32 por USB serial ou I2C; sensores de gaveta aberta/fechada e presença do medicamento no slot; LEDs e botões ligados à placa.

## 4. Riscos

1. **Firestore rules impedem credencial própria** (regra de `uid == userId`). Mitigação: na Fase 3, com autorização, ajustar regras (fora de `dispenser/`) e usar credencial dedicada do dispensador; nunca copiar segredos.
2. **Notificação sem push**: "dose perdida notifica cuidador/app" só funciona com app aberto/logado hoje. Mitigação: registrar eventos no backend (Fase 6) e avaliar FCM como extensão do app (requer acordo).
3. **Relógio sem RTC**: sem NTP no boot, não disparar por horário não confiável; avisar. NTP deve ser habilitado/configurado no Pi (Fase 7).
4. **`Historico` sem status e sem `medicamentoId`**: não dá para marcar perdida nem distinguir medicamentos homônimos. Mitigação: evoluir o schema de forma compatível (campo `status`, `medicamentoId`) na Fase 6; não alterar o app sem autorização.
5. **Identidade de dose frágil** (nome + horário): replicar exatamente a chave do app; colisões de mesmo nome/horário devem ser tratadas e registradas como incoerência.
6. **LGPD / logs**: nomes de medicamentos e dados de saúde nunca em logs; segredos com permissão 600 fora do repo; TLS sempre; `.env.example` em vez de `.env`.
7. **Idempotência e sensores**: nunca marcar tomada sem confirmação do usuário e sensores; mesma ocorrência de dose nunca aberta duas vezes; sensor incoerente não é assumido (avisa + registra + notifica).
8. **Sem Pi/placa ainda**: Fases 2 (núcleo) rodam no simulador; Fase 4 dependerá do hardware chegar.

## 5. Perguntas em aberto

Todas foram respondidas na Fase 0; suposições registradas abaixo ficam valendo até serem reabertas:

1. Trava/atuador na gaveta? **Suposto: abre livremente, sem trava.** (respondido)
2. Quantos slots / relação com medicamentos? **Suposto: um medicamento por slot.** (respondido)
3. "Devolver ao slot" = recipiente inteiro? **Suposto: sim.** (respondido)
4. Firmware da placa? **Suposto: não existe; propor na Fase 1.** (respondido)
5. Tela LCD e touch? **Suposto: HDMI, sem touch.** (respondido)
6. RTC no Pi? **Suposto: não; depender de NTP.** (respondido)
7. Alarme (intervalo/tentativas/tolerância/soneca)? **Suposto: 2 min, 5 tentativas, sem soneca.** (respondido; validar com usuário na Fase 6)
8. Notificação ao cuidador? **Suposto: mesmo mecanismo do app (backend + app local).** (respondido)
9. Credencial própria no backend? **Suposto: sim; ajustar firestore.rules com autorização na Fase 3.** (respondido)
10. Múltiplos pacientes/dispensadores por conta? **Suposto: um paciente, um dispensador.** (respondido)

Pendência prática: **Pi e placa não estão disponíveis**; reavaliar ambiente (comandos da seção 2) quando chegarem.