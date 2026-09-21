# ADR 008 — Vínculo app↔dispensador via Bluetooth (onboarding) e provisionamento de rede

Status: implementada (Fase 3b, 2026-09-21) **com fakes/simulações e app**;
**validar no Pi** quando hardware chegar (servidores GATT `bluez_servico.py` e
`RedeLinux` só rodam lá; ver `docs/BLUETOOTH.md`).

## Contexto
A aba "Dispositivo" do app (hoje placeholder) deve conectar/vincular o app ao
dispensador. O Pi é headless (sem teclado) e a Fase 3 usa credencial própria + nuvem
para a agenda. O usuário quer que a conexão Bluetooth também **leve o dispensador à
rede** (Wi-Fi) no primeiro uso.

## Opções consideradas
- **BT como canal de dados** (agenda/comandos/sensores) — duplicaria o sync em nuvem,
  só funciona perto do celular e conflita com o outbox/offline-first.
- **Hotspot HTTP do Pi** para enviar Wi-Fi — mais simples de implementar, porém fora do
  Bluetooth pedido.
- **BT só para identificar + config manual do Wi-Fi** — dois passos e digitação manual.

## Escolha
O Bluetooth é canal de **onboarding/vínculo**, não de dados; os dados continuam na nuvem
(Fase 3). Na **Fase 3b**:
- O Pi entra em **modo provisionamento** no 1º boot sem configuração (e por botão físico,
  ex.: segurar 5 s), anunciando um serviço **BLE GATT** curto; o LCD mostra um **código de
  6 dígitos** de um só uso.
- O app escaneia, o usuário digita o código e envia por GATT: **Wi-Fi (SSID/senha) +
  config Firebase** (projectId, apiKey, `DISPENSER_USER_ID`).
- O Pi valida o código, aplica a rede (NetworkManager → netplan/wpa_supplicant), grava a
  config local (600) e então lê `Medicamentos` e registra `Historico` pela nuvem.
- Vínculo consolidado no Firestore: o app grava `Dispensadores/{uidDispenser} =
  {usuarioId: <paciente>}` — o mesmo documento usado pela regra `isDispenserDo` da Fase 3.
- A credencial Auth do dispensador (email/senha) continua criada no console (o app não
  pode criar usuários); a Fase 3b usa o arquivo 600 existente.

## Motivo
Menor superfície de código no Pi (sem duplicar o canal de dados), UX sem digitação manual
e segurança: o código no LCD evita que qualquer um "reivindique" o aparelho; senha de rede
e config nunca vão para logs ou para o repositório; nenhum segredo do Firebase trafega por
BT além do uso já autorizado na 3b. Consequência aceita: exige GATT server no Pi
(BlueZ/D-Bus) e a alteração da aba Dispositivo no app Flutter (autorização explícita na 3b).