# ADR 001 — Linguagem do core: Python 3

Status: aprovada (Fase 1, 2026-09-20).

## Contexto
O `dispenser-core` é um daemon de longa duração no Raspberry Pi 3 (2x ARM Cortex-A53, 1 GB de RAM, Ubuntu). Precisará de acesso a serial/I2C, cache local em SQLite, sync com o Firestore do app, agendamento de doses e alto testabilidade autônoma (Fase 2 roda sem hardware). O projeto reaproveita um app Flutter (Dart), mas o núcleo não precisa de UI.

## Opções consideradas
- **Python 3** — `pyserial`/`smbus2` para serial/I2C, `sqlite3` na stdlib, ecossistema Firebase (REST ou `google-cloud-firestore` com service account), `pytest` para testes, RAM ~50-80 MB.
- **Go** — binário estático leve, ótimo daemon, mas mais código novo e menor agilidade de prototipagem.
- **Dart CLI** — reaproveita o conhecimento em Dart, mas serial/I2C têm ecossistema fraco e cross-compile para arm64 é trabalhoso.

## Escolha
Python 3 (>= 3.9, a versão do Ubuntu do Pi).

## Motivo
Menor esforço para o conjunto de necessidades (serial, SQLite, Firestore, testes), consumo compatível com 1 GB, código simples de auditar em campo e manutenção facilitada. Dart/Go não compensam o custo de ferramental/ecossistema serial para este caso.