# Progresso do projeto

Atualize este arquivo ao final de cada fase. Ele é carregado no início de cada sessão.

## Estado atual
- Fase atual: 3 (Sync com backend), concluída em 2026-09-21
- Próximas: Fase 4 (hardware real) e Fase 3b (vínculo/provisionamento via Bluetooth — ADR 008, aguarda Pi + autorização do app)

## Fases
| # | Fase | Status | Aprovada em | Notas |
|---|---|---|---|---|
| 0 | Descoberta | concluída | 2026-09-20 | Ver `dispenser/docs/DESCOBERTA.md` |
| 1 | Arquitetura | concluída | 2026-09-20 | ADRs 001-005 em `docs/decisoes/`; esqueleto criado |
| 2 | Núcleo | concluída | 2026-09-21 | Máquina pura, agendador, SQLite/outbox, coordenador; ADR 006 |
| 3 | Sync com backend | concluída | 2026-09-21 | Firestore REST + credencial própria; 69 testes verdes; ADRs 007 e 008 |
| 3b | Vínculo BT (onboarding) | pendente | | Desenho aprovado (ADR 008); implementação depende de Pi/placa e autorização do app |
| 4 | Hardware real | pendente | | |
| 5 | UI (LCD) | pendente | | |
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

Suposições da Fase 0 (respondidas pelo usuário; detalhes e riscos em `dispenser/docs/DESCOBERTA.md`):
- Gaveta abre livremente, sem trava; um medicamento por slot; devolução do recipiente inteiro.
- Não existe firmware de placa; tela LCD HDMI sem touch; sem RTC no Pi (depender de NTP).
- Alarme: repetir a cada 2 min, até 5 tentativas, sem soneca.
- Cuidador notificado pelo mesmo mecanismo do app (sem push ainda).
- Dispensador com credencial própria no backend; um paciente, um dispensador.
- Registro de adesão atual só confirma "tomada" (`Historico`); Fase 6 evoluirá o schema de forma compatível.
- **Vínculo app↔dispensador via Bluetooth** (novo): BT = onboarding/provisionamento (Wi-Fi + config Firebase, serviço GATT + código de 6 dígitos no LCD, automático no 1º boot + botão); os dados continuam na nuvem. Implementação na Fase 3b.

## Pendências e perguntas em aberto
- **Pi e placa não disponíveis** ainda; validar ambiente (comandos do spec 00 §2) quando chegarem.
- Testes rodam via `.venv` em `dispenser/` (o pytest global do usuário está quebrado: `ModuleNotFoundError`).
- **Deploy manual pendente no console Firebase**: ler/adotar `app-saude/firestore.rules` (`firebase deploy --only firestore:rules`), criar o usuário Auth do dispensador e o doc `Dispensadores/{uidDispenser} = {usuarioId}` (passos em `docs/firestore-integracao.md`). Até lá o sync real não autentica.
- Fase 3b (BT/provisionamento): depende de Pi/LCD/botão chegarem e de autorização para alterar a aba Dispositivo no app Flutter.
- Notificação de dose perdida depende de o app estar logado (sem FCM) — avaliar push na Fase 6.
- Alarmes (2 min, 5x, sem soneca) validar com usuário na Fase 6.

## Próximo passo
Rodar `/fase 4` (ler `dispenser/docs/spec/02-hardware-protocolo.md`) — requer Pi e placa. Antes, se quiser o vínculo por Bluetooth, chame a **Fase 3b** (desenho já aprovado; precisa autorizar alterações no app).