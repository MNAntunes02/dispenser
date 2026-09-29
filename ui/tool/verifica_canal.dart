// Verificação manual do transporte real (FFI/AF_UNIX), sem `flutter test`.
//
// Útil para depurar o canal na mão quando o teste de integração falha.
// Uso:
//   python3 -m core.demo --socket /tmp/core.sock --sem-mini-ui &   # em dispenser/
//   dart run tool/verifica_canal.dart /tmp/core.sock
import 'dart:io';

import 'package:dispenser_ui/src/canal.dart';

Future<void> main(List<String> args) async {
  if (args.isEmpty) {
    stderr.writeln('uso: dart run tool/verifica_canal.dart <socket>');
    exit(2);
  }
  final canal = CanalSocketUnix(args.first);
  var recebidas = 0;
  canal.linhas.listen((l) {
    recebidas++;
    stderr.writeln('LINHA: $l');
  });
  canal.erros.listen((e) => stderr.writeln('ERRO: $e'));
  canal.iniciar();
  await Future<void>.delayed(const Duration(seconds: 2));
  if (recebidas > 0) {
    canal.enviar('{"v":1,"type":"input","acao":"confirma"}');
    await Future<void>.delayed(const Duration(seconds: 1));
  }
  await canal.dispose();
  stderr.writeln('total de linhas: $recebidas');
  exit(recebidas == 0 ? 1 : 0);
}
