/// Tema do LCD: alto contraste, fonte grande e sem elementos decorativos.
///
/// O público é idoso e a tela é vista à distância: tamanho grande, contraste
/// forte e nada que distraia da frase do passo. As cores vêm da paleta tonal
/// do design system (Primary, Feedback-Info/Alert/Error, Neutral e
/// Second-neutral); a UI só usa os tokens semânticos de [Cores].
library;

import 'package:flutter/material.dart';

/// Paletas tonais de referência (tom 0 a 99, como no design system).
///
/// Não use direto nas telas: use os tokens semânticos de [Cores], para que
/// trocar um tom aconteça em um lugar só.
class Paleta {
  const Paleta._();

  static const primary90 = Color(0xFF052A16);
  static const primary80 = Color(0xFF0B552D);
  static const primary70 = Color(0xFF107F43);
  static const primary60 = Color(0xFF16A95A);
  static const primary50 = Color(0xFF1BD370);
  static const primary40 = Color(0xFF49DC8D);
  static const primary30 = Color(0xFF76E5A9);
  static const primary20 = Color(0xFFA4EEC6);
  static const primary10 = Color(0xFFD1F6E2);

  static const info80 = Color(0xFF0A1B2F);
  static const info60 = Color(0xFF14365D);
  static const info50 = Color(0xFF1E518C);
  static const info30 = Color(0xFF3286E9);
  static const info20 = Color(0xFF5B9EED);
  static const info10 = Color(0xFFADCFF6);

  static const alert90 = Color(0xFF2E2103);
  static const alert60 = Color(0xFF5B4306);
  static const alert50 = Color(0xFFE4A710);
  static const alert20 = Color(0xFFE9B940);
  static const alert10 = Color(0xFFFAEDCF);

  static const error90 = Color(0xFF410E0B);
  static const error70 = Color(0xFF601410);
  static const error60 = Color(0xFFDC362E);
  static const error50 = Color(0xFFE46962);
  static const error20 = Color(0xFFEC928E);
  static const error10 = Color(0xFFF9DEDC);

  static const neutral50 = Color(0xFF212422);
  static const neutral30 = Color(0xFF464C49);
  static const neutral20 = Color(0xFF767D7A);

  static const second99 = Color(0xFF08080C);
  static const second80 = Color(0xFF11111A);
  static const second70 = Color(0xFF36364A);
  static const second60 = Color(0xFF515162);
  static const second50 = Color(0xFF69697C);
  static const second40 = Color(0xFF9191A1);
  static const second30 = Color(0xFFB4B4C0);
  static const second20 = Color(0xFFD0D0D7);
  static const second10 = Color(0xFFFDFDFF);
}

/// Tokens semânticos usados pelas telas.
class Cores {
  const Cores._();

  // Superfícies (do mais fundo para o mais elevado).
  static const fundo = Paleta.second20;
  static const painel = Paleta.second10;
  static const painelElevado = Paleta.second30;
  static const borda = Paleta.second30;

  // Texto.
  static const texto = Paleta.second99;
  static const textoFraco = Paleta.second70;
  static const textoSuave = Paleta.second60;

  // Marca / ação principal.
  static const destaque = Paleta.primary70;
  static const destaqueSuave = Paleta.primary80;
  static const destaqueEscuro = Paleta.primary10;
  static const destaqueContainer = Paleta.primary20;

  // Feedback.
  static const ok = Paleta.primary50;
  static const alerta = Paleta.error60;
  static const alertaForte = Paleta.error50;
  static const alertaContainer = Paleta.error10;
  static const alertaTexto = Paleta.error90;
  static const aviso = Paleta.alert50;
  static const avisoContainer = Paleta.alert10;
  static const info = Paleta.info60;
  static const infoContainer = Paleta.info10;
}

/// Raios de borda comuns.
class Medidas {
  const Medidas._();

  static const raioCartao = 28.0;
  static const raioMedio = 20.0;
  static const raioPilula = 999.0;

  /// Tamanho de projeto de cada cartão de dose no repouso. O [FittedBox] que
  /// envolve a lista escala esses valores para caber no LCD; sem limites finitos
  /// aqui o `width: double.infinity` e o `crossAxisAlignment.stretch` do cartão
  /// recebem restrições ilimitadas e o layout falha (o cartão some da tela).
  static const larguraProjetoCartaoProxima = 1200.0;
  static const alturaProjetoCartaoProxima = 220.0;

