# Teste de hardware

> Placeholder da Fase 1. Este documento será preenchido na **Fase 4** (hardware real) com o checklist de validação dos sensores/padrões e na **Fase 8** (instalação do zero).

Cenários previstos (ver `spec/02-hardware-protocolo.md`):
- fluxo feliz (abrir → ingerir → devolver → confirmar);
- placa sem resposta (handshake/ack), desconexão e reconexão;
- medicamento não devolvido (retorno pendente);
- gaveta aberta fora de hora;
- falha de sensor / estado incoerente (F003).

Cada cenário roda primeiro no **simulador** (Fase 2) e depois com a placa real (Fase 4).