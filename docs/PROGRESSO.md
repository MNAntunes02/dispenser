# Progresso do projeto

Atualize este arquivo ao final de cada fase. Ele é carregado no início de cada sessão.

## Estado atual
- Fase atual: **5 (UI do LCD) concluída** em 2026-09-29, com core real, socket real e
  transporte FFI real testados ponta a ponta. Falta rodar no Pi (kiosk + tela real).
- Próximas: Fase 3b-run e Fase 4 (hardware real), ambas dependem do Pi/placa chegarem.

## Fases
| # | Fase | Status | Aprovada em | Notas |
|---|---|---|---|---|
| 0 | Descoberta | concluída | 2026-09-20 | Ver `dispenser/docs/DESCOBERTA.md` |
| 1 | Arquitetura | concluída | 2026-09-20 | ADRs 001-005 em `docs/decisoes/`; esqueleto criado |
| 2 | Núcleo | concluída | 2026-09-21 | Máquina pura, agendador, SQLite/outbox, coordenador; ADR 006 |
| 3 | Sync com backend | concluída | 2026-09-21 | Firestore REST + credencial própria; 99 testes verdes; ADRs 007 e 008 |
| 3b | Vínculo BT (onboarding) | concluída | 2026-09-21 | `docs/BLUETOOTH.md`; GATT Pi + provisionador + rede + aba Dispositivo do app; validar no Pi (Fase 3b-run) |
| 4 | Hardware real | pendente | | depende de Pi/placa |
| 5 | UI (LCD) | concluída | 2026-09-29 | 19 testes Flutter + 140 Python; ADR 009 |
| 6 | Notificações | pendente | | |
| 7 | Boot e robustez | pendente | | |
| 8 | Entrega | pendente | | |

## Decisões tomadas
Arquitetura (Fase 1, ADRs 001-005 em `docs/decisoes/`):
- **001**: core em Python 3; **002**: UI Flutter Linux/arm64; **003**: core↔UI por Unix socket + JSON; **004**: placa por USB serial (115200), protocolo JSON em `docs/PROTOCOLO.md`, debounce na placa; **005**: sync polling (~15s) + fila outbox em SQLite.
- Estrutura criada: `core/`, `ui/`, `hardware/bridge/`, `deploy/`, `config/`, `tests/`, `docs/`. Git inicializado em `dispenser/`.

Núcleo (Fase 2, ADR 006 + `docs/fluxo-dose.md`): doses simultâneas **uma por vez, fila por horário**; parâmetros aprovados (alarme 2min/5x/sem soneca; gaveta 2min; retorno 2min→pendente; limite 30min); FSM pura com 10 estados; agendador pt_BR; SQLite (`ocorrencias`, `outbox` idempotente, `log_eventos` sem nomes — LGPD); coordenador + ponte injetável; textos pt-BR em `core/textos.py`; demo `python -m core.demo`.

Sync com backend (Fase 3, ADRs 007 e 008 + `docs/firestore-integracao.md`):
- **Credencial própria**: usuário dedicado do Firebase Auth (email/senha) + transport Firestore REST com Bearer token (`identitytoolkit`); renovação em 401/expiração; falha de rede = offline.
- `core/transporte.py`: `TransporteFirestore` (real) + `TransporteFake` (memória) + mapeamento de `Medicamentos`→agenda; `Historico` de `dose_tomada` com docId determinístico (`sha1`), campos `dia` dd/MM/yyyy, `horario_previsto`, `horario_real`, `nome` (formato do app). Só `dose_tomada` sai nesta fase; demais ficam na fila (Fase 6).
- `core/sync.py`: `Sincronizador` (ciclo agenda + envio) e `FonteAgendaLocal` (cache); `core/armazenamento.py`: tabela `agenda_cache`.
- `core/dispenser_main.py`: com credencial configurada usa Firestore; senão demo/`DISPENSER_AGENDA_JSON`. `.env.example` += `DISPENSER_FIREBASE_API_KEY` e formato do arquivo 600.
- `app-saude/firestore.rules` **ajustadas** (autorizado): `isDispenserDo` + coleção `Dispensadores` (paciente cria/atualiza o vínculo).

