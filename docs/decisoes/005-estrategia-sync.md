# ADR 005 — Estratégia de sync: polling + outbox

Status: aprovada (Fase 1, 2026-09-20). Implementação detalhada na Fase 3.

## Contexto
O dispensador precisa da agenda salva pelo app (`UsuarioMedicamento/{userId}/Medicamentos`) e deve enviar eventos de adesão (dose tomada/perdida/retorno pendente) de forma **offline-first**, sem perder eventos em rede instável. O Pi sem RTC depende de NTP e o relógio pode ser inválido no boot. A agenda muda raramente.

## Opções consideradas
- **Polling + fila outbox** — leitura periódica (ex.: a cada 15 s) + fila de eventos em SQLite com retry/backoff e idempotência por chave de ocorrência.
- **Listeners em tempo real (Firestore `onSnapshot`)** — agenda atualiza na hora, mas o stream gRPC é pesado e frágil em rede instável.

## Escolha
Polling da agenda a cada ~15 s + **outbox** em SQLite para eventos, com retry/backoff, marcação de envio e chave de idempotência por ocorrência. `Busca` (lembrete de compra) é ignorada: fora do escopo de dose.

## Motivo
Rede instável e raridade de mudanças favorecem polling leve; o outbox garante entrega eventual e não perde eventos offline, exigência de segurança do paciente. Detalhes de credencial própria, regras Firestore e conflitos ficam na Fase 3.