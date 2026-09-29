/// `dispenser-ui`: a tela do LCD do dispensador.
///
/// App kiosk: tela cheia, sem navegação. Fala com o `dispenser-core` pelo Unix
/// socket (ADR 003) e mostra o que o core decidir — a UI não decide o estado
/// da dose, só exibe o passo e devolve o botão OK.
library;

import 'dart:io';

import 'package:flutter/material.dart';

import 'src/canal.dart';
import 'src/cliente_core.dart';
import 'src/controlador.dart';
import 'src/telas.dart';
import 'src/tema.dart';

/// Caminho do socket, definido na compilação (`--dart-define`).
///
/// Existe para o dev (`flutter test`) apontar para um core em outra máquina.
const String kSocketCompilado =
    String.fromEnvironment('DISPENSER_SOCKET', defaultValue: kSocketPadrao);

/// Caminho efetivo do socket: o ambiente na hora da execução vence.
///
/// A unit systemd passa `DISPENSER_SOCKET`; sem esta leitura o instalador
/// precisaria recompilar a UI sempre que mudasse o caminho — e um caminho
/// errado faria a tela ficar eternamente em "conectando", sem erro visível.
String caminhoSocketDoCore() {
  final doAmbiente = Platform.environment['DISPENSER_SOCKET'];
  if (doAmbiente != null && doAmbiente.trim().isNotEmpty) {
    return doAmbiente.trim();
  }
  return kSocketCompilado;
}

void main() {
  final caminho = caminhoSocketDoCore();
  final canal = CanalSocketUnix(caminho);
  final cliente = ClienteCore(canal, caminho: caminho);
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
