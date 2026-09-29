/// Canal de transporte entre a UI e o core.
///
/// O core escuta em um Unix socket (`core/servidor_ui.py`, ADR 003). O
/// `dart:io` do Flutter **não** expõe AF_UNIX, então a implementação real usa
/// `dart:ffi` para `socket()/connect()/send()/recv()` direto na libc, dentro de
/// uma isolate separada (o `recv` é bloqueante e não pode travar a UI).
///
/// A UI fala NDJSON: uma mensagem por linha.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:ffi';
import 'dart:isolate';

import 'package:ffi/ffi.dart';

/// Caminho padrão do socket no Pi.
const String kSocketPadrao = '/run/dispenser/core.sock';

/// Conexão com o core: linhas de entrada, erros e escrita.
abstract interface class CanalCore {
  /// Linhas recebidas do core (sem o `\n`).
  Stream<String> get linhas;

  /// Erro de conexão (o canal reconecta sozinho).
  Stream<Object> get erros;

  /// Abre o canal. Idempotente: chamar de novo não abre duas conexões.
  void iniciar();

  /// Envia uma linha para o core.
  void enviar(String linha);

  /// Fecha o canal.
  Future<void> dispose();
}

/// Canal real: Unix socket + JSON linhas, com reconexão automática.
class CanalSocketUnix implements CanalCore {
  CanalSocketUnix(this._caminho, {this.esperaReconexao = const Duration(seconds: 1)});

  final String _caminho;
  final Duration esperaReconexao;

  final _linhas = StreamController<String>.broadcast();
  final _erros = StreamController<Object>.broadcast();

  Isolate? _isolate;
  ReceivePort? _porta;
  SendPort? _comandos;
  Timer? _tempo;
  bool _iniciado = false;
  bool _parado = false;

  @override
  Stream<String> get linhas => _linhas.stream;

  @override
  Stream<Object> get erros => _erros.stream;

  String get caminho => _caminho;

  @override
  void iniciar() {
    if (_iniciado || _parado) return;
    _iniciado = true;
    _conectar();
  }

  @override
  void enviar(String linha) => _comandos?.send(linha);

  @override
  Future<void> dispose() async {
    _parado = true;
    _tempo?.cancel();
    _comandos?.send(null);
    _isolate?.kill(priority: Isolate.immediate);
    _isolate = null;
    _porta?.close();
    _porta = null;
    await _linhas.close();
    await _erros.close();
  }

  void _conectar() {
    if (_parado) return;
    final porta = ReceivePort();
    _porta = porta;
    porta.listen((Object? mensagem) {
      if (mensagem is SendPort) {
        _comandos = mensagem;
      } else if (mensagem is String) {
        _linhas.add(mensagem);
      } else if (mensagem is ErroCanal) {
        _erros.add(mensagem);
        _reconectar();
      } else if (mensagem == null) {
        porta.close();
      }
    });
    Isolate.spawn(_loopSocket, _ArgsSocket(porta.sendPort, _caminho)).then(
      (isolate) => _isolate = isolate,
      onError: (Object erro) {
        _erros.add(erro);
        _reconectar();
      },
    );
  }

  void _reconectar() {
    if (_parado) return;
    _isolate?.kill(priority: Isolate.immediate);
    _isolate = null;
    _comandos = null;
    _porta?.close();
    _porta = null;
    _tempo?.cancel();
    _tempo = Timer(esperaReconexao, _conectar);
  }
}

/// Erro do canal com caminho e motivo (traduzido para aviso na tela).
class ErroCanal implements Exception {
  ErroCanal(this.motivo, {this.caminho = ''});

  final String motivo;
  final String caminho;

  @override
  String toString() => 'ErroCanal: $motivo';
}

class _ArgsSocket {
  const _ArgsSocket(this.resposta, this.caminho);

  final SendPort resposta;
  final String caminho;
}

/// Isolate do socket: conecta, repassa linhas lidas e atende a fila de saída.
///
/// A leitura **não** pode ser um `recv` bloqueante: enquanto o isolate está
/// preso na chamada da libc, ele não roda o event loop e nunca entrega as
/// mensagens de saída (`confirmar` do paciente). Por isso usamos `poll(2)` com
/// um intervalo curto e cedemos a vez entre as checagens.
Future<void> _loopSocket(_ArgsSocket args) async {
  final socket = _SocketLibc();
  final entrada = ReceivePort();
  args.resposta.send(entrada.sendPort);
  var fd = -1;
  var parar = false;
  entrada.listen((Object? mensagem) {
    if (mensagem == null) {
      parar = true;
      if (fd >= 0) {
        socket.fechar(fd);
        fd = -1;
      }
      return;
    }
    if (mensagem is String && fd >= 0) socket.escrever(fd, mensagem);
  });

  while (!parar) {
    try {
      fd = socket.conectar(args.caminho);
    } on Object catch (erro) {
      args.resposta.send(ErroCanal('$erro', caminho: args.caminho));
      return;
    }
    final buffer = <int>[];
    while (!parar && fd >= 0) {
      if (!socket.temDados(fd)) {
        // cede a vez: o event loop do isolate entrega o que a UI mandou
        await Future<void>.delayed(_intervaloVotacao);
        continue;
      }
      final lido = socket.ler(fd);
      if (lido == null || lido.isEmpty) break;
      buffer.addAll(lido);
      var quebra = buffer.indexOf(0x0a);
      while (quebra >= 0) {
        final linha = utf8.decode(buffer.sublist(0, quebra), allowMalformed: true);
        buffer.removeRange(0, quebra + 1);
        if (linha.trim().isNotEmpty) args.resposta.send(linha);
        quebra = buffer.indexOf(0x0a);
      }
    }
    if (fd >= 0) {
      socket.fechar(fd);
      fd = -1;
    }
    if (parar) return;
    args.resposta.send(ErroCanal('conexão fechada', caminho: args.caminho));
  }
}

