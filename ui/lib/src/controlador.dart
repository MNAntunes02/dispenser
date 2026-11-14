/// Estado da tela e regras de apresentação (a UI não decide o fluxo da dose).
///
/// O controlador só guarda o que o core publicou (tela, agenda, avisos) e
/// escolhe qual das quatro telas mostrar. Regras:
///
/// - `desconectado` -> tela "sem conexão" (a UI não inventa estado de dose);
/// - ligado sem tela ainda -> "iniciando" (core conectado, retrato a caminho);
/// - tela com `esperaBotao` -> fluxo da dose com o botão OK;
/// - qualquer outra -> repouso.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'cliente_core.dart';
import 'modelo.dart';
import 'visao.dart';

/// Uma tela que o controlador pode mostrar.
sealed class EstadoUI {
  const EstadoUI();

  /// Momento de referência do relógio exibido (a UI só mostra horas).
  DateTime get agora;
}

/// Core fora do ar: nada pode ser afirmado sobre a dose.
class EstadoSemCore extends EstadoUI {
  const EstadoSemCore({
    required this.momento,
    required this.rotulos,
    this.erro,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final Object? erro;

  @override
  DateTime get agora => momento;
}

/// Core conectado, aguardando o retrato inicial.
class EstadoIniciando extends EstadoUI {
  const EstadoIniciando({
    required this.momento,
    required this.rotulos,
    this.erro,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final String? erro;

  @override
  DateTime get agora => momento;
}

/// Repouso: nenhuma dose em aberto.
class EstadoRepouso extends EstadoUI {
  const EstadoRepouso({
    required this.momento,
    required this.rotulos,
    required this.agenda,
    this.aviso,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final Agenda agenda;

  /// Último aviso do core (falha de sensor, gaveta fora de horário).
  final Aviso? aviso;

  /// Próxima dose a exibir: a primeira que o core ainda não marcou como
  /// concluída. A UI não filtra por horário — quem sabe é o core.
  Ocorrencia? get proxima => agenda.emAberto ?? agenda.primeira;

  @override
  DateTime get agora => momento;
}

/// Dose em andamento: um passo por tela, com o número do passo.
class EstadoDose extends EstadoUI {
  const EstadoDose({
    required this.momento,
    required this.rotulos,
    required this.tela,
    required this.agenda,
    this.aviso,
    this.visaoAtiva = false,
    this.visaoAviso,
    this.visaoEspera = Duration.zero,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final Tela tela;
  final Agenda agenda;
  final Aviso? aviso;
  final bool visaoAtiva;
  final String? visaoAviso;
  final Duration visaoEspera;

  @override
  DateTime get agora => momento;
}

/// Converte os eventos do core no estado mostrado na tela.
class ControladorUI extends ChangeNotifier {
  ControladorUI(
    this.cliente, {
    DateTime Function()? relogio,
    DetectorConsumo? detector,
    this.limiteSemTela = const Duration(seconds: 5),
    this.intervaloVigia = const Duration(seconds: 1),
    this.maxTentativasSemTela = 2,
  }) : _agora = relogio ?? DateTime.now,
       _detector = detector ?? const DetectorConsumoNulo() {
    _rotulos = Rotulos.vazio;
    _agenda = Agenda.vazia;
    _eventos = cliente.eventos.listen(_tratarEvento);
    _visao = _detector.confirmacoes.listen((_) => _confirmarPorVisao());
    _quadrosVisao = _detector.quadros.listen(_tratarQuadro);
    _avisosVisao = _detector.avisos.listen(_tratarAvisoVisao);
  }

  final ClienteCore cliente;
  final DateTime Function() _agora;
  final DetectorConsumo _detector;
  final Duration limiteSemTela;
  final Duration intervaloVigia;
  final int maxTentativasSemTela;
  late final StreamSubscription<EventoCore> _eventos;
  late final StreamSubscription<void> _visao;
  late final StreamSubscription<Uint8List> _quadrosVisao;
  late final StreamSubscription<String> _avisosVisao;

  Rotulos _rotulos = Rotulos.vazio;
  Agenda _agenda = Agenda.vazia;
  Tela? _tela;
  Aviso? _aviso;
  bool _conectado = false;
  Object? _erro;
  Timer? _relogio;

  DateTime? _semTelaDesde;
  int _tentativasSemTela = 0;
  String? _erroSemTela;

  /// A detecção de visão está ligada agora (só durante o passo 4).
  bool _visaoLigada = false;

  /// A visão já confirmou esta dose (não repetir o `confirma`).
  bool _visaoConfirmou = false;

  /// Último quadro do preview da câmera (só no passo 4).
  Uint8List? _quadro;

  String? _visaoAviso;
  DateTime? _visaoIniciadaEm;

  Rotulos get rotulos => _rotulos;
  Agenda get agenda => _agenda;
  bool get conectado => _conectado;

  /// Estado atual da tela (recalculado a cada segundo e a cada evento).
  EstadoUI get estado {
    final agora = _agora();
    if (!_conectado) {
      return EstadoSemCore(momento: agora, rotulos: _rotulos, erro: _erro);
    }
    final tela = _tela;
    if (tela == null) {
      return EstadoIniciando(
        momento: agora,
        rotulos: _rotulos,
        erro: _erroSemTela,
      );
    }
    if (tela.doseEmAberto) {
      return EstadoDose(
        momento: agora,
        rotulos: _rotulos,
        tela: tela,
        agenda: _agenda,
        aviso: _aviso,
        visaoAtiva: _detector.ativo,
        visaoAviso: _visaoAviso,
        visaoEspera: _visaoIniciadaEm == null
            ? Duration.zero
            : agora.difference(_visaoIniciadaEm!),
      );
    }
    return EstadoRepouso(
      momento: agora,
      rotulos: _rotulos,
      agenda: _agenda,
      aviso: _aviso,
    );
  }

  /// Última tela do core, se houver.
  Tela? get tela => _tela;

  /// Botão OK visível? Só quando o core pediu (`ok` pendente).
  bool get podeConfirmar => _tela?.esperaBotao ?? false;

  /// Último frame do preview da câmera, se houver (passo 4).
  Uint8List? get quadro => _quadro;

  /// Erro mostrado quando o core está conectado mas não manda tela.
  String? get erroSemTela => _erroSemTela;

  void iniciar() {
    _relogio = Timer.periodic(intervaloVigia, (_) {
      _verificarSemTela();
      notifyListeners();
    });
  }

  void _verificarSemTela() {
    if (!_conectado || _tela != null) {
      _semTelaDesde = null;
      _tentativasSemTela = 0;
      _erroSemTela = null;
      return;
    }
    final agora = _agora();
    _semTelaDesde ??= agora;
    final esperando = agora.difference(_semTelaDesde!);
    if (esperando < limiteSemTela) return;
    if (_tentativasSemTela >= maxTentativasSemTela) {
      _erroSemTela ??=
          'Core conectado, mas sem o estado da dose. Reinicie o core.';
      return;
    }
    _tentativasSemTela++;
    _semTelaDesde = agora;
    _erroSemTela = null;
    final espera = esperando.inSeconds >= 1
        ? '${esperando.inSeconds}s'
        : '${esperando.inMilliseconds}ms';
    stderr.writeln(
      '[ui] conectado sem tela há $espera; '
      'reconectando (tentativa $_tentativasSemTela/$maxTentativasSemTela)',
    );
    cliente.reconectar();
  }

  /// O paciente apertou OK: só isso vai para o core. A UI não decide se a
  /// dose foi tomada — o core confere os sensores e responde.
  void confirmar() => cliente.confirmar();

  /// A detecção de visão liga só no passo 4 (consumo) e desliga ao sair. Sem
  /// câmera o detector é nulo e nada muda: o botão OK segue valendo.
  void _ajustarVisao() {
    final noConsumo = _conectado && _tela?.chave == 'tome_e_ok';
    if (noConsumo) {
      if (!_visaoLigada) {
        _visaoLigada = true;
        _visaoConfirmou = false;
        _quadro = null;
        _visaoAviso = null;
        _visaoIniciadaEm = _agora();
        _detector.iniciar();
      }
    } else if (_visaoLigada) {
      _visaoLigada = false;
      _quadro = null;
      _visaoAviso = null;
      _visaoIniciadaEm = null;
      _detector.parar();
    }
  }

  void _tratarAvisoVisao(String aviso) {
    if (!_visaoLigada) return;
    _visaoAviso = aviso;
    notifyListeners();
  }

  /// Guarda o frame do preview e redesenha a tela. Fora do passo 4 o quadro é
  /// descartado: a câmera só existe durante o consumo.
  void _tratarQuadro(Uint8List quadro) {
    if (!_conectado || _tela?.chave != 'tome_e_ok') return;
    _quadro = quadro;
    notifyListeners();
  }

  /// A câmera reconheceu o consumo: manda o mesmo `confirma` do botão OK.
  ///
  /// Guardas: só no passo 4, uma vez por dose e nunca no lugar do core — quem
  /// valida a dose continua sendo ele (ADR 009).
  void _confirmarPorVisao() {
    if (_visaoConfirmou) return;
    if (!_conectado || _tela?.chave != 'tome_e_ok') return;
    _visaoConfirmou = true;
    confirmar();
  }

  void _tratarEvento(EventoCore evento) {
    switch (evento) {
      case ConexaoMudou(:final conectado, :final erro):
        _conectado = conectado;
        _erro = erro;
        _semTelaDesde = null;
        _tentativasSemTela = 0;
        _erroSemTela = null;
        if (!conectado) {
          // Sem core não há estado confiável: limpa a tela para não exibir
          // um passo antigo como se fosse verdade atual.
          _tela = null;
          _aviso = null;
          _ajustarVisao();
        }
      case MensagemRecebida(:final mensagem):
        _aplicar(mensagem);
      case LinhaInvalida():
        // Linha ruim não muda a tela; o core reenvia o retrato ao reconectar.
        break;
    }
    notifyListeners();
  }

  void _aplicar(MensagemCore mensagem) {
    switch (mensagem) {
      case Rotulos():
        _rotulos = mensagem;
      case Agenda():
        _agenda = mensagem;
      case Tela():
        _tela = mensagem;
        _semTelaDesde = null;
        _tentativasSemTela = 0;
        _erroSemTela = null;
        // A tela do fluxo também é a última linha do aviso: se o core mostra
        // uma falha, o aviso some junto (evita alerta fantasma).
        if (mensagem.fluxo == 'alerta') {
          _aviso = Aviso(codigo: mensagem.chave, mensagem: mensagem.mensagem);
        } else if (_aviso != null) {
          _aviso = null;
        }
        _ajustarVisao();
      case Aviso():
        _aviso = mensagem;
      case Health():
        break;
    }
  }

  @override
  void dispose() {
    _relogio?.cancel();
    unawaited(_eventos.cancel());
    unawaited(_visao.cancel());
    unawaited(_quadrosVisao.cancel());
    unawaited(_avisosVisao.cancel());
    unawaited(_detector.dispose());
    super.dispose();
  }
}
