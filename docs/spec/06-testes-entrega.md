# Testes e entrega

## Testes mínimos
- **Máquina de estados**: todos os cenários de `03-fluxo-dose.md`.
- **Agendador**: recorrências, fuso, virada de dia, doses simultâneas.
- **Sync offline**: fila de eventos, reenvio, idempotência, reautenticação.
- **Integração** com a ponte simulada: fluxo completo sem hardware.
- **Hardware real**: roteiro manual em `dispenser/docs/TESTE_HARDWARE.md`.
Rode os testes antes de encerrar cada fase e cite o resultado no resumo.

## Definição de pronto
- [ ] Liga o Raspberry e o sistema inicia sozinho.
- [ ] Doses cadastradas no app aparecem e disparam no horário certo.
- [ ] Fluxo completo: alarme, abrir gaveta, ingerir, devolver, concluir.
- [ ] Dose perdida e medicamento não devolvido repetem alarme e notificam cuidador/app.
- [ ] Funciona sem internet e sincroniza eventos ao voltar a rede, sem duplicar.
- [ ] Reinício por queda de energia retoma o estado corretamente.
- [ ] Testes passando e roteiro de hardware executado.
- [ ] Nenhum segredo no repositório; README com instalação reproduzível do zero e aviso de que não é dispositivo médico certificado.
