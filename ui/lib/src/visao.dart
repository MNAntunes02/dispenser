/// Detecção de consumo do passo 2 (câmera + YOLO via subprocesso Python).
///
/// Regra de segurança do paciente (ADR 009/017): a UI **não decide** a dose.
/// A câmera é apoio visual do operador; quando a leitura fica estável, a UI
/// apenas mostra o status "aguardando liberação". Quem confirma o consumo é o
/// painel/CLI, por um comando explícito ao core.
///
/// A inferência (picamera2 + YOLO) roda em Python (`detecta_pill/`), iniciado
/// como subprocesso só durante o passo 2. Ele imprime uma linha NDJSON por
/// frame (`{"pill":N,"no_pill":M}`); a estabilidade é decidida aqui em Dart
/// (ver [EstabilidadeLeitura]).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

/// Uma leitura da câmera: quantos `pill` e `no_pill` foram detectados.
///
/// [quadro] é o JPEG anotado do preview (quando `--preview` está ligado). Ele
/// **não** entra na igualdade: a estabilidade depende só da contagem, e cada
/// frame novo invalidaria a janela.
class Leitura {
  const Leitura(this.pill, this.noPill, {this.quadro});

  final int pill;
  final int noPill;
  final Uint8List? quadro;

  @override
  bool operator ==(Object other) =>
      other is Leitura && other.pill == pill && other.noPill == noPill;

  @override
  int get hashCode => Object.hash(pill, noPill);

  @override
  String toString() =>
      'Leitura(pill: $pill, noPill: $noPill, quadro: ${quadro?.length ?? 0}B)';
}

/// Lê uma linha NDJSON do detector. Devolve `null` se a linha for inválida
/// (ruído do processo não pode virar leitura de câmera).
Leitura? leituraDeLinha(String linha) {
  final texto = linha.trim();
  if (texto.isEmpty) return null;
  final Object? bruto;
  try {
    bruto = jsonDecode(texto);
  } on FormatException {
    return null;
  }
  if (bruto is! Map) return null;
  final pill = bruto['pill'];
  final noPill = bruto['no_pill'];
  if (pill is! int || noPill is! int) return null;
  return Leitura(pill, noPill, quadro: _decodificarQuadro(bruto['frame']));
}

/// Decodifica o JPEG em base64 do preview. Frame inválido não invalida a
/// leitura: a contagem continua valendo e o preview simplesmente não aparece.
Uint8List? _decodificarQuadro(Object? bruto) {
  if (bruto is! String || bruto.isEmpty) return null;
  try {
    final bytes = base64Decode(bruto);
    return bytes.isEmpty ? null : bytes;
  } on FormatException {
    return null;
  }
}

/// Regra de estabilidade da detecção de consumo.
///
/// Avisa quando a **mesma** leitura se repete por [frames] quadros seguidos.
///
/// Com [minPilulas] > 0, leituras abaixo do mínimo zeram a janela (evita
/// avisar com a câmera ligada sem ler nenhuma cartela). O fluxo novo usa o
/// padrão 0: qualquer leitura estável é suficiente para o operador decidir.
class EstabilidadeLeitura {
  EstabilidadeLeitura({this.frames = 30, this.minPilulas = 0})
    : assert(frames > 0),
      assert(minPilulas >= 0);

  final int frames;
  final int minPilulas;

  final List<Leitura> _janela = <Leitura>[];

  /// Reinicia a janela (nova tentativa de leitura).
  void reiniciar() => _janela.clear();

  /// Registra uma leitura. Devolve `true` no instante em que a condição é
  /// atingida — e reinicia a janela para não repetir o aviso.
  bool registrar(Leitura leitura) {
    if (leitura.pill < minPilulas) {
      _janela.clear();
      return false;
    }
    if (_janela.isNotEmpty && _janela.last != leitura) {
      _janela.clear();
    }
    _janela.add(leitura);
    if (_janela.length >= frames) {
      _janela.clear();
      return true;
    }
    return false;
  }
}

