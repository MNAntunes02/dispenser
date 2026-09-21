# Vínculo e provisionamento via Bluetooth (Fase 3b)

O Bluetooth tem **um único papel**: *onboarding* (vínculo + provisionamento).
Os dados de saúde/agenda continuam na nuvem (Firestore); o BLE só entrega ao Pi
o Wi-Fi e a configuração do Firebase **de uma vez, no primeiro uso** (ou quando
reconfigurado). Depois do sucesso, o dispensador para de anunciar o serviço.

## Fluxo

1. **Pi (sem `/var/lib/dispenser/dispenser.env`)** inicia `dispenser-provision`:
   gera um **código de 6 dígitos** (one-time, expira em 10 min) exibido no LCD.
2. **App** (aba Dispositivo) escaneia por `OptiBlister-*`, conecta e lê a
   característica `id` (UID + nome do dispensador).
3. Usuário digita o **código**; o app monta a carga (código + Wi-Fi + Firebase)
   e a escreve na característica `config` (com **chunking**).
4. Pi valida código+carga → aplica a rede (nmcli → netplan) → persiste
   `/var/lib/dispenser/dispenser.env` (600) → notifica `status=ok` e **para o
   anúncio**. Senha de rede nunca é persistida pelo dispensador nem logada.
5. App grava o vínculo em Firestore: `Dispensadores/{uidDoDispenser} =
   {usuarioId: uidDoPaciente}` (regra exige auth do paciente).
6. Ao reiniciar `dispenser-core` (systemd), o env carregado habilita o sync
   Firestore normal.

## Serviço GATT

- Service UUID: `9a40d000-1dd1-11b2-80c0-00805f9b34fb`
- Nome de anúncio: `OptiBlister-<hostname>` (apenas quando não provisionado —
  ou após `dispenser-provision`/botão).

| Característica | UUID | Flags | Conteúdo |
|---|---|---|---|
| `id` | `9a40d001-…` | read | `{"uid": "<uid firebase do dispensador>", "nome": "<hostname>"}` |
| `config` | `9a40d002-…` | write | pedaços de configuração (ver abaixo) |
| `status` | `9a40d003-…` | read, notify | `{"estado": "aguardando_codigo"\|"aplicando_rede"\|"ok"\|"erro", "erro"?: "..."}` |

### Característica `config` (chunking)

Cada escrita é um pedaço ≤ **240 bytes**:

```json
{"seq": 0, "total": 3, "dados": "<fragmento do JSON da configuração>"}
```

Máximo de 8 pedaços. Quando o último tiver chegado, o Pi remonta e valida:

```json
{
  "codigo": "123456",
  "wifi": {"ssid": "Casa", "senha": "segredo"},
  "firebase": {"projectId": "app-saude-8fba1", "apiKey": "<apiKey>", "usuarioId": "<uidPaciente>"}
}
```

- `usuarioId` = UID do paciente que manda configurar (vira o dono do env).
- Pedaços fora de ordem são aceitos; totais divergentes, seq fora do intervalo
  ou payload maior que o limite são rejeitados (`status=erro`).

## Segurança

- Código de 6 dígitos com **validade de 10 min**, sutilmente comparado; expiração
  verificada; carga inválida nunca toca a rede.
- Após provisionar, o serviço deixa de anunciar — reconfigure exigir
  `dispenser-provision`/botão físico no Pi.
- `dispenser.env` perm **600**, no diretório do serviço; sem nomes de
  medicamento em logs (LGPD).
- `status` só é notificado a quem se subscrever (CCC 2902); o GATT não guarda
  dados de saúde (nada além de config/identidade).

## Implementação

- Pi: `core/provisionamento.py` (FSM pura + `MontadorChunks`), `rede/rede.py`
  (`RedeLinux`: nmcli → netplan; `RedeSimulada`), `hardware/gatt/`
  (`ServicoGattSimulado` + `ServicoGattBlueZ` D-Bus), `core/provision_main.py`
  (CLI `--simulado` para dev sem hardware).
- App: `lib/services/dispositivo_ble.dart` (`ParqueamentoBle` + fake),
  `lib/main/dispositivo.dart` (estados não vinculado → escaneando → pareando →
  vinculado).
- Testes: `tests/test_provisionamento.py`, `tests/test_gatt_simulado.py`,
  `tests/test_rede.py`, `tests/test_provision_entrypoint.py` — **todo o fluxo é
  hermetricamente testado com fakes**; a parte BlueZ/NetworkManager só roda no
  Pi (Fase 3b-run / Fase 4).