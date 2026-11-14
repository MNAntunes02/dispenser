import 'dart:io';

import 'package:dispenser_ui/src/ambiente.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('lê o .env subindo a partir do diretório do bundle', () {
    final raiz = Directory.systemTemp.createTempSync('ambiente');
    final fundo = Directory('${raiz.path}/a/b/c')..createSync(recursive: true);
    File('${raiz.path}/.env').writeAsStringSync(
      'DISPENSER_SOCKET=/run/core.sock\n'
      'DISPENSER_VISAO_SCRIPT="/opt/visao/detector.py"\n'
      "DISPENSER_VISAO_CAMERA='1'\n"
      'export DISPENSER_VISAO_PREVIEW=0\n'
      'DISPENSER_VISAO_CONF=0.7 # comentário\n'
      'SEGREDO=nao-copiar\n',
    );

    final ambiente = carregarAmbiente(inicio: fundo);

    expect(ambiente['DISPENSER_SOCKET'], '/run/core.sock');
    expect(ambiente['DISPENSER_VISAO_SCRIPT'], '/opt/visao/detector.py');
    expect(ambiente['DISPENSER_VISAO_CAMERA'], '1');
    expect(ambiente['DISPENSER_VISAO_PREVIEW'], '0');
    expect(ambiente['DISPENSER_VISAO_CONF'], '0.7');
    expect(ambiente.containsKey('SEGREDO'), isFalse);
    raiz.deleteSync(recursive: true);
  });

  test('o ambiente do processo vence o arquivo', () {
    final raiz = Directory.systemTemp.createTempSync('ambiente');
    final arquivo = File('${raiz.path}/.env')
      ..writeAsStringSync(
        'DISPENSER_SOCKET=/run/do-arquivo.sock\n'
        'DISPENSER_VISAO_CAMERA=0\n',
      );

    final ambiente = carregarAmbiente(
      base: const {
        'DISPENSER_SOCKET': '/run/do-processo.sock',
        'DISPENSER_VISAO_CAMERA': '2',
      },
      arquivo: arquivo.path,
    );

    expect(ambiente['DISPENSER_SOCKET'], '/run/do-processo.sock');
    expect(ambiente['DISPENSER_VISAO_CAMERA'], '2');
    raiz.deleteSync(recursive: true);
  });

  test('arquivo ausente não quebra e não inventa valores', () {
    final raiz = Directory.systemTemp.createTempSync('ambiente');
    expect(carregarAmbiente(arquivo: '${raiz.path}/nao-existe.env'), isEmpty);
    raiz.deleteSync(recursive: true);
  });
}
