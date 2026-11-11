/// Testes da detecção de consumo (passo 4): regra de estabilidade, leitura do
/// NDJSON, configuração por ambiente e o detector real via subprocesso.
@TestOn('vm')
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

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

    test('lê o frame do preview em base64', () {
      final jpeg = Uint8List.fromList(<int>[0xFF, 0xD8, 0xFF, 0xD9]);
      final linha = jsonEncode({'pill': 2, 'no_pill': 1, 'frame': base64Encode(jpeg)});

      final leitura = leituraDeLinha(linha)!;

      expect(leitura.pill, 2);
      expect(leitura.noPill, 1);
      expect(leitura.quadro, jpeg);
    });

    test('frame inválido não invalida a contagem', () {
      final leitura = leituraDeLinha('{"pill": 1, "no_pill": 0, "frame": "não é base64"}')!;

      expect(leitura.pill, 1);
      expect(leitura.noPill, 0);
      expect(leitura.quadro, isNull);
    });

    test('o frame não entra na igualdade da leitura', () {
      final jpeg = Uint8List.fromList(<int>[1, 2, 3]);

      expect(const Leitura(2, 1, quadro: null), Leitura(2, 1, quadro: jpeg));
      expect(const Leitura(2, 1).hashCode, Leitura(2, 1, quadro: jpeg).hashCode);
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
      expect(config.preview, isTrue);
      expect(config.previewFps, 5);
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
        'DISPENSER_VISAO_PREVIEW': '0',
        'DISPENSER_VISAO_PREVIEW_FPS': '2',
      });
      expect(config.ativo, isTrue);
      expect(config.python, '/opt/venv/bin/python');
      expect(config.modelo, 'best.pt');
      expect(config.camera, 1);
      expect(config.conf, 0.7);
      expect(config.frames, 10);
      expect(config.minPilulas, 2);
      expect(config.preview, isFalse);
      expect(config.previewFps, 2);
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

  group('DetectorConsumoFake', () {
    test('emite os quadros do preview', () async {
      final detector = DetectorConsumoFake();
      final quadros = <Uint8List>[];
      final sub = detector.quadros.listen(quadros.add);
      final jpeg = Uint8List.fromList(<int>[0xFF, 0xD8, 0xFF, 0xD9]);

      detector.emitirQuadro(jpeg);
      await Future<void>.delayed(const Duration(milliseconds: 20));

      expect(quadros, [jpeg]);
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

    test('emite o frame do preview junto da leitura', () async {
      final jpeg = base64Encode(<int>[0xFF, 0xD8, 0xFF, 0xD9]);
      final gerador = _executavel(
        '#!/bin/sh\n'
        'echo \'{"pill": 1, "no_pill": 0, "frame": "$jpeg"}\'\n'
        'sleep 0.2\n',
      );
      final config = ConfiguracaoVisao(
        ativo: true,
        python: gerador.path,
        script: 'ignorado',
        modelo: 'm',
        camera: 0,
        conf: 0.5,
        frames: 30,
        minPilulas: 1,
      );
      final detector = DetectorConsumoProcesso(config);
      final quadros = <Uint8List>[];
      final sub = detector.quadros.listen(quadros.add);
      detector.iniciar();
      await _esperar(() => quadros.isNotEmpty, porque: 'o frame do preview');
      expect(quadros.first, <int>[0xFF, 0xD8, 0xFF, 0xD9]);
      await sub.cancel();
      await detector.dispose();
      gerador.parent.deleteSync(recursive: true);
    });

    test('passa os argumentos do contrato (câmera e preview) ao script', () async {
      final dir = Directory.systemTemp.createTempSync('visao');
      final args = File('${dir.path}/args.txt');
      final gerador = File('${dir.path}/gerador.sh')
        ..writeAsStringSync(
          '#!/bin/sh\n'
          'printf "%s\\n" "\$@" > "${args.path}"\n'
          'echo \'{"pill": 1, "no_pill": 0}\'\n'
          'sleep 0.2\n',
        );
      Process.runSync('chmod', ['+x', gerador.path]);

      final config = ConfiguracaoVisao(
        ativo: true,
        python: gerador.path,
        script: 'ignorado',
        modelo: 'best_ncnn_model',
        camera: 1,
        conf: 0.5,
        frames: 30,
        minPilulas: 1,
        previewFps: 2,
      );
      final detector = DetectorConsumoProcesso(config);
      detector.iniciar();
      await _esperar(
        () => args.existsSync() && args.readAsLinesSync().length >= 10,
        porque: 'os argumentos do script',
      );
      final linhas = args.readAsStringSync().trim().split('\n');
      expect(linhas, containsAllInOrder(<String>[
        '--modelo',
        'best_ncnn_model',
        '--camera',
        '1',
        '--conf',
        '0.5',
        '--ndjson',
        '--preview',
        '--preview-fps',
        '2.0',
      ]));
      await detector.dispose();
      dir.deleteSync(recursive: true);
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
