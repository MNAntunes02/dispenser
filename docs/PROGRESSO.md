# Progresso do projeto

Atualize este arquivo ao final de cada fase. Ele é carregado no início de cada sessão.

## Estado atual
- Fase atual: 3 (Sync com backend), não iniciada
- Última fase aprovada: 2 (Núcleo), 2026-09-21

## Fases
| # | Fase | Status | Aprovada em | Notas |
|---|---|---|---|---|
| 0 | Descoberta | concluída | 2026-09-20 | Ver `dispenser/docs/DESCOBERTA.md` |
| 1 | Arquitetura | concluída | 2026-09-20 | ADRs 001-005 em `docs/decisoes/`; esqueleto criado |
| 2 | Núcleo | concluída | 2026-09-21 | Máquina pura, agendador, SQLite/outbox, coordenador; 50 testes verdes; ADR 006 |
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

Núcleo (Fase 2, ADR 006 + `docs/fluxo-dose.md`):
- Doses simultâneas: **uma por vez, fila por horário** (validado com o usuário).
- Parâmetros aprovados: alarme 2 min / 5 tentativas / sem soneca; gaveta 2 min; retorno 2 min → `RETORNO_PENDENTE`; limite 30 min → notificar. Configuráveis por env (`DISPENSER_*`).
- FSM pura (`core/maquina_estados.py`) com 10 estados do spec; `core/agendador.py` (recorrência por abrev pt_BR, id determinístico); SQLite (`core/armazenamento.py`): `ocorrencias`, `outbox` (chave única), `log_eventos` sem nomes de medicamento (LGPD); `core/coordenador.py` orquestra agenda+relógio+ponte; `core/sync.py` fila + idempotência (transporte real na Fase 3); mensagens pt-BR centralizadas em `core/textos.py`; demo `python -m core.demo`.

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
Rodar `/fase 3` (ler `dispenser/docs/DESCOBERTA.md` e `dispenser/docs/spec/01-arquitetura.md`). Requer autorização para ajustar `firestore.rules`.
