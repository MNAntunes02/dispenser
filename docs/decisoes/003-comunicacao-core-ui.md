# ADR 003 — Comunicação core ↔ UI: Unix socket + JSON

Status: aprovada (Fase 1, 2026-09-20).

## Contexto
`dispenser-core` e `dispenser-ui` são processos independentes na mesma máquina. Um deve sobreviver e reconectar quando o outro reiniciar (ex.: UI reinicia sem derrubar o núcleo). Mensagens de agenda, ocorrências, mudanças de estado e entrada do usuário precisam trafegar em ambos os sentidos.

## Opções consideradas
- **Unix domain socket + JSON (newline-delimited)** — local-only, permissão 600, sem porta exposta, suportado nativamente por Python (`socket`) e Dart (`dart:io` UnixDomainSocket).
- **TCP em 127.0.0.1** — funciona igualmente, mas expõe porta e exige cuidados de auth no loopback.
- **WebSocket local** — útil se a UI fosse web; desnecessário para Flutter native.

## Escolha
Mensagens JSON (um objeto por linha) sobre Unix socket em `/run/dispenser/core.sock` (permissão 600), com reconexão automática dos dois lados.

## Motivo
Segurança por escopo local (sem rede), simplicidade de serialização nos dois lados e reconexão trivial. O formato das mensagens (versionadas por `type`) será definido em PROTOCOLO core↔UI no qual a Fase 5 (UI) e a Fase 2 (núcleo) se apoiam.