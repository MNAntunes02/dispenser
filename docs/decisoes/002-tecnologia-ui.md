# ADR 002 — Tecnologia da UI: Flutter Linux/arm64

Status: aprovada (Fase 1, 2026-09-20).

## Contexto
A UI roda na tela LCD HDMI **sem touch**, navegação por botões físicos, em kiosk/tela cheia, no mesmo Pi 3 (1 GB de RAM). Deve manter coerência visual com o app Flutter (temas, fonte Inter) e ser estável por dias seguidos. O app já é Flutter.

## Opções consideradas
- **Flutter Linux/arm64 (GTK)** — reaproveita tema/widgets do app; roda no dev x86 durante o desenvolvimento; no Pi usa GLES/mesa (~200-300 MB).
- **flutter-pi** — renderer leve para Pi, porém ferramenta de terceiros com manutenção irregular.
- **Web kiosk (Chromium)** — simples de evoluir, mas ~300-450 MB de RAM e mais volátil no Pi 3.
- **Nativa leve (pygame/Kivy)** — baixíssimo consumo, porém código novo e sem coerência com o app.

## Escolha
Flutter na plataforma Linux desktop (aplicativo `dispenser-ui`).

## Motivo
Coerência visual e reaproveitamento direto do design do app; a UI é fina (telas guiadas por botões), mantendo RAM total estimada confortável (< 400 MB com o core). flutter-pi descartado por risco de manutenção; web por RAM/estabilidade; nativa leve por duplicar esforço sem ganho relevante aqui.