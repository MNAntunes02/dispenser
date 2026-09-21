# ADR 006 — Doses simultâneas e parâmetros do fluxo

Status: aprovada (Fase 2, 2026-09-21).

## Contexto
`docs/spec/03-fluxo-dose.md` deixa duas políticas em aberto: o que fazer com
doses simultâneas/sobrepostas e os valores iniciais de alarme, tentativas,
timeout de gaveta/retorno e limite de "não devolvido".

## Opções consideradas
- **Doses simultâneas**: uma por vez em fila por horário (com desempate por
  medicamento); ou tocar alarmes de todas ao mesmo tempo.
- **Alarme**: repetir a cada 2 min até 5 tentativas, sem soneca (sugerido no
  spec); ou com soneca / mais tentativas.

## Escolha
Validada com o usuário: **uma ocorrência por vez, fila ordenada por horário**;
a próxima só é liberada quando a atual termina. Parâmetros: alarme a cada
2 min (até 5 tentativas), sem soneca; gaveta 2 min; retorno 2 min →
`RETORNO_PENDENTE`; limite de 30 min para notificar "não devolvido". Todos
configuráveis por variável de ambiente (`DISPENSER_*`).

## Motivo
Toque de um único alarme por vez reduz confusão do usuário (mais seguro que
múltiplos alarmes simultâneos) e mantém a fila simples e determinística. Os
valores iniciais seguem a sugestão do spec 03 e ficam ajustáveis sem código.
Ver implementação em `core/maquina_estados.py`, `core/config.py` e
`docs/fluxo-dose.md`.