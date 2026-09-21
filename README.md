# Dispensador de Medicamentos (Raspberry Pi + Ubuntu)

Sistema complementar ao app Flutter `app-saude/`: na hora da dose, alarme
sonoro + LEDs + tela LCD guiam o usuário a abrir a gaveta, ingerir o
medicamento e devolvê-lo ao slot; sensores confirmam cada etapa; se a dose
não for tomada, repete o alarme e notifica cuidador/app. Inicia sozinho no
boot e funciona offline.

> **Importante**: este projeto é um **auxiliar de adesão** e **não é um
> dispositivo médico certificado**. Não substitui orientação médica nem
> prescrição.

Documentação e estado do projeto: `docs/PROGRESSO.md`, `docs/DESCOBERTA.md`,
`docs/PROTOCOLO.md`, `docs/HARDWARE.md` e `docs/decisoes/`.

## Arquitetura (Fase 1)

- `dpenser-core` (Python 3): agendador + máquina de estados da dose + sync
  (polling + outbox) + notificador.
- `dpenser-ui` (Flutter Linux/arm64): telas guiadas no LCD HDMI (kiosk).
- Comunicação core ↔ UI: Unix socket com JSON (`/run/dispenser/core.sock`).
- Placa controladora (Arduino/ESP32): USB serial, protocolo JSON em
  `docs/PROTOCOLO.md`; todo acesso passa por `HardwareBridge` (real e
  simulada).

## Estrutura

```
core/       núcleo Python (daemon)
ui/         interface Flutter (LCD)
hardware/   ponte de hardware (real/simulada)
deploy/     systemd, udev, instalador
config/     .env.example (sem segredos)
tests/      testes pytest
docs/       documentação e decisões
```

## Desenvolvimento

```bash
pip install -r core/requirements.txt -r tests/requirements-dev.txt
pytest
```

A UI roda no dev (x86) com `flutter run` dentro de `ui/`; a compilação
arm64 para o Pi é feita na instalação (Fase 7/8).

## Configuração

Copie `config/.env.example` para o local de instalação e preencha. Segredos
(credenciais do backend) ficam em arquivo com permissão 600 **fora** do
repositório — nunca versione tokens ou `google-services.json`.