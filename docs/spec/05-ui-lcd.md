# Interface (LCD, alarme, LEDs, botões) (Fase 5)

## Tela
- Fonte grande, alto contraste, frases curtas, **um passo por tela**.
- Textos em português do Brasil, num único arquivo de strings.
- Passos do fluxo guiado:
  1. "Hora do remédio: {nome}, {dose}. Pressione OK."
  2. "Abra a gaveta."
  3. "Retire o medicamento do slot {n}."
  4. "Tome o medicamento e pressione OK."
  5. "Coloque o medicamento de volta no slot {n} e feche a gaveta."
  6. "Tudo certo! Próxima dose às {hora}."
- Tela de repouso: hora atual, próxima dose, indicador de conexão e de falhas.
- Se o app tiver identidade visual (cores, logo, tipografia), reaproveitar sem alterar o app.

## Alarme, LEDs e botões
- Padrões sonoros distintos: dose, lembrete de retorno, falha. Volume seguro. Soneca só se a política definida permitir.
- LED: indica o slot correto, estado de erro e conectividade.
- Botões físicos com função única e clara (OK, ajuda; soneca/pular só se permitido). Mapear e documentar em `docs/HARDWARE.md`.
- A UI nunca decide o estado da dose: apenas exibe o estado do core e envia eventos de botão.
