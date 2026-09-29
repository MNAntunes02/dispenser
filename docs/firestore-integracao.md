# Integração com Firestore (Fases 3 e 6)

Como o dispensador usa o backend do app: credencial própria, agenda, envio de
`dose_tomada` no `Historico` e avisos do cuidador em `Notificacoes`.
Implementação em `core/transporte.py` + `core/sync.py` + `core/notificador.py`.

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
- `Historico` é **adesão positiva**: só `dose_tomada` entra. `dose_perdida`,
  `retorno_pendente` e `falha` vão para `Notificacoes` (abaixo); `dose_concluida`
  e `gaveta_fora_de_horario` ainda não têm destino no app e ficam na fila.
- Sem nomes de medicamento em logs (LGPD).

## Avisos do cuidador (Fase 6 — ADR 010)

`PATCH .../UsuarioMedicamento/{PACIENTE}/Notificacoes/{docId}` com

- `docId = "n" + sha1("{ocorrencia_id}|{tipo}")[:20]` — determinístico, então
  reenvio após queda de energia sobrescreve o mesmo aviso.
- Campos (todos `stringValue`): `motivo` (`dose_perdida` | `nao_devolvido` |
  `falha`), `mensagem` (frase pt-BR já renderizada em `core/textos.py`),
  `dia` (dd/MM/yyyy), `horario_previsto`, `horario_real`, `nome`, `codigo`
  (só em falha) e `em` (ISO do evento).
- A subcoleção já está liberada ao dispensador vinculado pelas `firestore.rules`
  (`UsuarioMedicamento/{userId}/{document=**}`) — **nenhuma regra nova**.
- Falha de sensor sem dose em andamento também avisa: o doc leva `dia` e
  `codigo`, sem `nome`/`horario_previsto`.
- Um aviso por ocorrência: a chave `UNIQUE` da `outbox` (`{ocorrencia_id}|{tipo}`)
  absorve a duplicidade entre as ações `registrar` e `notificar` da máquina de
  estados; falha sem dose usa `sem_dose|falha|{codigo}|{dia}`.
- Offline nada se perde: o aviso fica na `outbox` (SQLite) e sai no próximo ciclo
  de sync. Sem rede, o fluxo da dose não é afetado.
- O `app-saude` **não** foi alterado: quando quiser consumir, basta ler
  `UsuarioMedicamento/{uid}/Notificacoes`. Sem FCM, o aviso só chega com o app
  aberto (limitação conhecida, `docs/DESCOBERTA.md`).

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