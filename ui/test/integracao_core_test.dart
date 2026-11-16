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
    var liberou = false;
    cliente.eventos.listen((evento) {
      if (evento case MensagemRecebida(:final mensagem)) {
        if (mensagem is Tela) {
          telas.add(mensagem);
          // O operador libera o passo de detecção pelo painel/CLI.
          if (!liberou && mensagem.chave == 'consuma_e_detectar') {
            liberou = true;
            cliente.canal.enviar(
              jsonEncode({
                'v': 1,
                'type': 'comando',
                'cmd': 'liberar_proximo',
              }),
            );
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

      // os quatro passos do roteiro, na ordem
      expect(
        telas.where((t) => t.fluxo == 'dose').map((t) => t.chave).toList(),
        [
          'abra_gaveta',
          'consuma_e_detectar',
          'devolva_slot',
          'tudo_certo',
        ],
      );
      // numeração e total vêm do core; a UI só mostra
      expect(
        telas.map((t) => t.passo).whereType<int>().toList(),
        [1, 2, 3, 4],
      );
      expect(telas.every((t) => t.totalPassos == 4), isTrue);
      // O fluxo novo não usa OK: a liberação é do painel/CLI.
      expect(telas.where((t) => t.esperaBotao), isEmpty);
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