  /// Largura em que a instrução das telas de câmera quebra linha antes de
  /// qualquer redução pelo [FittedBox]. Sem esse limite, o texto é medido com
  /// largura ilimitada e encolhe inteiro na coluna estreita, em vez de quebrar.
  static const larguraProjetoInstrucaoCamera = 720.0;
}

/// Escala de espaçamento (múltiplos de 4). Use sempre estes valores.
class Espaco {
  const Espaco._();

  static const xxs = 4.0;
  static const xs = 8.0;
  static const s = 12.0;
  static const m = 16.0;
  static const l = 24.0;
  static const xl = 32.0;
  static const xxl = 40.0;
  static const xxxl = 48.0;
}

/// Escala tipográfica: Inter, com os papéis do design system (Display e
/// H1 a H6).
///
/// Os tamanhos de referência (54, 32, 24, 20, 16, 14) são de tela de celular.
/// O LCD é lido à distância, então cada tamanho é multiplicado por [escala].
/// Peso e espaçamento entre letras seguem a referência (proporcionalmente).
/// A altura de linha da referência (24 para fonte 32, 16 para fonte 16) corta
/// texto de duas linhas; aqui ela é aumentada nesses casos.
class Tipografia {
  const Tipografia._();

  static const familia = 'Inter';

  /// Fator do celular para o LCD.
  static const escala = 2.0;

  static TextStyle _estilo({required double tamanho, required double altura, required double tracking, FontWeight peso = FontWeight.w400}) {
    return TextStyle(fontFamily: familia, fontSize: tamanho * escala, height: altura, letterSpacing: tracking * escala, fontWeight: peso);
  }

  /// Display: 32 / bold.
  static final display = _estilo(tamanho: 32, altura: 1.15, tracking: -0.8, peso: FontWeight.w700);

  /// H1: 54 (horário da próxima dose).
  static final h1 = _estilo(tamanho: 54, altura: 64 / 54, tracking: -0.4);

  /// H2: 32.
  static final h2 = _estilo(tamanho: 32, altura: 1.15, tracking: -0.8);

  /// H3: 24.
  static final h3 = _estilo(tamanho: 24, altura: 32 / 24, tracking: -0.8);

  /// H4: 20.
  static final h4 = _estilo(tamanho: 20, altura: 28 / 20, tracking: -0.8);

  /// H5: 16.
  static final h5 = _estilo(tamanho: 16, altura: 1.25, tracking: -0.8);

  /// H6: 14 / medium.
  static final h6 = _estilo(tamanho: 14, altura: 1.25, tracking: -0.4, peso: FontWeight.w500);

  /// Legenda: o menor texto permitido no LCD (não existe na referência).
  static final legenda = _estilo(tamanho: 12, altura: 1.3, tracking: -0.2);

  static const negrito = FontWeight.w700;
  static const tabular = [FontFeature.tabularFigures()];
}

ThemeData temaKiosk() {
  final base = ThemeData(brightness: Brightness.dark, useMaterial3: true, fontFamily: Tipografia.familia);
  final esquema = const ColorScheme.dark().copyWith(
    surface: Cores.fundo,
    onSurface: Cores.texto,
    onSurfaceVariant: Cores.textoFraco,
    surfaceContainerHighest: Cores.painelElevado,
    primary: Cores.destaque,
    onPrimary: Cores.destaqueEscuro,
    primaryContainer: Cores.destaqueContainer,
    onPrimaryContainer: Paleta.primary90,
    secondary: Cores.info,
    tertiary: Cores.aviso,
    error: Cores.alerta,
    onError: Paleta.error10,
    errorContainer: Cores.alertaContainer,
    onErrorContainer: Cores.alertaTexto,
    outline: Cores.borda,
  );
  return base.copyWith(
    scaffoldBackgroundColor: Cores.fundo,
    colorScheme: esquema,
    textTheme: base.textTheme
        .copyWith(
          displayLarge: Tipografia.h1,
          displayMedium: Tipografia.display,
          headlineLarge: Tipografia.h2,
          headlineMedium: Tipografia.h3,
          headlineSmall: Tipografia.h4,
          bodyLarge: Tipografia.h5,
          bodyMedium: Tipografia.h6,
          bodySmall: Tipografia.legenda,
        )
        .apply(fontFamily: Tipografia.familia, bodyColor: Cores.texto, displayColor: Cores.texto),
    progressIndicatorTheme: const ProgressIndicatorThemeData(color: Cores.destaque, circularTrackColor: Cores.painelElevado),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(backgroundColor: Cores.destaque, foregroundColor: Cores.destaqueEscuro),
    ),
  );
}
