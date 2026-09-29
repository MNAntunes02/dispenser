/// Tema do LCD: alto contraste, fonte grande e sem elementos decorativos.
///
/// O público é idoso e a tela é vista à distância: tamanho grande, contraste
/// forte e nada que distraia da frase do passo. Cores seguem o app do
/// paciente (azul/verde/vermelho) reaproveitados sem alteração.
library;

import 'package:flutter/material.dart';

/// Paleta de alto contraste para leitura à distância.
class Cores {
  const Cores._();

  static const fundo = Color(0xFF07131F);
  static const painel = Color(0xFF10263A);
  static const texto = Color(0xFFF7FBFF);
  static const textoFraco = Color(0xFF9DB4C8);
  static const destaque = Color(0xFF35C4F0);
  static const ok = Color(0xFF2E9E63);
  static const alerta = Color(0xFFD64545);
  static const aviso = Color(0xFFE8A33D);
}

ThemeData temaKiosk() {
  final base = ThemeData.dark(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: Cores.fundo,
    colorScheme: base.colorScheme.copyWith(
      surface: Cores.fundo,
      primary: Cores.destaque,
      error: Cores.alerta,
    ),
    textTheme: base.textTheme.apply(bodyColor: Cores.texto, displayColor: Cores.texto),
  );
}
