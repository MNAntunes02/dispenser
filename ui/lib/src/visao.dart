/// Detecção de consumo do passo 4 (câmera + YOLO via subprocesso Python).
///
/// Regra de segurança do paciente (ADR 009): a UI **não decide** a dose. Quando
/// a leitura da câmera fica estável, a UI apenas envia o mesmo `input:confirma`
/// do botão OK — o core continua validando com os sensores. O botão OK segue
/// disponível como fallback: sem câmera, o comportamento é o de sempre.
///
/// A inferência (picamera2 + YOLO) roda em Python (`detecta_pill/`), iniciado
/// como subprocesso só durante o passo 4. Ele imprime uma linha NDJSON por
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
/// Confirma quando a **mesma** leitura se repete por [frames] quadros seguidos,
/// exigindo ao menos [minPilulas] comprimidos — evita confirmar com a câmera
/// ligada sem ler nenhuma cartela. Qualquer leitura diferente reinicia a
/// contagem; uma leitura sem comprimido também zera a janela.
class EstabilidadeLeitura {
  EstabilidadeLeitura({this.frames = 30, this.minPilulas = 1})
      : assert(frames > 0),
        assert(minPilulas > 0);

  final int frames;
  final int minPilulas;

  final List<Leitura> _janela = <Leitura>[];

  /// Reinicia a janela (nova tentativa de leitura).
  void reiniciar() => _janela.clear();

  /// Registra uma leitura. Devolve `true` no instante em que a condição é
  /// atingida — e reinicia a janela para não confirmar de novo.
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

  /// Pede o JPEG anotado junto do NDJSON (preview ao vivo do passo 4).
  final bool preview;

  /// Quadros de preview por segundo (0 = todo frame).
  final double previewFps;

  /// Lê `DISPENSER_VISAO_*` do ambiente. Sem `DISPENSER_VISAO_SCRIPT` a
  /// detecção fica desligada (o comportamento é o de hoje: só o botão OK).
  factory ConfiguracaoVisao.doAmbiente(Map<String, String> ambiente) {
    final script = (ambiente['DISPENSER_VISAO_SCRIPT'] ?? '').trim();
    final ligada = _bool(ambiente['DISPENSER_VISAO_ATIVA']) ?? script.isNotEmpty;
    return ConfiguracaoVisao(
      ativo: ligada && script.isNotEmpty,
      python: (ambiente['DISPENSER_VISAO_PYTHON'] ?? 'python3').trim(),
      script: script,
      modelo: (ambiente['DISPENSER_VISAO_MODELO'] ?? 'best_ncnn_model').trim(),
      camera: _int(ambiente['DISPENSER_VISAO_CAMERA']) ?? 0,
      conf: _double(ambiente['DISPENSER_VISAO_CONF']) ?? 0.5,
      frames: _int(ambiente['DISPENSER_VISAO_FRAMES']) ?? 30,
      minPilulas: _int(ambiente['DISPENSER_VISAO_MIN_PILL']) ?? 1,
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

/// Fonte de confirmação por visão. A UI só envia `confirma` quando este stream
/// emite — nunca por conta própria.
abstract class DetectorConsumo {
  /// Emite quando a leitura da câmera ficou estável (vira o OK do passo 4).
  Stream<void> get confirmacoes;

  /// Emite o JPEG anotado do preview (vazio quando `preview` está desligado).
  Stream<Uint8List> get quadros;

  /// Liga a detecção (chamado ao entrar no passo 4). Idempotente.
  void iniciar();

  /// Desliga a detecção (ao sair do passo 4 ou cair a conexão).
  void parar();

  Future<void> dispose();
}

/// Detecção desligada: nada é confirmado por visão (o OK manual continua).
class DetectorConsumoNulo implements DetectorConsumo {
  const DetectorConsumoNulo();

  @override
  Stream<void> get confirmacoes => const Stream<void>.empty();

  @override
  Stream<Uint8List> get quadros => const Stream<Uint8List>.empty();

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
  final _quadrosController = StreamController<Uint8List>.broadcast();

  int inicios = 0;
  int paradas = 0;

  @override
  Stream<void> get confirmacoes => _controller.stream;

  @override
  Stream<Uint8List> get quadros => _quadrosController.stream;

  @override
  void iniciar() => inicios++;

  @override
  void parar() => paradas++;

  /// Simula a câmera reconhecendo o consumo (leitura estável).
  void confirmar() {
    if (!_controller.isClosed) _controller.add(null);
  }

  /// Simula um quadro do preview ao vivo.
  void emitirQuadro(Uint8List quadro) {
    if (!_quadrosController.isClosed) _quadrosController.add(quadro);
  }

  @override
  Future<void> dispose() async {
    await _controller.close();
    await _quadrosController.close();
  }
}

/// Detector real: dispara o script Python e lê as leituras NDJSON.
class DetectorConsumoProcesso implements DetectorConsumo {
  DetectorConsumoProcesso(this.config, {EstabilidadeLeitura? estabilidade})
      : _estabilidade = estabilidade ??
            EstabilidadeLeitura(
              frames: config.frames,
              minPilulas: config.minPilulas,
            );

  final ConfiguracaoVisao config;
  final EstabilidadeLeitura _estabilidade;
  final _controller = StreamController<void>.broadcast();
  final _quadrosController = StreamController<Uint8List>.broadcast();

  Process? _processo;
  StreamSubscription<String>? _linhas;
  bool _deveRodar = false;

  @override
  Stream<void> get confirmacoes => _controller.stream;

  @override
  Stream<Uint8List> get quadros => _quadrosController.stream;

  @override
  void iniciar() {
    if (!config.ativo || _deveRodar) return;
    _deveRodar = true;
    _estabilidade.reiniciar();
    unawaited(_iniciarProcesso());
  }

  Future<void> _iniciarProcesso() async {
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
      _linhas = processo.stdout
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen(_tratarLinha);
      // Drena o stderr para o processo não travar se o pipe encher.
      unawaited(processo.stderr.drain<void>());
      unawaited(processo.exitCode.then((_) {
        if (identical(_processo, processo)) {
          _processo = null;
          _linhas = null;
        }
      }));
    } on ProcessException {
      // Sem câmera/script: fica sem confirmação e o OK manual segue valendo.
      _processo = null;
    }
  }

  void _tratarLinha(String linha) {
    final leitura = leituraDeLinha(linha);
    if (leitura == null) return;
    final quadro = leitura.quadro;
    if (quadro != null && !_quadrosController.isClosed) {
      _quadrosController.add(quadro);
    }
    if (_estabilidade.registrar(leitura) && !_controller.isClosed) {
      _controller.add(null);
    }
  }

  @override
  void parar() {
    _deveRodar = false;
    final processo = _processo;
    _processo = null;
    _linhas?.cancel();
    _linhas = null;
    processo?.kill();
    _estabilidade.reiniciar();
  }

  @override
  Future<void> dispose() async {
    parar();
    await _controller.close();
    await _quadrosController.close();
  }
}

/// Cria o detector a partir do ambiente: processo real se ativo, senão nulo.
DetectorConsumo detectorDoAmbiente(Map<String, String> ambiente) {
  final config = ConfiguracaoVisao.doAmbiente(ambiente);
  if (!config.ativo) return const DetectorConsumoNulo();
  return DetectorConsumoProcesso(config);
}