Vínculo BT (Fase 3b, ADR 008 implementada + `docs/BLUETOOTH.md`):
- **Pi**: `core/provisionamento.py` (FSM pura: código 6 dígitos one-time/10 min, validação, net, env 600 via `MontadorChunks`); `core/dispenser_main.py` carrega `/var/lib/dispenser/dispenser.env`; entrypoint `core/provision_main.py` (`dispenser-provision`, `--simulado` sem HW); `rede/rede.py` (`RedeLinux` nmcli→netplan + `RedeSimulada`); `hardware/gatt/` (`ServicoGattSimulado` + `ServicoGattBlueZ` D-Bus — só no Pi); `hardware/tela.py`. `requirements` += `dbus-next`.
- **App (autorizado)**: `pubspec` += `flutter_blue_plus` (connect exige `License.nonprofit`); `lib/services/dispositivo_ble.dart` (`ParqueamentoBle` + fake, chunking ≤240 B) e `lib/services/vinculo_dispensador.dart` (Firestore `Dispensadores/{uid}` + fake); aba `lib/main/dispositivo.dart` reescrita (não vinculado → escaneando → pareando → vinculado/Reconfigurar/Desvincular); permissões BLE em AndroidManifest e Info.plist; regras `Dispensadores` com leitura restrita ao dono.
- **Testes**: +30 pytest no Pi (99 no total) e 12 `flutter test` no app; todo o fluxo herméticamente fechado com fakes. **Validar** `ServicoGattBlueZ`, `RedeLinux`, LCD/botão no Pi (Fase 3b-run).

UI do LCD (Fase 5, ADR 009 + `docs/PROTOCOLO.md` §2):
- **A UI não decide**: o core renderiza a frase em `core/textos.py` e envia pronta em `estado.mensagem`, com `chave`, `passo` (1..6), `totalPassos`, `esperaBotao` e `fluxo` (dose/reposo/alerta). A UI só desenha e devolve `input:confirma`. Sem soneca (ADR 006).
- **Core**: `ServidorUI(caminho, retrato=…, relogio=…, intervalo_health_s=…)` com fila de entradas, wake-up por evento e `health` de 2 s em evento próprio; `Coordenador.definir_ui/definir_publicador_ui/retrato_cache/tick()` integra a UI sem que a thread do socket toque SQLite/FSM; telas de repouso `reposo`/`reposo_sem_dose` publicadas quando não há dose (sem isso a UI ficaria em "conectando").
- **UI** (`ui/`): Flutter Linux/arm64, kiosk. `modelo.dart` (contrato tipado), `canal.dart` (**FFI/AF_UNIX** — `dart:io` não expõe AF_UNIX; `socket/connect/send/recv/poll` numa isolate, reconexão automática), `cliente_core.dart` (parsing + watchdog de heartbeat), `controlador.dart` (4 telas), `telas.dart` (alto contraste, `_Encolhe`/`FittedBox`), `tema.dart`, `rotulos.dart` (fallback, paridade testada).
- **Testes**: 19 `flutter test` (18 unit/widget sobre `CanalMemoria` + 1 de integração que sobe `core.demo --sem-mini-ui` e confirma a dose inteira pelo socket FFI real) e 140 pytest. `flutter analyze` limpo. Demo validado ponta a ponta.
- **Pendências**: rodar no Pi (kiosk, tela real, testar `flutter build linux` — falta toolchain clang/ninja/GTK no snap); goldens visuais não criados; slot ainda `null` (ver HARDWARE.md).

Suposições da Fase 0 (respondidas pelo usuário; detalhes e riscos em `dispenser/docs/DESCOBERTA.md`):
- Gaveta abre livremente, sem trava; um medicamento por slot; devolução do recipiente inteiro.
- Não existe firmware de placa; tela LCD HDMI sem touch; sem RTC no Pi (depender de NTP).
- Alarme: repetir a cada 2 min, até 5 tentativas, sem soneca.
- Cuidador notificado pelo mesmo mecanismo do app (sem push ainda).
- Dispensador com credencial própria no backend; um paciente, um dispensador.
- Registro de adesão atual só confirma "tomada" (`Historico`); Fase 6 evoluirá o schema de forma compatível.
- **Vínculo app↔dispensador via Bluetooth** (novo): BT = onboarding/provisionamento (Wi-Fi + config Firebase, serviço GATT + código de 6 dígitos no LCD, automático no 1º boot + botão); os dados continuam na nuvem. Implementação na Fase 3b.

## Pendências e perguntas em aberto
- **Pi e placa não disponíveis** ainda; validar ambiente (comandos do spec 00 §2) e a parte real da 3b (GATT BlueZ, NetworkManager, LCD/botão) quando chegarem (Fase 3b-run).
- Testes rodam via `.venv` em `dispenser/` (o pytest global do usuário está quebrado: `ModuleNotFoundError`).
- **Deploy manual pendente no console Firebase**: ler/adotar as regras novas (`firebase deploy --only firestore:rules`), criar o usuário Auth do dispensador e anotar o UID na credencial 600 (`{"email","senha","uid"}`) e o doc `Dispensadores/{uidDispenser} = {usuarioId}` (o passo 2 passa a ser feito pelo app no pareamento) — passos em `docs/firestore-integracao.md`. Sem isso o sync real não autentica e o UID do vínculo não existe.
- Notificação de dose perdida depende de o app estar logado (sem FCM) — avaliar push na Fase 6.
- Alarmes (2 min, 5x, sem soneca) validar com usuário na Fase 6.
- `flutter_blue_plus` 2.x exige `License.nonprofit` no `connect` — reavaliar `License.commercial` se o projeto virar uso comercial.