/// Configuração da detecção, lida do ambiente (`DISPENSER_VISAO_*`).
class ConfiguracaoVisao {
  const ConfiguracaoVisao({
    required this.ativo,
    required this.python,
    required this.script,
    required this.modelo,
    required this.camera,
    required this.conf,
    required this.frames,
    required this.minPilulas,
    this.preview = true,
    this.previewFps = 5,
  });

  final bool ativo;
  final String python;
  final String script;
  final String modelo;
  final int camera;
  final double conf;
  final int frames;
  final int minPilulas;

  /// Pede o JPEG anotado junto do NDJSON (preview ao vivo do passo 2).
  final bool preview;

  /// Quadros de preview por segundo (0 = todo frame).
  final double previewFps;

  /// Lê `DISPENSER_VISAO_*` do ambiente. Sem `DISPENSER_VISAO_SCRIPT` a
  /// detecção fica desligada; a liberação manual continua disponível.
  factory ConfiguracaoVisao.doAmbiente(Map<String, String> ambiente) {
    final script = (ambiente['DISPENSER_VISAO_SCRIPT'] ?? '').trim();
    final ligada =
        _bool(ambiente['DISPENSER_VISAO_ATIVA']) ?? script.isNotEmpty;
    return ConfiguracaoVisao(
      ativo: ligada && script.isNotEmpty,
      python: (ambiente['DISPENSER_VISAO_PYTHON'] ?? 'python3').trim(),
      script: script,
      modelo: (ambiente['DISPENSER_VISAO_MODELO'] ?? 'best_ncnn_model').trim(),
      camera: _int(ambiente['DISPENSER_VISAO_CAMERA']) ?? 0,
      conf: _double(ambiente['DISPENSER_VISAO_CONF']) ?? 0.5,
      frames: _int(ambiente['DISPENSER_VISAO_FRAMES']) ?? 30,
      minPilulas: _int(ambiente['DISPENSER_VISAO_MIN_PILL']) ?? 0,
      preview: _bool(ambiente['DISPENSER_VISAO_PREVIEW']) ?? true,
      previewFps: _double(ambiente['DISPENSER_VISAO_PREVIEW_FPS']) ?? 5,
    );
  }
}

bool? _bool(String? valor) {
  final texto = valor?.trim().toLowerCase();
  if (texto == null || texto.isEmpty) return null;
  return const {'1', 'true', 'sim', 'on', 'yes'}.contains(texto);
}

int? _int(String? valor) => int.tryParse((valor ?? '').trim());

double? _double(String? valor) => double.tryParse((valor ?? '').trim());

/// Fonte de estabilidade da visão. O stream é informativo: a UI mostra o
/// status, mas não confirma a dose (a liberação é do painel/CLI).
abstract class DetectorConsumo {
  /// Emite quando a leitura da câmera ficou estável (status informativo).
  Stream<void> get confirmacoes;

  /// A última leitura estável, com a contagem de comprimidos.
  ///
  /// Usada no registro de cartela: a UI envia a contagem ao core, mas quem
  /// decide o slot e confirma a colocação é o painel/CLI.
  Stream<Leitura> get leituras => const Stream<Leitura>.empty();

  /// Emite o JPEG anotado do preview (vazio quando `preview` está desligado).
  Stream<Uint8List> get quadros;

  /// Mensagens de diagnóstico da câmera (stderr e falhas do subprocesso).
  Stream<String> get avisos => const Stream<String>.empty();

  /// A detecção está ligada e deveria haver uma câmera rodando.
  bool get ativo => false;

  /// Liga a detecção (chamado ao entrar no passo 2). Idempotente.
  void iniciar();

  /// Desliga a detecção (ao sair do passo 2 ou cair a conexão).
  void parar();

  Future<void> dispose();
}

