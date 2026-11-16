# dispenser_ui

Interface LCD do dispensador (kiosk)

## Getting Started

This project is a starting point for a Flutter application.

A few resources to get you started if this is your first Flutter project:

- [Learn Flutter](https://docs.flutter.dev/get-started/learn-flutter)
- [Write your first Flutter app](https://docs.flutter.dev/get-started/codelab)
- [Flutter learning resources](https://docs.flutter.dev/reference/learning-resources)

For help getting started with Flutter development, view the
[online documentation](https://docs.flutter.dev/), which offers tutorials,
samples, guidance on mobile development, and a full API reference.

## Rodar no Raspberry Pi (flutter-pi)

Use o launcher para que a UI receba as variáveis `DISPENSER_VISAO_*` do `.env`
(detecção de consumo do passo 4) e o `DISPENSER_SOCKET`:

```sh
./ui/run_pi.sh
```

Ele carrega do `.env` somente essas chaves, sem repassar credenciais do backend
para a UI. Para usar outro bundle: `DISPENSER_UI_BUNDLE=/caminho/do/bundle ./ui/run_pi.sh`.

## Rodar o bundle Linux/arm64 (debug)

```sh
LIBGL_ALWAYS_SOFTWARE=1 FLUTTER_ENGINE_SWITCHES=1 FLUTTER_ENGINE_SWITCH_1="enable-impeller=false" ./build/linux/arm64/debug/bundle/dispenser_ui
```

SCRIPT:
DISPENSER_SOCKET=/home/pi/Desktop/dispenser/.run/core.sock flutter-pi --release ~/Desktop/dispenser/ui/pi3-64
