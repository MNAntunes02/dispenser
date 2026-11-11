/// Testes da detecção de consumo (passo 4): regra de estabilidade, leitura do
/// NDJSON, configuração por ambiente e o detector real via subprocesso.
@TestOn('vm')
library;

import 'dart:io';

import 'package:dispenser_ui/src/visao.dart';
import 'package:flutter_test/flutter_test.dart';

Future<void> _esperar(
  bool Function() condicao, {
  Duration limite = const Duration(seconds: 5),
  String porque = 'a condição',
}) async {
  final fim = DateTime.now().add(limite);
  while (!condicao()) {
    if (DateTime.now().isAfter(fim)) fail('timeout esperando $porque');
    await Future<void>.delayed(const Duration(milliseconds: 20));
  }
}

/// Cria um executável temporário (shell) com o conteúdo dado.
File _executavel(String conteudo) {
  final dir = Directory.systemTemp.createTempSync('visao');
  final arquivo = File('${dir.path}/gerador.sh')..writeAsStringSync(conteudo);
  Process.runSync('chmod', ['+x', arquivo.path]);
  return arquivo;
}

void main() {
  group('EstabilidadeLeitura', () {
    test('confirma só ao repetir a mesma leitura por N frames', () {
      final regra = EstabilidadeLeitura(frames: 3, minPilulas: 1);
      const leitura = Leitura(2, 1);
      expect(regra.registrar(leitura), isFalse);
      expect(regra.registrar(leitura), isFalse);
      expect(regra.registrar(leitura), isTrue);
      // reinicia depois de confirmar: não confirma de novo com o mesmo quadro
      expect(regra.registrar(leitura), isFalse);
    });

    test('leitura diferente reinicia a contagem', () {
      final regra = EstabilidadeLeitura(frames: 3, minPilulas: 1);
      expect(regra.registrar(const Leitura(2, 1)), isFalse);
      expect(regra.registrar(const Leitura(2, 1)), isFalse);
      expect(regra.registrar(const Leitura(1, 2)), isFalse);
      expect(regra.registrar(const Leitura(1, 2)), isFalse);
      expect(regra.registrar(const Leitura(1, 2)), isTrue);
    });

    test('sem comprimido nunca confirma (câmera ligada sem ler cartela)', () {
      final regra = EstabilidadeLeitura(frames: 2, minPilulas: 1);
      for (var i = 0; i < 10; i++) {
        expect(regra.registrar(const Leitura(0, 3)), isFalse);
      }
    });

    test('respeita minPilulas', () {
      final regra = EstabilidadeLeitura(frames: 2, minPilulas: 2);
      expect(regra.registrar(const Leitura(1, 0)), isFalse);
      expect(regra.registrar(const Leitura(2, 0)), isFalse);
      expect(regra.registrar(const Leitura(2, 0)), isTrue);
    });
  });

  group('leituraDeLinha', () {
    test('lê o NDJSON do detector', () {
      expect(leituraDeLinha('{"pill": 3, "no_pill": 1}'), const Leitura(3, 1));
    });

    test('ignora linhas inválidas', () {
      expect(leituraDeLinha(''), isNull);
      expect(leituraDeLinha('não é json'), isNull);
      expect(leituraDeLinha('[1,2,3]'), isNull);
      expect(leituraDeLinha('{"pill": 1}'), isNull);
      expect(leituraDeLinha('{"pill": "x", "no_pill": 1}'), isNull);
    });
  });

  group('ConfiguracaoVisao', () {
    test('desligada por padrão (sem script)', () {
      final config = ConfiguracaoVisao.doAmbiente(const {});
      expect(config.ativo, isFalse);
      expect(config.frames, 30);
      expect(config.minPilulas, 1);
      expect(config.python, 'python3');
    });

    test('liga quando há script e lê os valores', () {
      final config = ConfiguracaoVisao.doAmbiente(const {
        'DISPENSER_VISAO_SCRIPT': '/opt/detector.py',
        'DISPENSER_VISAO_PYTHON': '/opt/venv/bin/python',
        'DISPENSER_VISAO_MODELO': 'best.pt',
        'DISPENSER_VISAO_CAMERA': '1',
        'DISPENSER_VISAO_CONF': '0.7',
        'DISPENSER_VISAO_FRAMES': '10',
        'DISPENSER_VISAO_MIN_PILL': '2',
      });
      expect(config.ativo, isTrue);
      expect(config.python, '/opt/venv/bin/python');
      expect(config.modelo, 'best.pt');
      expect(config.camera, 1);
      expect(config.conf, 0.7);
      expect(config.frames, 10);
      expect(config.minPilulas, 2);
    });

    test('DISPENSER_VISAO_ATIVA=0 desliga mesmo com script', () {
      final config = ConfiguracaoVisao.doAmbiente(const {
        'DISPENSER_VISAO_SCRIPT': '/opt/detector.py',
        'DISPENSER_VISAO_ATIVA': '0',
      });
      expect(config.ativo, isFalse);
    });
  });

  group('DetectorConsumoNulo', () {
    test('não confirma nada e não quebra ao iniciar/parar', () async {
      const detector = DetectorConsumoNulo();
      final confirmacoes = <void>[];
      final sub = detector.confirmacoes.listen(confirmacoes.add);
      detector.iniciar();
      detector.parar();
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(confirmacoes, isEmpty);
      await sub.cancel();
      await detector.dispose();
    });
  });

  group('DetectorConsumoProcesso', () {
    test('confirma quando o detector emite leitura estável', () async {
      final gerador = _executavel(
        '#!/bin/sh\n'
        'i=0\n'
        'while [ \$i -lt 3 ]; do\n'
        '  echo \'{"pill": 2, "no_pill": 1}\'\n'
        '  i=\$((i+1))\n'
        'done\n',
      );
      final config = ConfiguracaoVisao(
        ativo: true,
        python: gerador.path,
        script: 'ignorado',
        modelo: 'm',
        camera: 0,
        conf: 0.5,
        frames: 3,
        minPilulas: 1,
      );
      final detector = DetectorConsumoProcesso(config);
      final confirmacoes = <void>[];
      final sub = detector.confirmacoes.listen(confirmacoes.add);
      detector.iniciar();
      await _esperar(() => confirmacoes.isNotEmpty, porque: 'a confirmação da visão');
      expect(confirmacoes, hasLength(1));
      await sub.cancel();
      await detector.dispose();
      gerador.parent.deleteSync(recursive: true);
    });

    test('não confirma quando as leituras variam', () async {
      final gerador = _executavel(
        '#!/bin/sh\n'
        'echo \'{"pill": 1, "no_pill": 0}\'\n'
        'echo \'{"pill": 2, "no_pill": 0}\'\n'
        'echo \'{"pill": 3, "no_pill": 0}\'\n'
        'echo \'{"pill": 4, "no_pill": 0}\'\n',
      );
      final config = ConfiguracaoVisao(
        ativo: true,
        python: gerador.path,
        script: 'ignorado',
        modelo: 'm',
        camera: 0,
        conf: 0.5,
        frames: 3,
        minPilulas: 1,
      );
      final detector = DetectorConsumoProcesso(config);
      final confirmacoes = <void>[];
      final sub = detector.confirmacoes.listen(confirmacoes.add);
      detector.iniciar();
      await Future<void>.delayed(const Duration(milliseconds: 500));
      expect(confirmacoes, isEmpty);
      await sub.cancel();
      await detector.dispose();
      gerador.parent.deleteSync(recursive: true);
    });

    test('falha ao abrir o processo não quebra (OK manual segue)', () async {
      final config = ConfiguracaoVisao(
        ativo: true,
        python: '/caminho/que/nao/existe/python',
        script: 'x',
        modelo: 'm',
        camera: 0,
        conf: 0.5,
        frames: 3,
        minPilulas: 1,
      );
      final detector = DetectorConsumoProcesso(config);
      final confirmacoes = <void>[];
      final sub = detector.confirmacoes.listen(confirmacoes.add);
      detector.iniciar();
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect(confirmacoes, isEmpty);
      await sub.cancel();
      await detector.dispose();
    });
  });
}
