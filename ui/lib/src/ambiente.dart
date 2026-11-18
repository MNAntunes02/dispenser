import 'dart:io';

bool _permitida(String chave) =>
    chave == 'DISPENSER_SOCKET' || chave.startsWith('DISPENSER_VISAO_');

Map<String, String> carregarAmbiente({
  Map<String, String> base = const {},
  String? arquivo,
  Directory? inicio,
}) {
  final caminho = arquivo ?? base['DISPENSER_ENV_PATH'];
  final lido = _ler(_localizar(caminho, inicio));
  return {...lido, ...base};
}

File? _localizar(String? caminho, Directory? inicio) {
  if (caminho != null && caminho.trim().isNotEmpty) {
    final arquivo = File(caminho.trim());
    return arquivo.existsSync() ? arquivo : null;
  }
  final origens = <Directory>[
    inicio ?? Directory.current,
    File(Platform.resolvedExecutable).parent,
  ];
  final visitados = <String>{};
  for (final origem in origens) {
    var diretorio = origem;
    for (var nivel = 0; nivel < 6; nivel++) {
      if (!visitados.add(diretorio.path)) break;
      final arquivo = File('${diretorio.path}/.env');
      if (arquivo.existsSync()) return arquivo;
      final pai = diretorio.parent;
      if (pai.path == diretorio.path) break;
      diretorio = pai;
    }
  }
  return null;
}

Map<String, String> _ler(File? arquivo) {
  if (arquivo == null) return const {};
  final valores = <String, String>{};
  for (final bruta in arquivo.readAsLinesSync()) {
    var linha = bruta.trim();
    if (linha.isEmpty || linha.startsWith('#')) continue;
    if (linha.startsWith('export ')) linha = linha.substring(7).trimLeft();
    final igual = linha.indexOf('=');
    if (igual <= 0) continue;
    final chave = linha.substring(0, igual).trim();
    if (!_permitida(chave)) continue;
    var valor = linha.substring(igual + 1).trim();
    final citado =
        valor.length >= 2 &&
        ((valor.startsWith('"') && valor.endsWith('"')) ||
            (valor.startsWith("'") && valor.endsWith("'")));
    if (citado) {
      valor = valor.substring(1, valor.length - 1);
    } else {
      final comentario = valor.indexOf(' #');
      if (comentario >= 0) valor = valor.substring(0, comentario).trimRight();
    }
    valores[chave] = valor;
  }
  return valores;
}
