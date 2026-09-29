# ADR 010 — Avisos ao cuidador vão para a coleção `Notificacoes`, fora do `Historico`

Status: implementada (Fase 6, 2026-09-29).

## Contexto
O AGENTS.md exige avisar cuidador/app quando a dose não é tomada, quando o medicamento
não volta ao slot e quando um sensor falha. A Fase 0 descobriu que o app **não tem push**
(`flutter_local_notifications` só, sem FCM) e que o registro de adesão é apenas o
`Historico` de confirmações. A decisão Q8 foi: "notificar caregiver/app" = **registrar o
evento no backend**; push real fica pendente.

O `Historico` do app é lido por `medicamentos_do_dia.dart` (doses do dia, para exibir o
que foi tomado) e por `exportar_historico.dart` (relatório em PDF). Escrever um aviso de
"dose não tomada" ali faria o app contar uma dose como **tomada** — o oposto do desejado —
e poluiria o relatório de adesão.

O usuário confirmou nesta fase: escopo **só no dispensador** (o `app-saude` fica
intocado, regra 4 do AGENTS.md), destino `UsuarioMedicamento/{paciente}/Notificacoes`
(uma subcoleção que as `firestore.rules` atuais já liberam ao dispensador vinculado — sem
mexer em regra nem redeploy) e motivos `dose_perdida`, `nao_devolvido` e `falha`.

## Opções consideradas
- **Escrever o aviso no `Historico`** com um campo extra (`status`) — o app passaria a
  distinguir tomada de não tomada, mas quebraria a leitura atual (que só conhece
  `dia/horario_previsto/horario_real/nome`) e exigiria alteração no app. Rejeitado.
- **Coleção top-level `Notificacoes`** — mais fácil de listar no console do Firebase,
  mas exige criar regras novas e um novo deploy antes de qualquer aviso funcionar. A
  subcoleção do paciente já está coberta. Rejeitado.
- **Push FCM nesta fase** — é o que realmente entrega o aviso com o app fechado, mas
  exige FCM no app, chave no Pi e um ciclo de trabalho bem maior. Fica como fase futura.
- **Subcoleção `Notificacoes` do paciente, escrita pelo dispensador, consumida pelo app
  quando ele abrir** — caminho escolhido.

## Escolha
- Avisos vão para `UsuarioMedicamento/{PACIENTE}/Notificacoes/{docId}`, com
  `docId = "n" + sha1("{ocorrencia_id}|{tipo}")[:20]`: determinístico, então reenvio
  após queda de energia sobrescreve o mesmo doc (idempotência, sem duplicar aviso).
- Campos (todos `stringValue`, mesmo estilo do `Historico`): `motivo`
  (`dose_perdida` | `nao_devolvido` | `falha`), `mensagem` (frase pt-BR já renderizada
  em `core/textos.py`), `dia` (dd/MM/yyyy), `horario_previsto`, `horario_real`, `nome`,
  `codigo` (só em falha) e `em` (ISO do evento).
- `Historico` continua sendo **só** adesão positiva: dose perdida/nao devolvida nunca
  entra nele.
- O aviso **nunca** bloqueia o fluxo: o `Notificador` só enfileira na `outbox` (SQLite) e
  o `Sincronizador` despacha quando houver rede. Offline, a fila cresce e entrega depois.
- Sem ocorrência (falha de sensor com ociosidade) o aviso é gravado mesmo assim, com
  `motivo=falha`, `dia` do dia e sem `nome`/`horario`.
- Cada motivo é enfileirado **uma vez** por ocorrência: a chave `UNIQUE` da `outbox`
  (`{ocorrencia_id}|{tipo}`) absorve a duplicidade entre a ação `registrar` da máquina e a
  ação `notificar`; falha sem dose usa a chave `sem_dose|falha|{codigo}|{dia}`.
- Reenvio/recorrência de aviso (escalonar repetir a cada N min) **não** entra nesta fase:
  o intervalo precisa ser validado com o usuário junto com os parâmetros de alarme, e
  notificação repetida sem critério vira ruído para o cuidador.

## Consequências
- O `app-saude` continua funcionando sem alteração; quando quiser, basta ler
  `UsuarioMedicamento/{uid}/Notificacoes` e avisar o paciente/cuidador (mudança futura,
  fora do escopo do dispensador).
- Sem FCM o aviso só chega se alguém abrir o app — limitação conhecida e registrada em
  `docs/DESCOBERTA.md`.
- Nomes de medicamento continuam **fora** dos logs locais (LGPD); eles só aparecem no
  documento do aviso, que é dado de saúde no backend do próprio paciente, como já
  acontece no `Historico`.