/// Detecção desligada: nenhuma leitura estável é produzida.
class DetectorConsumoNulo implements DetectorConsumo {
  const DetectorConsumoNulo();

  @override
  Stream<void> get confirmacoes => const Stream<void>.empty();

  @override
  Stream<Leitura> get leituras => const Stream<Leitura>.empty();

  @override
  Stream<Uint8List> get quadros => const Stream<Uint8List>.empty();

  @override
  Stream<String> get avisos => const Stream<String>.empty();

  @override
  bool get ativo => false;

  @override
  void iniciar() {}

  @override
  void parar() {}

  @override
  Future<void> dispose() async {}
}

/// Detector controlável para testes (não abre câmera nem processo).
class DetectorConsumoFake implements DetectorConsumo {
  final _controller = StreamController<void>.broadcast();
  final _leiturasController = StreamController<Leitura>.broadcast();
  final _quadrosController = StreamController<Uint8List>.broadcast();
  final _avisosController = StreamController<String>.broadcast();

  int inicios = 0;
  int paradas = 0;
  bool _ligado = false;

  @override
  Stream<void> get confirmacoes => _controller.stream;

  @override
  Stream<Leitura> get leituras => _leiturasController.stream;

  @override
  Stream<Uint8List> get quadros => _quadrosController.stream;

  @override
  Stream<String> get avisos => _avisosController.stream;

  @override
  bool get ativo => _ligado;

  @override
  void iniciar() {
    _ligado = true;
    inicios++;
  }

  @override
  void parar() {
    _ligado = false;
    paradas++;
  }

  /// Simula a câmera com uma leitura estável.
  void confirmar({Leitura leitura = const Leitura(10, 0)}) {
    if (!_controller.isClosed) _controller.add(null);
    if (!_leiturasController.isClosed) _leiturasController.add(leitura);
  }

  /// Simula uma leitura estável sem emitir o status de dose.
  void emitirLeitura(Leitura leitura) {
    if (!_leiturasController.isClosed) _leiturasController.add(leitura);
  }

  /// Simula um quadro do preview ao vivo.
  void emitirQuadro(Uint8List quadro) {
    if (!_quadrosController.isClosed) _quadrosController.add(quadro);
  }

  /// Simula uma falha da câmera.
  void emitirAviso(String aviso) {
    if (!_avisosController.isClosed) _avisosController.add(aviso);
  }

  @override
  Future<void> dispose() async {
    await _controller.close();
    await _leiturasController.close();
    await _quadrosController.close();
    await _avisosController.close();
  }
}

/// Detector real: dispara o script Python e lê as leituras NDJSON.
class DetectorConsumoProcesso implements DetectorConsumo {
  DetectorConsumoProcesso(this.config, {EstabilidadeLeitura? estabilidade})
    : _estabilidade =
          estabilidade ??
          EstabilidadeLeitura(
            frames: config.frames,
            minPilulas: config.minPilulas,
          );

  final ConfiguracaoVisao config;
  final EstabilidadeLeitura _estabilidade;
  final _controller = StreamController<void>.broadcast();
  final _leiturasController = StreamController<Leitura>.broadcast();
  final _quadrosController = StreamController<Uint8List>.broadcast();
  final _avisosController = StreamController<String>.broadcast();
  final _ultimosErros = <String>[];

  Process? _processo;
  StreamSubscription<String>? _linhas;
  bool _deveRodar = false;

  @override
  Stream<void> get confirmacoes => _controller.stream;

  @override
  Stream<Leitura> get leituras => _leiturasController.stream;

  @override
  Stream<Uint8List> get quadros => _quadrosController.stream;

  @override
  Stream<String> get avisos => _avisosController.stream;

  @override
  bool get ativo => _deveRodar && config.ativo;

  @override
  void iniciar() {
    if (!config.ativo || _deveRodar) return;
    _deveRodar = true;
    _ultimosErros.clear();
    _estabilidade.reiniciar();
    unawaited(_iniciarProcesso());
  }

