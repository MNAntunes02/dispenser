/// `dispenser-ui`: a tela do LCD do dispensador.
///
/// App kiosk: tela cheia, sem navegação. Fala com o `dispenser-core` pelo Unix
/// socket (ADR 003) e mostra o que o core decidir — a UI não decide o estado
/// da dose, só exibe o passo e devolve o botão OK.
library;

import 'package:flutter/material.dart';

import 'src/canal.dart';
import 'src/cliente_core.dart';
import 'src/controlador.dart';
import 'src/telas.dart';
import 'src/tema.dart';

/// Caminho do socket: o systemd passa por variável de ambiente; o padrão é o
/// do Pi (`deploy/dispenser-core.service`).
const String kSocketDoCore =
    String.fromEnvironment('DISPENSER_SOCKET', defaultValue: kSocketPadrao);

void main() {
  final canal = CanalSocketUnix(kSocketDoCore);
  final cliente = ClienteCore(canal, caminho: kSocketDoCore);
  final controlador = ControladorUI(cliente);
  cliente.iniciar();
  controlador.iniciar();
  runApp(DispenserApp(controlador: controlador));
}

class DispenserApp extends StatelessWidget {
  const DispenserApp({super.key, required this.controlador});

  final ControladorUI controlador;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Dispensador de Medicamentos',
      theme: temaKiosk(),
      home: TelaDispensador(controlador: controlador),
    );
  }
}

/// Atalho para os testes: monta a UI sobre um [ClienteCore] já pronto.
class DispenserAppFake extends StatelessWidget {
  const DispenserAppFake({super.key, required this.cliente});

  final ClienteCore cliente;

  @override
  Widget build(BuildContext context) {
    return DispenserApp(controlador: ControladorUI(cliente));
  }
}
