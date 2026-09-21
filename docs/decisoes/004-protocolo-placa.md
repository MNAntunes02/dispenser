# ADR 004 — Protocolo com a placa: JSON sobre USB serial (CDC)

Status: aprovada (Fase 1, 2026-09-20). Firmware a implementar seguindo `docs/PROTOCOLO.md`.

## Contexto
Não existe firmware pronto; a Fase 1 deve propor o protocolo. A placa (Arduino/ESP32) liga ao Pi por USB serial ou I2C (decisão fixa do AGENTS.md). Gadgets: sensores de gaveta (aberta/fechada) e de presença do recipiente por slot, LEDs por slot, buzzer e botões físicos. A gaveta é de abertura livre (sem trava/atuador).

## Opções consideradas
- **Link USB serial (CDC)** — plug-and-play, caminho estável via udev (`/dev/serial/by-id`), fácil depuração.
- **I2C** — menos pinos, porém dependência de endereçamento, pull-ups e mais frágil na prática.

## Escolha
Foi escolhido **USB serial (CDC) a 115200 baud** com protocolo de linhas JSON (UTF-8, um objeto por linha), handshake `ident` com versão, `ack/nack`, timeout de 500 ms com 3 tentativas, heartbeat 2 s (timeout 5 s) em ambos os sentidos e **debounce dos sensores na placa**.

## Motivo
USB serial é o vínculo mais simples e de manutenção previsível no Pi; JSON legível facilita testes e o simulador. Debounce na placa mantém a ponte apenas como tradutora de transições (edge events), reduzindo carga e complexidade no host. Códigos de falha e tempos detalhados em `docs/PROTOCOLO.md`.