  void _registrarLog(String mensagem) {
    final texto = _resumir(mensagem);
    if (texto.isEmpty) return;
    stderr.writeln('[visao] $texto');
  }

  void _registrarAviso(String mensagem) {
    final texto = _resumir(mensagem);
    if (texto.isEmpty) return;
    _registrarLog(texto);
    if (!_avisosController.isClosed) _avisosController.add(texto);
  }

  void _guardarErro(String linha) {
    final texto = _resumir(linha);
    if (texto.isEmpty) return;
    _ultimosErros.add(texto);
    if (_ultimosErros.length > 8) _ultimosErros.removeAt(0);
  }

  Future<void> _iniciarProcesso() async {
    _registrarLog(
      'iniciando ${config.script} (camera=${config.camera}, modelo=${config.modelo})',
    );
    try {
      final processo = await Process.start(config.python, <String>[
        config.script,
        '--modelo',
        config.modelo,
        '--camera',
        '${config.camera}',
        '--conf',
        '${config.conf}',
        '--ndjson',
        if (config.preview) ...[
          '--preview',
          '--preview-fps',
          '${config.previewFps}',
        ],
      ]);
      if (!_deveRodar) {
        // `parar()` chegou antes de o processo subir: não deixar câmera órfã.
        processo.kill();
        return;
      }
      _processo = processo;
      _registrarLog('câmera iniciada (pid ${processo.pid})');
      _linhas = processo.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen(_tratarLinha);
      processo.stderr
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen((linha) {
            _guardarErro(linha);
            _registrarAviso('stderr: $linha');
          });
      unawaited(
        processo.exitCode.then((codigo) {
          if (!identical(_processo, processo)) return;
          _processo = null;
          _linhas = null;
          if (!_deveRodar) return;
          final ultimo = _ultimosErros.isEmpty
              ? ''
              : ' — ${_ultimosErros.last}';
          _registrarAviso('câmera encerrou (código $codigo)$ultimo');
        }),
      );
    } on ProcessException catch (erro) {
      // Sem câmera/script: o status mostra a falha; a liberação manual segue.
      _processo = null;
      _registrarAviso('não foi possível iniciar a câmera: ${erro.message}');
    }
  }

  void _tratarLinha(String linha) {
    final leitura = leituraDeLinha(linha);
    if (leitura == null) {
      final texto = linha.trim();
      if (texto.isNotEmpty && !texto.startsWith('{')) {
        _registrarLog(texto);
      }
      return;
    }
    final quadro = leitura.quadro;
    if (quadro != null && !_quadrosController.isClosed) {
      _quadrosController.add(quadro);
    }
    if (_estabilidade.registrar(leitura)) {
      if (!_controller.isClosed) _controller.add(null);
      if (!_leiturasController.isClosed) _leiturasController.add(leitura);
    }
  }

  @override
  void parar() {
    _deveRodar = false;
    final processo = _processo;
    _processo = null;
    _linhas?.cancel();
    _linhas = null;
    if (processo != null) {
      processo.kill();
      Timer(const Duration(seconds: 3), () {
        processo.kill(ProcessSignal.sigkill);
      });
    }
    _estabilidade.reiniciar();
  }

  @override
  Future<void> dispose() async {
    parar();
    await _controller.close();
    await _leiturasController.close();
    await _quadrosController.close();
    await _avisosController.close();
  }
}

String _resumir(String texto) {
  final limpo = texto.replaceAll(RegExp(r'\s+'), ' ').trim();
  if (limpo.length <= 300) return limpo;
  return '${limpo.substring(0, 297)}...';
}

/// Cria o detector a partir do ambiente: processo real se ativo, senão nulo.
DetectorConsumo detectorDoAmbiente(Map<String, String> ambiente) {
  final config = ConfiguracaoVisao.doAmbiente(ambiente);
  if (!config.ativo) return const DetectorConsumoNulo();
  return DetectorConsumoProcesso(config);
}
