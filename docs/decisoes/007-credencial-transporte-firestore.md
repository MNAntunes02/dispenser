# ADR 007 — Credencial própria + transporte Firestore REST

Status: aprovada (Fase 3, 2026-09-21).

## Contexto
O dispensador precisa ler `UsuarioMedicamento/{paciente}/Medicamentos` e gravar
`Historico` de adesão sem ser o usuário do app. As regras atuais exigem
`request.auth.uid == userId`. Dados de saúde são sensíveis (LGPD): mínimo
privilégio e endpoint oficial, sem expor a senha do paciente.

## Opções consideradas
- **Usuário dedicado (email/senha) + Firestore REST com Bearer** — credencial própria
  do dispensador no Firebase Auth; token via `identitytoolkit`; chamadas HTTP v1 do
  Firestore. Respeita as regras e o escopo mínimo.
- **Admin SDK (service account)** — acesso total, ignoraria as regras; privilégio alto
  demais para um aparelho doméstico.

## Escolha
Usuário dedicado do Firebase Auth + `TransporteFirestore` (REST): `signInWithPassword`
→ idToken (headers `Bearer`), renovação em `401`/expiração via `securetoken`, falha de
rede = offline. `Historico` com **docId determinístico** (`sha1(ocorrencia_id)`) para
reescrita idempotente; `dia` "dd/MM/yyyy", `horario_previsto`, `horario_real`, `nome`.
Firestore REST é usado para a gravação de `Historico`.

## Motivo
Respeita as regras (sem bypass), usa o fluxo de token padrão do Firebase, TLS sempre e
credencial própria do dispositivo. Consequência aceita: é preciso ajustar
`firestore.rules` (ADR/ajuste autorizado nesta fase) e provisionar o usuário + o doc
`Dispensadores/{uid}` (manual hoje; automatizado na Fase 3b via Bluetooth).
Medicamentos e nomes nunca aparecem em logs (LGPD).