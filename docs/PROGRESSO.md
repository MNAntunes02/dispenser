# Progresso do projeto

Atualize este arquivo ao final de cada fase. Ele é carregado no início de cada sessão.

## Estado atual
- Fase atual: **7 (Boot e robustez) concluída** em 2026-09-29: systemd (core/ui/provision, Type=notify com watchdog, instância única por flock), relógio não confiável com política segura, SQLite em WAL + retenção, journald volátil, install/uninstall idempotentes, backoff de reconexão na UI. Testes Python 210/210 e Flutter 22/22 verdes. `app-saude` não foi alterado (regra 4).
- Próximas: Fase 8 (entrega) — gerar o pacote de instalação, validar no Pi (Fase 3b-run/4) quando chegar.

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
| 6 | Notificações | concluída | 2026-09-29 | Avisos em `Notificacoes`; 163 Python; ADR 010 |
| 7 | Boot e robustez | concluída | 2026-09-29 | systemd + watchdog + relógio + SD; 210 Python + 22 Flutter; ADRs 011-013; `docs/BOOT.md` |
| 8 | Entrega | pendente | | pacote de instalação e validação no Pi |

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

Notificações (Fase 6, ADR 010 + `docs/firestore-integracao.md`):
- **Escopo aprovado pelo usuário**: só o dispensador escreve; `app-saude` intocado (regra 4) e nenhuma regra nova (a subcoleção já é liberada ao dispensador vinculado).
- Avisos em `UsuarioMedicamento/{paciente}/Notificacoes` — motivos `dose_perdida`, `nao_devolvido` (limite de 30 min) e `falha` (inclusive sem dose em andamento, com `dia`+`codigo` e sem `nome`). Campos: `motivo`, `mensagem` (pt-BR de `core/textos.py`), `dia` dd/MM/yyyy, `horario_previsto`, `horario_real`, `nome`, `codigo`, `em`.
- `docId` determinístico `n+sha1({occ}|{tipo})[:20]` → reenvio sobrescreve o mesmo aviso. `Historico` continua **só** dose tomada (o app conta adesão positiva).
- `core/notificador.py` enfileira na `outbox` (chave `UNIQUE` absorve a duplicidade entre `registrar` e `notificar`; falha sem dose usa `sem_dose|falha|{codigo}|{dia}`); `Sincronizador._TIPOS_AVISO` despacha; offline mantém pendente e não trava o fluxo da dose.
- `core/transporte.py`: `registro_notificacao` + `doc_notificacao_id` + `gravar_notificacao` (real e fake), escrita por `_gravar` único (retry em 401). `_registrar` passou a carimbar `horario_real` em todos os eventos.
- **Testes**: +23 em `tests/test_notificacoes.py` (mapeamento, dedup, offline/entrega única, reenvio sem duplicar, falha com e sem dose, dose perdida fora do `Historico`, fluxo feliz sem aviso, transporte REST real com 401/403/sem rede, log sem nome de medicamento — LGPD). Total **163 pytest** verdes.
- **Não entra nesta fase**: repetir o aviso periodicamente (escalonamento com intervalo — precisa de validação do usuário), FCM/push, e o app consumir `Notificacoes`.

