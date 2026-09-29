/// Teste de integração: core Python real + UI Flutter real pelo Unix socket.
///
/// Este é o teste que fecha a Fase 5. Ele sobe `python3 -m core.demo
/// --sem-mini-ui` (o mesmo coordenador, a mesma máquina de estados e o mesmo
/// `ServidorUI` do Pi), conecta o `CanalSocketUnix` de produção via FFI e
/// confirma os passos com o `input:confirma` que a UI envia quando o core
/// pede um OK. Nenhum hardware, nenhuma tela real — mas o protocolo, o
/// transporte e a máquina de estados são os de produção.
@TestOn('vm')
library;

import 'dart:convert';
import 'dart:io';

import 'package:dispenser_ui/src/canal.dart';
import 'package:dispenser_ui/src/cliente_core.dart';
import 'package:dispenser_ui/src/controlador.dart';
import 'package:dispenser_ui/src/modelo.dart';
import 'package:flutter_test/flutter_test.dart';

/// Caminho do core a partir de `ui/`.
final Directory _raiz = Directory('..').absolute;

void main() {
  test('UI real conduz a dose inteira pelo socket do core', () async {
    final dir = Directory.systemTemp.createTempSync('dispenser_e2e');
    final socket = '${dir.path}/core.sock';

    final core = await Process.start(
      Platform.resolvedExecutable.contains('python')
          ? Platform.resolvedExecutable
          : 'python3',
      [
        '-m',
        'core.demo',
        '--socket',
        socket,
        '--sem-mini-ui',
      ],
      workingDirectory: _raiz.path,
      environment: {
        ...Platform.environment,
        'PYTHONPATH': _raiz.path,
      },
    );

    core.stdout.transform(utf8.decoder).listen((l) => stdout.writeln('CORE> $l'));
    core.stderr.transform(utf8.decoder).listen((l) => stderr.writeln('CORE! $l'));

    final cliente = ClienteCore(CanalSocketUnix(socket));
    final controlador = ControladorUI(cliente);
    cliente.iniciar();
    final telas = <Tela>[];
    cliente.eventos.listen((evento) {
      if (evento case MensagemRecebida(:final mensagem)) {
        if (mensagem is Tela) {
          telas.add(mensagem);
          // é assim que a UI confirma: só quando o core pede o OK
          if (mensagem.esperaBotao) {
            controlador.confirmar();
          }
        }
      }
    });

    try {
      await _esperar(
        () => telas.any((t) => t.chave == 'tudo_certo'),
        porque: 'o core concluir o fluxo',
        limite: const Duration(seconds: 40),
      );

      // os seis passos do roteiro, na ordem
      expect(
        telas.where((t) => t.fluxo == 'dose').map((t) => t.chave).toList(),
        [
          'hora_remedio',
          'abra_gaveta',
          'retire_medicamento',
          'tome_e_ok',
          'devolva_slot',
          'tudo_certo',
        ],
      );
      // numeração e total vêm do core; a UI só mostra
      expect(telas.map((t) => t.passo).whereType<int>().toList(), [1, 2, 3, 4, 5, 6]);
      expect(telas.every((t) => t.totalPassos == 6), isTrue);
      // os OKs só acontecem onde o core mandou esperar o botão
      expect(
        telas.where((t) => t.esperaBotao).map((t) => t.chave).toList(),
        ['hora_remedio', 'tome_e_ok'],
      );
      // fluxo concluído: o core volta a publicar a tela de repouso
      expect(controlador.estado, isA<EstadoRepouso>());
    } finally {
      await cliente.dispose();
      controlador.dispose();
      core.kill(ProcessSignal.sigterm);
      dir.deleteSync(recursive: true);
    }
  }, timeout: const Timeout(Duration(minutes: 2)));
}

Future<void> _esperar(
  bool Function() condicao, {
  required String porque,
  Duration limite = const Duration(seconds: 10),
}) async {
  final fim = DateTime.now().add(limite);
  while (!condicao()) {
    if (DateTime.now().isAfter(fim)) fail('timeout esperando $porque');
    await Future<void>.delayed(const Duration(milliseconds: 50));
  }
}
