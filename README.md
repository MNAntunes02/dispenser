# Dispensador de Medicamentos (Raspberry Pi + Ubuntu)

Sistema complementar ao app Flutter `app-saude/`: na hora da dose, alarme
sonoro + LEDs + tela LCD guiam o usuário a abrir a gaveta, ingerir o
medicamento e devolvê-lo ao slot; sensores confirmam cada etapa; se a dose
não for tomada, repete o alarme e notifica cuidador/app. Inicia sozinho no
boot e funciona offline.

> **Importante**: este projeto é um **auxiliar de adesão** e **não é um
> dispositivo médico certificado**. Não substitui orientação médica nem
> prescrição.

Documentação e estado do projeto: `docs/PROGRESSO.md`, `docs/BOOT.md`,
`docs/DESCOBERTA.md`, `docs/PROTOCOLO.md`, `docs/BLUETOOTH.md`,
`docs/HARDWARE.md` e `docs/decisoes/`.

## Arquitetura

- `dispenser-core` (Python 3): agendador + máquina de estados da dose + sync
  (polling + outbox) + notificador + relógio confiável. É o serviço
  **obrigatório**: dose, alarme e sensores vivem aqui.
- `dispenser-ui` (Flutter Linux/arm64): telas guiadas no LCD HDMI (kiosk).
  Serviço **opcional** — se cair, a dose segue por alarme e LED.
- `dispenser-provision`: pareamento com o app por Bluetooth (Fase 3b). Só
  roda até o aparelho ser pareado.
- Comunicação core ↔ UI: Unix socket com JSON (`/run/dispenser/core.sock`).
- Placa controladora (Arduino/ESP32): USB serial, protocolo JSON em
  `docs/PROTOCOLO.md`; todo acesso passa por `HardwareBridge` (real e
  simulada).

## Avisos ao cuidador (Fases 3, 6 e 7)

Dose não tomada, medicamento não devolvido, falha de sensor e **relógio
incorreto** viram documentos em
`UsuarioMedicamento/{paciente}/Notificacoes` (mensagem em pt-BR, com o
medicamento, o horário previsto e o motivo). O `Historico` do app continua
sendo só dose tomada. Os avisos entram numa fila local e saem quando houver
rede — sem rede, o fluxo da dose continua funcionando. Detalhes em
`docs/firestore-integracao.md` e `docs/decisoes/010-*.md`.

## Relógio e fuso (Fase 7)

O Raspberry Pi não tem RTC de fábrica. O core:

- aplica o fuso do paciente (`DISPENSER_TZ`, padrão `America/Sao_Paulo`) para
  a agenda não depender do fuso do SO;
- considera a hora **não confiável** se estiver abaixo de
  `DISPENSER_DATA_MINIMA` (padrão 2024-01-01) ou se saltar mais que
  `DISPENSER_TOLERANCIA_SALTO_S` (padrão 300 s);
- nesse caso **não dispara dose**, mostra aviso na tela e manda **um** aviso
  agregado ao cuidador quando a hora volta;
- ao recuperar, retoma o fluxo: doses mais de `DISPENSER_JANELA_ATRASO_S`
  (padrão 15 min) atrasadas são marcadas como não atendidas em vez de
  disparar alarme fora de hora.

Detalhes em `docs/BOOT.md` e `docs/decisoes/012-*.md`.

## Estrutura

```
core/       núcleo Python (daemon)
ui/         interface Flutter (LCD)
hardware/   ponte de hardware (real/simulada)
rede/       configuração de rede do pareamento
deploy/     systemd, udev, journald, instalador
config/     .env.example (sem segredos)
tests/      testes pytest
docs/       documentação e decisões
```

## Desenvolvimento

```bash
python3 -m venv .venv && .venv/bin/pip install -r core/requirements.txt -r tests/requirements-dev.txt
.venv/bin/python -m pytest          # núcleo
.venv/bin/python -m core.demo       # fluxo completo no simulador
```

A UI roda no dev (x86) com `flutter run` dentro de `ui/`; `flutter test` roda
a UI sobre um canal em memória. A compilação arm64 para o Pi é feita antes da
instalação:

```bash
cd ui && flutter build linux --target-platform linux-arm64
```

## Instalação no Pi (Fase 7/8)

O instalador **não faz nada por padrão**: sem `--executar`, ele só mostra o
plano. Ele altera o sistema (usuário, venv, units, udev, journald), então
confirme antes de rodar.

```bash
sudo ./deploy/install.sh                # mostra o plano
sudo ./deploy/install.sh --executar     # instala
```

O que ele faz: cria o usuário `dispenser` (sem root) nos grupos `dialout`,
`video`, `input`, `render` e `bluetooth`; monta o venv em `/opt/dispenser`;
cria os wrappers `dispenser-core`, `dispenser-ui` e `dispenser-provision` em
`/usr/local/bin`; instala as três units, o drop-in do journald e a regra udev
da placa; habilita `dispenser-core` (obrigatório) e os demais quando existem.

Depois da instalação:

```bash
sudoedit /etc/dispenser/dispenser.conf   # fuso, socket, caminho da placa
sudo /opt/dispenser/detectar-placa.sh    # nome estável da placa
systemctl status dispenser-core
journalctl -u dispenser-core -f
```

O app faz o pareamento por Bluetooth na primeira vez (`docs/BLUETOOTH.md`); o
core detecta a configuração nova **sem reiniciar** (recarga por SIGHUP ou
pelo mtime do arquivo de provisionamento).

Para remover: `sudo ./deploy/uninstall.sh --executar`. Os dados em
`/var/lib/dispenser` (histórico de adesão e fila de eventos) **só são
apagados** com `--apagar-dados`.

Detalhes de operação, diagnóstico e queda de energia: `docs/BOOT.md`.

## Configuração

`config/.env.example` é instalado em `/etc/dispenser/dispenser.conf`
(permissão 640, grupo `dispenser`) e é o único arquivo de configuração
versãoado. Segredos (credenciais do backend) ficam em arquivo próprio com
permissão 600, **fora** do repositório — nunca versione tokens ou
`google-services.json`.