Boot e robustez (Fase 7, ADRs 011-013 + `docs/BOOT.md`):
- **Decisões aprovadas pelo usuário**: fuso sempre `America/Sao_Paulo`; relógio inválido **não** agenda nem dispara e avisa na tela; venv em `/opt/dispenser` com wrappers em `/usr/local/bin` também nesta fase; `dispenser-provision` condicionado à ausência do arquivo de provisionamento; core recarrega o provisionamento sem reiniciar; relógio ruim gera aviso **agregado** ao cuidador (um por indisponibilidade, não um por dose).
- **Relógio** (`core/relogio.py`, ADR 012): estados `CONFIVEL`/`INVALIDO`/`INSTAVEL` com piso `DISPENSER_DATA_MINIMA` (2024-01-01) e tolerância de salto medida contra relógio **monotônico** (NTP perdido não confunde com tempo passando). `aplicar_fuso_com_padrao` fixa `TZ`+`tzset` no boot; fuso errado cai no padrão em vez de derrubar o core. Enquanto não confiável o `tick` para inteiro, o **buzzer em andamento é desligado** e a dose fica sem timeout. Ao recuperar: ressincroniza, retoma temporizadores a partir de agora, marca `NAO_ATENDIDA` as doses >`DISPENSER_JANELA_ATRASO_S` (15 min) atrasadas e repinta a tela. Aviso `relogio` em `Notificacoes` (chave `sem_dose|relogio|{dia}`), sem nome de medicamento no log.
- **Watchdog** (`core/saude.py`, ADR 011): `Type=notify` + `WatchdogSec=45`; `READY=1` no boot e `WATCHDOG=1` de 15 em 15 s pelo `NOTIFY_SOCKET` (AF_UNIX direto, **sem** pacote systemd). Falha de socket desliga o watchdog e avisa uma vez, sem derrubar o core.
- **Instância única** (`core/instancia.py`): `flock` em `/run/dispenser/core.lock`; segundo core sai com código 3 antes de tocar no banco. Lock é do kernel: `SIGKILL` por queda de energia o libera.
- **Cartão SD** (ADR 013): `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000`, checkpoint TRUNCATE ao fechar; `purga_logs` corta `log_eventos` após 90 dias, **uma vez por dia**; a `outbox` **nunca** é purgada. journald volátil (`Storage=volatile`, 32 MB) em `deploy/journald/10-dispenser.conf`.
- **systemd**: três units — `dispenser-core` (Type=notify, usuário `dispenser`, `ProtectSystem=strict`, `ExecReload=SIGHUP`), `dispenser-ui` (**`Wants=`**, não `Requires=`: sobrevive ao reinício do core), `dispenser-provision` (`ConditionPathExists=!/var/lib/dispenser/dispenser.env`, não exige o core). `systemd-analyze verify` sem erro de diretiva.
- **Entrada**: `core/dispenser_main.py` reescrito — fuso no boot, lock, watchdog, SIGHUP, detecção por mtime do arquivo provisionado, `Sincronizador.enviar_item` como callback da outbox. Recarga incompleta **mantém a agenda que funcionava** em vez de trocar por uma vazia.
- **UI** (`ui/lib/src/canal.dart`): `Backoff` (1 s → 15 s, fator 2, jitter) no lugar da espera fixa; `main.dart` passa a ler `DISPENSER_SOCKET` do **ambiente** (antes só lia `--dart-define`, então a unit não surtia efeito).
- **Entrega**: `deploy/install.sh` e `deploy/uninstall.sh` idempotentes, com `--executar` (padrão mostra só o plano), `--prefixo`, `--binario-ui`, `--dry-run` implícito; uninstall **não** apaga `/var/lib/dispenser` sem `--apagar-dados`. `deploy/udev/detectar-placa.sh` imprime a regra correta a partir dos IDs reais (a regra de fábrica ainda tem placeholder `XXXX`). `config/.env.example` reorganizado e virou o `/etc/dispenser/dispenser.conf`.
- **Testes**: +44 pytest (27 em `test_relogio.py`, 17 em `test_boot.py`) e +3 `flutter test` (`test/backoff_test.dart`) — total **210 pytest** e **22 Flutter** verdes, `flutter analyze` limpo. Verificado de ponta a ponta fora do systemd: boot, recusa do 2º core (exit 3), recarga por mtime ("provisionamento aplicado: agenda via Firestore") e SIGTERM gracioso.
- **Não validado no Pi** (falta o aparelho): `Type=notify`/watchdog real, IDs da placa no udev, `timedatectl`/NTP e o caminho offline até 1970, grupos do kiosk, queda de energia física, `flutter build linux` arm64. Lista em `docs/BOOT.md`.

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
- **Regras do Firestore publicadas** em 2026-09-29 (`firebase deploy --only firestore:rules` em `app-saude/`, projeto `app-saude-8fba1`). Sem passo de `firebase init`: o `firebase.json`/`.firebaserc` já existiam. Restam os passos manuais no console: criar o usuário Auth do dispensador e anotar o UID na credencial 600 (`{"email","senha","uid"}`) e o doc `Dispensadores/{uidDispenser} = {usuarioId}` (o passo 2 passa a ser feito pelo app no pareamento) — passos em `docs/firestore-integracao.md`. Sem isso o sync real não autentica e o UID do vínculo não existe.
- Notificação de dose perdida **já sai para o backend** (Fase 6: `Notificacoes`); falta o app consumir e o **push** para chegar com o app fechado — avaliar FCM como fase seguinte.
- Alarmes (2 min, 5x, sem soneca) validar com o usuário (pendente das Fases 6/7).
- Repetir o aviso do cuidador periodicamente (escalonamento): intervalo precisa de validação do usuário; hoje sai **um aviso por ocorrência** (também no caso do relógio, que é agregado por indisponibilidade).
- **Cartão SD corrompido**: se o `state.db` ficar ilegível, o core sobe sem histórico local e a fila é perdida. Recuperação (backup/reescrita do banco) é candidata à Fase 8.
- `flutter_blue_plus` 2.x exige `License.nonprofit` no `connect` — reavaliar `License.commercial` se o projeto virar uso comercial.