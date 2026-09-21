# Fase 1: Arquitetura

Objetivo: propor e registrar as escolhas de arquitetura e criar o esqueleto do projeto. Toda escolha vira ADR em `dispenser/docs/decisoes/`. **Peça aprovação antes de seguir para a Fase 2.**

## Módulos
| Módulo | Responsabilidade |
|---|---|
| Sync | Busca medicamentos/horários do backend do app e envia eventos (dose tomada, perdida, alertas), usando o mesmo fluxo de credenciais do app |
| Armazenamento local | SQLite: cache da agenda e **fila de eventos pendentes** para operar offline |
| Agendador | Converte a agenda em ocorrências de dose (fuso e recorrências idênticos ao app) |
| Máquina de estados da dose | Núcleo do sistema, puro e testável, sem acesso direto a serial ou tela (ver `03-fluxo-dose.md`) |
| Ponte de hardware | Interface `HardwareBridge` com implementação real e simulada (ver `02-hardware-protocolo.md`) |
| UI (LCD) | Tela guiada em tela cheia (ver `05-ui-lcd.md`) |
| Notificador | Escalonamento para cuidador/app com o mecanismo que o app já usa |
| Supervisor/boot | Serviços systemd, watchdog, logs (ver `04-boot-systemd.md`) |

Processos: `dispenser-core` (agendador + máquina de estados + ponte + sync + notificador) e `dispenser-ui` (tela), comunicando-se por socket local ou similar. Um deve reconectar sozinho se o outro reiniciar.

## Decisões a registrar em ADR (proponha, justifique, aguarde aprovação)
1. **Linguagem/stack do core.** Critérios: peso no Pi 3, acesso a serial/I2C, facilidade de testes, reaproveitamento de conhecimento do projeto. Justifique.
2. **Tecnologia da UI.** Compare no mínimo:
   - Flutter no Linux/arm64 ou flutter-pi (reaproveita tema e widgets do app; avaliar peso, necessidade de compilar fora do Pi, suporte à tela usada);
   - interface web em modo quiosque (Chromium em tela cheia; simples de evoluir, mais pesada no Pi 3);
   - UI nativa leve (Qt, Kivy, pygame; baixo consumo, mais código novo).
   Critérios: desempenho com 1 GB de RAM, estabilidade contínua, touch e botões físicos, manutenção, coerência visual com o app.
3. **Comunicação core ↔ UI.**
4. **Protocolo com a placa** (ver `02-hardware-protocolo.md`).
5. **Estratégia de sync** (polling, listeners em tempo real, conflitos, reautenticação).

## Estrutura de pastas a criar
```
dispenser/
├── README.md
├── docs/            (DESCOBERTA, PROTOCOLO, HARDWARE, TESTE_HARDWARE, decisoes/, spec/)
├── core/            (agendador, máquina de estados, sync, notificador)
├── ui/
├── hardware/
│   ├── bridge/      (implementação real e simulada)
│   └── firmware/    (somente se necessário)
├── deploy/          (systemd/, udev/, install.sh, uninstall.sh)
├── config/          (.env.example)
└── tests/
```
