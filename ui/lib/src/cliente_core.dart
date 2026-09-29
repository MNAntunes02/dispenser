/// Cliente do `dispenser-core`: linha JSON -> [MensagemCore].
///
/// Fica entre o [CanalCore] (transporte) e a UI. Cuida de duas coisas que a
/// tela não deve pensar:
///
/// - **Reconexão**: quando o canal cai, o cliente avisa `desconectado` e a UI
///   mostra "sem conexão" em vez de fingir que está tudo certo.
/// - **Silêncio do core**: o core manda `health` a cada 2 s. Se parar de
///   mandar, o socket continua aberto mas o core está travado — a UI trata
///   como falha, para o cuidador notar.
library;

import 'dart:async';
import 'dart:convert';

import 'canal.dart';
import 'modelo.dart';

/// Eventos que a UI consome do cliente.
sealed class EventoCore {
  const EventoCore();
}

/// Uma mensagem bem formada do core.
class MensagemRecebida extends EventoCore {
  const MensagemRecebida(this.mensagem);

  final MensagemCore mensagem;
}

/// Mudança de conexão do canal.
class ConexaoMudou extends EventoCore {
  const ConexaoMudou(this.conectado, [this.erro]);

  final bool conectado;
  final Object? erro;
}

/// Linha inválida do core (JSON quebrado, versão ou tipo fora do contrato).
///
/// A UI não cai por causa disso: avisa no log e segue exibindo a última tela
/// conhecida — o core é a fonte da verdade.
class LinhaInvalida extends EventoCore {
  const LinhaInvalida(this.erro);

  final MensagemInvalida erro;
}

class ClienteCore {
  ClienteCore(
    this.canal, {
    this.caminho = 'core',
    this.intervaloHealth = const Duration(seconds: 6),
  });

  final CanalCore canal;

  /// Caminho do socket, exibido na tela de erro.
  final String caminho;

  /// Se nenhum `health` chegar nesse prazo, tratamos o core como travado.
  final Duration intervaloHealth;

  final _eventos = StreamController<EventoCore>.broadcast();
  StreamSubscription<String>? _linhas;
  StreamSubscription<Object>? _erros;
  Timer? _vigia;
  DateTime _ultimoHealth = DateTime.fromMillisecondsSinceEpoch(0);
  bool _conectado = false;
  bool _parado = false;

  Stream<EventoCore> get eventos => _eventos.stream;

  bool get conectado => _conectado;

  void iniciar() {
    _linhas = canal.linhas.listen(_tratarLinha);
    _erros = canal.erros.listen(_tratarErro);
    _ultimoHealth = DateTime.now();
    _vigia = Timer.periodic(const Duration(seconds: 1), (_) => _vigiar());
    canal.iniciar();
  }

  /// Envia a intenção do paciente. Só existe uma ação: `confirma`.
  ///
  /// A UI nunca confirma nada por conta própria: quem valida é o core, junto
  /// com os sensores.
  void confirmar() => canal.enviar(jsonEncode({'v': 1, 'type': 'input', 'acao': 'confirma'}));

  Future<void> dispose() async {
    _parado = true;
    _vigia?.cancel();
    await _linhas?.cancel();
    await _erros?.cancel();
    await _eventos.close();
    await canal.dispose();
  }

  void _tratarLinha(String linha) {
    if (!_conectado) {
      _conectado = true;
      _eventos.add(const ConexaoMudou(true));
    }
    final MensagemCore mensagem;
    try {
      final bruto = jsonDecode(linha);
      if (bruto is! Map) {
        throw MensagemInvalida('mensagem não é um objeto');
      }
      mensagem = MensagemCore.deJson(bruto.cast<String, Object?>());
    } on MensagemInvalida catch (erro) {
      _eventos.add(LinhaInvalida(erro));
      return;
    } on FormatException catch (erro) {
      _eventos.add(LinhaInvalida(MensagemInvalida('json inválido: $erro')));
      return;
    }
    if (mensagem is Health) {
      _ultimoHealth = DateTime.now();
    }
    _eventos.add(MensagemRecebida(mensagem));
  }

  void _tratarErro(Object erro) {
    if (!_parado) {
      _conectado = false;
      _eventos.add(ConexaoMudou(false, erro));
    }
  }

  void _vigiar() {
    if (!_conectado || _parado) return;
    if (DateTime.now().difference(_ultimoHealth) > intervaloHealth) {
      // Socket aberto e core calado: melhor mostrar falha do que uma tela
      // parada fingindo que a dose está em dia.
      _conectado = false;
      _eventos.add(
        ConexaoMudou(false, ErroCanal('core não responde (sem heartbeat)')),
      );
    }
  }
}

/// Canal em memória: permite testar a UI inteira sem Pi nem socket.
class CanalMemoria implements CanalCore {
  final _linhas = StreamController<String>.broadcast();
  final _erros = StreamController<Object>.broadcast();
  final _enviados = <String>[];

  List<String> get enviados => List.unmodifiable(_enviados);

  @override
  Stream<String> get linhas => _linhas.stream;

  @override
  Stream<Object> get erros => _erros.stream;

  @override
  void iniciar() {}

  @override
  void enviar(String linha) => _enviados.add(linha);

  /// Simula uma linha recebida do core.
  void receber(String linha) => _linhas.add(linha);

  /// Simula queda do socket.
  void cair([Object? erro]) => _erros.add(erro ?? ErroCanal('conexão perdida'));

  @override
  Future<void> dispose() async {
    await _linhas.close();
    await _erros.close();
  }
}

/// Cliente sobre o [CanalMemoria], com utilitários de roteiro para os testes.
class ClienteCoreFake extends ClienteCore {
  ClienteCoreFake(this.memoria) : super(memoria, caminho: '/fake/core.sock');

  final CanalMemoria memoria;

  /// Entrega uma mensagem do core (serializa o mapa para a linha NDJSON).
  void receberMensagem(Map<String, Object?> mensagem) =>
      memoria.receber(jsonEncode(mensagem));

  /// Entrega a linha crua, como o core a escreveria no socket.
  void receberLinha(String linha) => memoria.receber(linha);
}