// --- ligações mínimas com a libc (AF_UNIX) ---------------------------------

typedef _SocketNative = Int32 Function(Int32, Int32, Int32);
typedef _SocketDart = int Function(int, int, int);
typedef _ConnectNative = Int32 Function(Int32, Pointer<NativeType>, Int32);
typedef _ConnectDart = int Function(int, Pointer<NativeType>, int);
typedef _EnviarNative = IntPtr Function(Int32, Pointer<Uint8>, IntPtr, Int32);
typedef _EnviarDart = int Function(int, Pointer<Uint8>, int, int);
typedef _LerNative = IntPtr Function(Int32, Pointer<Uint8>, IntPtr, Int32);
typedef _LerDart = int Function(int, Pointer<Uint8>, int, int);
typedef _FecharNative = Int32 Function(Int32);
typedef _FecharDart = int Function(int);
// int poll(struct pollfd *fds, nfds_t nfds, int timeout)
typedef _PollNative = Int32 Function(Pointer<NativeType>, IntPtr, Int32);
typedef _PollDart = int Function(Pointer<NativeType>, int, int);

/// `struct pollfd` em x86_64/arm64: `int fd`, `short events`, `short revents`.
final class _PollFd extends Struct {
  @Int32()
  external int fd;

  @Int16()
  external int events;

  @Int16()
  external int revents;
}

/// Quanto o isolate espera antes de checar de novo se há dado (ou comando).
///
/// 50 ms é imperceptível para o paciente e mantém o isolate respondendo.
const Duration _intervaloVotacao = Duration(milliseconds: 50);

/// Ligação com `socket(2)`/`connect(2)`/`send(2)`/`recv(2)`/`close(2)`.
class _SocketLibc {
  _SocketLibc() {
    final lib = DynamicLibrary.process();
    _socket = lib.lookupFunction<_SocketNative, _SocketDart>('socket');
    _connectar = lib.lookupFunction<_ConnectNative, _ConnectDart>('connect');
    _enviar = lib.lookupFunction<_EnviarNative, _EnviarDart>('send');
    _ler = lib.lookupFunction<_LerNative, _LerDart>('recv');
    _fechar = lib.lookupFunction<_FecharNative, _FecharDart>('close');
    _poll = lib.lookupFunction<_PollNative, _PollDart>('poll');
  }

  late final _SocketDart _socket;
  late final _ConnectDart _connectar;
  late final _EnviarDart _enviar;
  late final _LerDart _ler;
  late final _FecharDart _fechar;
  late final _PollDart _poll;

  static const int afUnix = 1;
  static const int sockStream = 1;
  static const int sockCloexec = 0x80000;
  static const int pollIn = 0x001;

  /// Há dados para ler no socket agora?
  bool temDados(int fd) {
    final fds = calloc<_PollFd>();
    try {
      fds.ref
        ..fd = fd
        ..events = pollIn
        ..revents = 0;
      return _poll(fds.cast<NativeType>(), 1, 0) == 1;
    } finally {
      calloc.free(fds);
    }
  }

  /// Monta `struct sockaddr_un` e conecta. Lança em caso de erro.
  int conectar(String caminho) {
    final tamanho = _tamanhoEndereco(caminho);
    final addr = calloc<Uint8>(tamanho);
    try {
      // sun_family = AF_UNIX (little-endian) ocupa os 2 primeiros bytes
      addr[0] = afUnix & 0xff;
      addr[1] = (afUnix >> 8) & 0xff;
      final bytes = utf8.encode(caminho);
      for (var i = 0; i < bytes.length; i++) {
        addr[2 + i] = bytes[i];
      }
      addr[tamanho - 1] = 0; // NUL final do sun_path
      final fd = _socket(afUnix, sockStream | sockCloexec, 0);
      if (fd < 0) throw Exception('socket() falhou');
      if (_connectar(fd, addr.cast<NativeType>(), tamanho) != 0) {
        _fechar(fd);
        throw Exception('connect() falhou em $caminho');
      }
      return fd;
    } finally {
      calloc.free(addr);
    }
  }

  void escrever(int fd, String linha) {
    final bytes = utf8.encode('$linha\n');
    final buffer = calloc<Uint8>(bytes.length);
    try {
      final destino = buffer.asTypedList(bytes.length);
      destino.setAll(0, bytes);
      var enviados = 0;
      while (enviados < bytes.length) {
        final n = _enviar(fd, buffer + enviados, bytes.length - enviados, 0);
        if (n <= 0) return;
        enviados += n;
      }
    } finally {
      calloc.free(buffer);
    }
  }

  /// Lê um pedaço; `null` quando a conexão caiu, lista vazia no fim do fluxo.
  ///
  /// Copia os bytes: `asTypedList` é uma *view* da memória do `calloc`, e ela
  /// é liberada no `finally` — devolver a view daria leitura de memória
  /// liberada para quem chama.
  List<int>? ler(int fd) {
    final buffer = calloc<Uint8>(4096);
    try {
      final n = _ler(fd, buffer, 4096, 0);
      if (n < 0) return null;
      if (n == 0) return const <int>[];
      return List<int>.of(buffer.asTypedList(n));
    } finally {
      calloc.free(buffer);
    }
  }

  void fechar(int fd) => _fechar(fd);
}

/// `sockaddr_un` = família (2 bytes) + caminho + NUL. Little-endian (x86_64 e
/// arm64 do Raspberry Pi).
int _tamanhoEndereco(String caminho) => 2 + utf8.encode(caminho).length + 1;
