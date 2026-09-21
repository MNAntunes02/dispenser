# Integração com Firestore (Fase 3)

Como o dispensador usa o backend do app: credencial própria, agenda e envio de
`dose_tomada`. Corresponde à implementação em `core/transporte.py` + `core/sync.py`.

## Fluxo de autenticação (REST)

- **Entrar** (1ª vez): `POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}`
  corpo `{"email", "password", "returnSecureToken": true}` → `idToken`, `refreshToken`, `expiresIn`.
- **Renovar** (ao expirar / após `401`): `POST https://securetoken.googleapis.com/v1/token?key={API_KEY}`
  corpo `{"grant_type": "refresh_token", "refresh_token": ...}` → novo `access_token`.
- As chamadas ao Firestore levam `Authorization: Bearer {idToken}`. Falha de rede = **offline**;
  a fila outbox permanece pendente e é reenviada no próximo ciclo.

## Leitura da agenda

`GET https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents/UsuarioMedicamento/{PACIENTE}/Medicamentos`

Resposta decodificada em `list[{id, nome, dosagem, dias[{dia_semana, horario[]}]}]`
(`core/transporte.normalizar_medicamentos`) — mesmo formato do `Agendador`.
É gravada em `agenda_cache` (SQLite) e lida por `FonteAgendaLocal`.

## Registro de dose tomada

`PATCH .../UsuarioMedicamento/{PACIENTE}/Historico/{docId}` com corpo
`{"fields": {"dia": {"stringValue": "dd/MM/yyyy"}, "horario_previsto": ..., "horario_real": ..., "nome": ...}}`

- `docId = "h" + sha1(ocorrencia_id)[:20]` → reenvio/retry substitui o mesmo doc (idempotente).
- `dia`/`horarios` no mesmo formato do app (`medicamentos_do_dia.dart`).
- Só `dose_tomada` sai nesta fase; `dose_perdida`, `dose_concluida`, retorno etc. ficam na fila
  até a Fase 6. Sem nomes de medicamento em logs (LGPD).

## Vínculo app↔dispensador (Fase 3b — Bluetooth)

O BLE entrega Wi-Fi + Firebase ao Pi e o **app-paciente** grava o vínculo:

```javascript
match /Dispensadores/{dispenserUid} {
  allow read: if request.auth != null && request.resource.data.usuarioId == request.auth.uid;
  allow write: if request.auth != null && request.resource.data.usuarioId == request.auth.uid;
}
```

- Leitura de `Dispensadores` restrita ao próprio paciente (evita enumerar vínculos
  de terceiros); escrita continua só pelo paciente.
- O UID do dispensador (`dispenserUid`) vem da **credencial 600** do Pi
  (`{"email", "senha", "uid"}`), exposto via GATT (característica `id`) e usado
  pelo app para criar o doc. Ver `docs/BLUETOOTH.md`.
- O passo 1 (criar usuário Auth do dispensador e anotar o UID) continua manual.

## Provisionamento manual (hoje) — passos no console

1. **Firebase Auth** → *Add user*: criar e-mail/senha do dispensador (ex. `dispenser@usuario`)
   e copiar o **UID** resultante para `{"email", "senha", "uid"}` da credencial 600 do Pi.
2. **Firestore** → criar a coleção `Dispensadores` com doc `{UID do dispensador}` e
   campo `{usuarioId: "<UID do paciente>"}` (na Fase 3b em diante, o app faz este passo no pareamento).
3. Deploy das regras: `firebase deploy --only firestore:rules`.

## Variáveis de ambiente

- `FIREBASE_PROJECT_ID`, `DISPENSER_USER_ID` (paciente), `DISPENSER_FIREBASE_API_KEY`
  (chave pública do projeto, fora do repo) e `DISPENSER_CREDENTIALS_PATH` apontando para
  arquivo JSON `{"email", "senha", "uid"}` com permissão 600, fora do repositório.
- Na Fase 3b, quando provisionado via BLE, essas variáveis vêm de
  `/var/lib/dispenser/dispenser.env` (600) — `dispenser-core` as carrega no boot.
- Sem essas variáveis o `dispenser-core` roda sem backend (demo/`DISPENSER_AGENDA_JSON`).