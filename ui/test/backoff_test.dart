/// Testes do backoff de reconexão e da leitura do socket no ambiente.
///
/// O ponto é o aparelho ficar dias ligado: se o core reinicia dez vezes, a UI
/// não pode martelar o socket nem esperar 15 s para voltar a mostrar a dose.
library;

import 'dart:math';

import 'package:dispenser_ui/main.dart';
import 'package:dispenser_ui/src/canal.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('Backoff', () {
    test('cresce, satura no máximo e reinicia depois de uma linha do core', () {
      final b = Backoff(jitter: 0, aleatorio: Random(1));
      final esperas = List.generate(8, (_) => b.proxima());
      expect(esperas[0], const Duration(seconds: 1));
      expect(esperas[1], const Duration(seconds: 2));
      expect(esperas[2], const Duration(seconds: 4));
      // Satura: nunca passa do teto mesmo com muitas falhas seguidas.
      expect(esperas.every((e) => e <= const Duration(seconds: 15)), isTrue);
      expect(b.tentativas, 8);

      b.reiniciar();
      expect(b.proxima(), const Duration(seconds: 1));
    });

    test('jitter não deixa a espera escapar das faixas', () {
      final b = Backoff(jitter: 0.2, aleatorio: Random(7));
      for (var i = 0; i < 30; i++) {
        final e = b.proxima();
        expect(e.inMilliseconds, greaterThanOrEqualTo(200));
        expect(e.inMilliseconds, lessThanOrEqualTo(60000));
      }
    });
  });

  group('caminho do socket', () {
    test('o ambiente vence o valor de compilação', () {
      // Sem variável no ambiente, usa o padrão/compilado.
      expect(caminhoSocketDoCore(), kSocketCompilado);
    });
  });
}
