# Progresso do projeto

Atualize este arquivo ao final de cada fase. Ele é carregado no início de cada sessão.

## Estado atual
- Fase atual: 2 (Núcleo), não iniciada
- Última fase aprovada: 1 (Arquitetura), 2026-09-20

## Fases
| # | Fase | Status | Aprovada em | Notas |
|---|---|---|---|---|
| 0 | Descoberta | concluída | 2026-09-20 | Ver `dispenser/docs/DESCOBERTA.md` |
| 1 | Arquitetura | concluída | 2026-09-20 | ADRs 001-005 em `docs/decisoes/`; esqueleto criado |
| 2 | Núcleo | pendente | | |
| 3 | Sync com backend | pendente | | |
| 4 | Hardware real | pendente | | |
| 5 | UI (LCD) | pendente | | |
| 6 | Notificações | pendente | | |
| 7 | Boot e robustez | pendente | | |
| 8 | Entrega | pendente | | |

## Decisões tomadas
Arquitetura (Fase 1, ADRs 001-005 em `docs/decisoes/`):
- **001**: core em Python 3; **002**: UI Flutter Linux/arm64; **003**: core↔UI por Unix socket + JSON; **004**: placa por USB serial (115200), protocolo JSON em `docs/PROTOCOLO.md`, debounce na placa; **005**: sync polling (~15s) + fila outbox em SQLite.
- Estrutura criada: `core/`, `ui/`, `hardware/bridge/`, `deploy/`, `config/`, `tests/`, `docs/`. Git inicializado em `dispenser/` (commit `96bd34c`).

Suposições da Fase 0 (respondidas pelo usuário; detalhes e riscos em `dispenser/docs/DESCOBERTA.md`):
- Gaveta abre livremente, sem trava; sensores só detectam.
- Um medicamento por slot; devolução do recipiente inteiro.
- Não existe firmware de placa; protocolo proposto na Fase 1.
- Tela LCD HDMI sem touch; sem RTC no Pi (depender de NTP).
- Alarme: repetir a cada 2 min, até 5 tentativas, sem soneca.
- Cuidador notificado pelo mesmo mecanismo do app (sem push ainda).
- Dispensador com credencial própria no backend; exige ajustar `firestore.rules` (fora de `dispenser/`, com autorização, na Fase 3).
- Um paciente, um dispensador.
- Registro de adesão atual só confirma "tomada" (`Historico`); não há estado perdida/pulada — Fase 6 evoluirá o schema de forma compatível.

## Pendências e perguntas em aberto
- **Pi e placa não disponíveis** ainda; validar ambiente (comandos do spec 00 §2) quando chegarem.
- Testes rodam via `.venv` em `dispenser/` (o pytest global do usuário está quebrado: `ModuleNotFoundError`).
- Ajuste de `firestore.rules` para credencial própria (Fase 3; requer autorização).
- Notificação de dose perdida depende de o app estar logado (sem FCM) — avaliar push na Fase 6.
- Alarmes (2 min, 5x, sem soneca) validar com usuário na Fase 6.

## Próximo passo
Rodar `/fase 2` (ler `dispenser/docs/spec/03-fluxo-dose.md` e `dispenser/docs/spec/06-testes-entrega.md`).
