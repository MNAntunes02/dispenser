/// Testes da UI do LCD: modelo das mensagens, controlador e telas.
///
/// Tudo roda sobre [CanalMemoria] — nenhum socket, nenhum hardware. O roteiro
/// reproduz o que o core publica de verdade (mesmos campos de
/// `core/protocolo_ui.py`).
library;

import 'dart:convert';

import 'package:dispenser_ui/main.dart';
import 'package:dispenser_ui/src/cliente_core.dart';
import 'package:dispenser_ui/src/controlador.dart';
import 'package:dispenser_ui/src/modelo.dart';
import 'package:dispenser_ui/src/rotulos.dart';
import 'package:dispenser_ui/src/telas.dart';
import 'package:dispenser_ui/src/visao.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Encerra o cliente dentro de `testWidgets`.
///
/// `Subscription.cancel()` só completa fora do zone de fake-async; sem o
/// `runAsync` o teste trava esperando o future.
Future<void> encerrar(WidgetTester tester, ClienteCoreFake cliente) =>
    tester.runAsync(() => cliente.dispose());

/// Filtra um stream por subtype (`Stream` não tem `whereType`).
extension FiltroEvento on Stream<Object?> {
  Stream<T> apenas<T>() => where((e) => e is T).cast<T>();
}

/// Rótulos exatamente como o core manda no retrato.
const Map<String, Object?> kRotulos = {
  'v': 1,
  'type': 'rotulos',
  'ts': '2026-09-29T08:00:00',
  'rotulos': kRotulosPadrao,
  'totalPassos': 4,
};

Map<String, Object?> kAgenda({
  List<Map<String, Object?>> ocorrencias = const [],
}) => {
  'v': 1,
  'type': 'agenda',
  'ts': '2026-09-29T08:00:00',
  'dia': '2026-09-29',
  'ocorrencias': ocorrencias,
};

/// Tela de repouso que o core publica quando não há dose em aberto.
Map<String, Object?> kRepouso({String proxima = '14:00'}) => kTela(
  chave: proxima.isEmpty ? 'reposo_sem_dose' : 'reposo',
  mensagem: proxima.isEmpty
      ? 'Nenhuma dose programada para hoje'
      : 'Tudo em dia. Próxima dose às $proxima',
  fluxo: 'reposo',
  proxima: proxima,
);

Map<String, Object?> kTela({
  required String chave,
  required String mensagem,
  String? fase,
  int? passo,
  int? slot,
  bool esperaBotao = false,
  String fluxo = 'dose',
  String proxima = '',
  String registroId = '',
  int? quantidade,
}) => {
  'v': 1,
  'type': 'estado',
  'ts': '2026-09-29T08:00:00',
  'chave': chave,
  'mensagem': mensagem,
  'totalPassos': 4,
  'esperaBotao': esperaBotao,
  'fluxo': fluxo,
  'fase': ?fase,
  'passo': ?passo,
  'slot': ?slot,
  if (proxima.isNotEmpty) 'proxima': proxima,
  if (registroId.isNotEmpty) 'registroId': registroId,
  'quantidade': ?quantidade,
};

/// Estoque dos 12 slots como o core publica (slot 12 com 7 comprimidos).
Map<String, Object?> kEstoque() => {
  'v': 1,
  'type': 'estoque',
  'ts': '2026-09-29T08:00:00',
  'itens': [
    for (var i = 0; i < 12; i++)
      {
        'slot': i + 1,
        'rotulo': 'Slot ${i + 1}',
        'linha': i ~/ 2,
        'coluna': i.isEven ? 'esquerda' : 'direita',
        'medicamento': i == 11 ? 'Losartana' : '',
        'quantidade': i == 11 ? 7 : 0,
        'vazio': i != 11,
      },
  ],
};

/// PNG 1×1 válido: o `Image.memory` do preview precisa de bytes decodificáveis.
const String kPng1x1 =
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

/// Monta cliente + controlador prontos para o roteiro.
({ClienteCoreFake cliente, ControladorUI controlador}) _ligado({
  DetectorConsumo? detector,
  DateTime Function()? relogio,
  Duration limiteSemTela = const Duration(seconds: 5),
  Duration intervaloVigia = const Duration(seconds: 1),
}) {
  final memoria = CanalMemoria();
  final cliente = ClienteCoreFake(memoria)..iniciar();
  final controlador = ControladorUI(
    cliente,
    relogio: relogio ?? () => DateTime(2026, 9, 29, 8, 30),
    detector: detector,
    limiteSemTela: limiteSemTela,
    intervaloVigia: intervaloVigia,
  )..iniciar();
  return (cliente: cliente, controlador: controlador);
}

void main() {
  group('modelo', () {
    test('lê o retrato de rótulos e agenda', () {
      final rotulos = MensagemCore.deJson(kRotulos);
      expect(rotulos, isA<Rotulos>());
      expect((rotulos as Rotulos).totalPassos, 4);
      expect(rotulos.preenchido('pressione_ok', const {}), 'Pressione OK');
      expect(
        rotulos.preenchido('passo', {'atual': 2, 'total': 4}),
        'Passo 2 de 4',
      );

      final agenda = MensagemCore.deJson(
        kAgenda(
          ocorrencias: [
            {
              'id': 'occ-1',
              'medicamento': 'Losartana 50 mg',
              'dosagem': '1 comprimido',
              'slot': 3,
              'horario': '08:00',
              'estado': 'ALARME',
            },
          ],
        ),
      );
      expect((agenda as Agenda).ocorrencias.single.slot, 3);
      expect(agenda.emAberto!.medicamento, 'Losartana 50 mg');
    });

    test('rejeita versão e tipo fora do contrato', () {
      expect(
        () => MensagemCore.deJson({'v': 2, 'type': 'health'}),
        throwsA(isA<MensagemInvalida>()),
      );
      expect(
        () => MensagemCore.deJson({'v': 1, 'type': 'doses'}),
        throwsA(isA<MensagemInvalida>()),
      );
    });

    test('lê o estoque e os campos do registro', () {
      final estoque = MensagemCore.deJson(kEstoque()) as Estoque;
      expect(estoque.itens, hasLength(12));
      expect(estoque.itens.last.slot, 12);
      expect(estoque.itens.last.quantidade, 7);
      expect(estoque.itens.first.coluna, 'esquerda');
      expect(estoque.itens[1].coluna, 'direita');

      final tela = MensagemCore.deJson(
        kTela(
          chave: 'registro_slot',
          mensagem: 'Cartela com 7 comprimidos. Coloque no slot 12.',
          fluxo: 'registro',
          registroId: 'abc123',
          quantidade: 7,
        ),
      ) as Tela;
      expect(tela.registroId, 'abc123');
      expect(tela.quantidade, 7);
      expect(tela.doseEmAberto, isFalse);
    });

    test('tela sem esperaBotao não habilita o botão', () {
      final tela =
          MensagemCore.deJson(
                kTela(
                  chave: 'abra_gaveta',
                  mensagem: 'Abra a gaveta',
                  passo: 1,
                ),
              )
              as Tela;
      expect(tela.esperaBotao, isFalse);
      expect(tela.emFluxo, isTrue);
      expect(tela.doseEmAberto, isTrue);
    });
  });

  group('cliente', () {
    test('traduz linha JSON em evento de mensagem', () async {
      final cliente = ClienteCoreFake(CanalMemoria())..iniciar();
      final eventos = <EventoCore>[];
      cliente.eventos.listen(eventos.add);
      cliente.receberMensagem(
        kTela(
          chave: 'abra_gaveta',
          mensagem: 'Abra a gaveta',
          fase: 'ALARME',
          passo: 1,
        ),
      );
      await pumpEventQueue();
      expect(eventos.first, isA<ConexaoMudou>());
      final recebida = eventos.whereType<MensagemRecebida>().single.mensagem;
      expect((recebida as Tela).chave, 'abra_gaveta');
      await cliente.dispose();
    });

    test('confirmar envia só a ação aprovada (sem soneca)', () async {
      final memoria = CanalMemoria();
      final cliente = ClienteCoreFake(memoria)..iniciar();
      cliente.confirmar();
      expect(memoria.enviados, ['{"v":1,"type":"input","acao":"confirma"}']);
      await cliente.dispose();
    });

    test('linha inválida não derruba o cliente', () async {
      final cliente = ClienteCoreFake(CanalMemoria())..iniciar();
      final invalidas = <LinhaInvalida>[];
      cliente.eventos.apenas<LinhaInvalida>().listen(invalidas.add);
      cliente.receberLinha('isso não é json');
      await pumpEventQueue();
      expect(invalidas, hasLength(1));
      // a conexão continua: o core reenvia o retrato quando puder
      expect(cliente.conectado, isTrue);
      await cliente.dispose();
    });

    test('queda do socket avisa desconexão', () async {
      final memoria = CanalMemoria();
      final cliente = ClienteCoreFake(memoria)..iniciar();
      final mudancas = <ConexaoMudou>[];
      cliente.eventos.apenas<ConexaoMudou>().listen(mudancas.add);
      memoria.cair();
      await pumpEventQueue();
      expect(mudancas.last.conectado, isFalse);
      expect(cliente.conectado, isFalse);
      await cliente.dispose();
    });
  });

  group('controlador', () {
    test('sem conexão mostra a tela de core fora do ar', () async {
      final l = _ligado();
      expect(l.controlador.estado, isA<EstadoSemCore>());
      expect(l.controlador.podeConfirmar, isFalse);
      await l.cliente.dispose();
    });

    test('retrato do core leva do "sem core" ao repouso', () async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(
        kAgenda(
          ocorrencias: [
            {
              'id': 'occ-1',
              'medicamento': 'Losartana 50 mg',
              'dosagem': '1 comprimido',
              'slot': 3,
              'horario': '14:00',
              'estado': 'AGUARDANDO',
            },
          ],
        ),
      );
      l.cliente.receberMensagem(kRepouso());
      await pumpEventQueue();
      final estado = l.controlador.estado as EstadoRepouso;
      expect(estado.proxima!.horario, '14:00');
      await l.cliente.dispose();
    });

    test('fluxo da dose só aparece com a tela do core', () async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'abra_gaveta',
          mensagem: 'Abra a gaveta',
          fase: 'ALARME',
          passo: 1,
        ),
      );
      await pumpEventQueue();
      final estado = l.controlador.estado as EstadoDose;
      expect(estado.tela.mensagem, 'Abra a gaveta');
      expect(estado.tela.passo, 1);
      expect(l.controlador.podeConfirmar, isFalse);
      await l.cliente.dispose();
    });

    test('tela de aviso não para o fluxo da dose', () async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'abra_gaveta',
          mensagem: 'Abra a gaveta',
          fase: 'ALARME',
          passo: 1,
        ),
      );
      await pumpEventQueue();
      l.cliente.receberMensagem({
        'v': 1,
        'type': 'alerta',
        'ts': '2026-09-29T08:05:00',
        'codigo': 'F003',
        'mensagem': 'Falha F003 no sensor. Avise o cuidador.',
      });
      await pumpEventQueue();
      final estado = l.controlador.estado as EstadoDose;
      expect(estado.aviso!.codigo, 'F003');
      expect(estado.tela.chave, 'abra_gaveta'); // a dose continua na tela
      await l.cliente.dispose();
    });

    test('perder o core limpa a tela (não mostra passo antigo)', () async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'consuma_e_detectar',
          mensagem: 'Consuma o medicamento e coloque a cartela na posição de detecção',
          fase: 'AGUARDANDO_DETECCAO',
          passo: 2,
        ),
      );
      await pumpEventQueue();
      expect(l.controlador.estado, isA<EstadoDose>());
      l.cliente.memoria.cair();
      await pumpEventQueue();
      expect(l.controlador.estado, isA<EstadoSemCore>());
      expect(l.controlador.podeConfirmar, isFalse);
      await l.cliente.dispose();
    });

    test(
      'conectado sem tela reconecta e volta ao normal com o retrato',
      () async {
        final l = _ligado(
          relogio: DateTime.now,
          limiteSemTela: const Duration(milliseconds: 20),
          intervaloVigia: const Duration(milliseconds: 10),
        );
        l.cliente.receberMensagem({
          'v': 1,
          'type': 'health',
          'ts': '2026-09-29T08:00:00',
        });
        await Future<void>.delayed(const Duration(milliseconds: 60));
        expect(l.cliente.memoria.reconexoes, greaterThanOrEqualTo(1));

        l.cliente.receberMensagem(kRotulos);
        l.cliente.receberMensagem(kAgenda());
        l.cliente.receberMensagem(kRepouso());
        await pumpEventQueue();
        expect(l.controlador.estado, isA<EstadoRepouso>());
        expect(l.controlador.erroSemTela, isNull);
        l.controlador.dispose();
        await l.cliente.dispose();
      },
    );

    test('sem tela depois do limite avisa e para de reconectar', () async {
      final l = _ligado(
        relogio: DateTime.now,
        limiteSemTela: const Duration(milliseconds: 10),
        intervaloVigia: const Duration(milliseconds: 10),
      );
      l.cliente.receberMensagem({
        'v': 1,
        'type': 'health',
        'ts': '2026-09-29T08:00:00',
      });
      await Future<void>.delayed(const Duration(milliseconds: 120));
      expect(l.cliente.memoria.reconexoes, 2);
      expect(l.controlador.erroSemTela, isNotNull);
      expect((l.controlador.estado as EstadoIniciando).erro, isNotNull);
      l.controlador.dispose();
      await l.cliente.dispose();
    });

    test('passo 2 liga a visão; leitura estável não envia OK', () async {
      final detector = DetectorConsumoFake();
      final l = _ligado(detector: detector);
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'consuma_e_detectar',
          mensagem: 'Consuma o medicamento e coloque a cartela na posição de detecção',
          fase: 'AGUARDANDO_DETECCAO',
          passo: 2,
        ),
      );
      await pumpEventQueue();
      expect(detector.inicios, 1);
      expect(l.cliente.memoria.enviados, isEmpty);

      detector.confirmar();
      await pumpEventQueue();
      // A visão é só status: a liberação vem do painel/CLI.
      expect(l.cliente.memoria.enviados, isEmpty);
      expect((l.controlador.estado as EstadoDose).visaoEstavel, isTrue);

      detector.confirmar();
      await pumpEventQueue();
      expect(l.cliente.memoria.enviados, isEmpty);

      l.controlador.dispose();
      await l.cliente.dispose();
    });

    test(
      'sair do passo 2 desliga a visão (leitura fora é ignorada)',
      () async {
        final detector = DetectorConsumoFake();
        final l = _ligado(detector: detector);
        l.cliente.receberMensagem(kRotulos);
        l.cliente.receberMensagem(kAgenda());
        l.cliente.receberMensagem(kRepouso());
        l.cliente.receberMensagem(
          kTela(
            chave: 'consuma_e_detectar',
            mensagem: 'Consuma o medicamento e coloque a cartela na posição de detecção',
            fase: 'AGUARDANDO_DETECCAO',
            passo: 2,
          ),
        );
        await pumpEventQueue();
        expect(detector.inicios, 1);

        l.cliente.receberMensagem(
          kTela(
            chave: 'devolva_slot',
            mensagem: 'Devolva ao slot 3 e feche a gaveta',
            fase: 'AGUARDANDO_RETORNO',
            passo: 3,
            slot: 3,
          ),
        );
        await pumpEventQueue();
        expect(detector.paradas, 1);

        detector.confirmar();
        await pumpEventQueue();
        expect(l.cliente.memoria.enviados, isEmpty);

        l.controlador.dispose();
        await l.cliente.dispose();
      },
    );

    test('registro liga a câmera e envia só a leitura estável', () async {
      final detector = DetectorConsumoFake();
      final l = _ligado(detector: detector);
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(
        kTela(
          chave: 'registro_posicionar',
          mensagem: 'Posicione a cartela na área de detecção',
          fluxo: 'registro',
          registroId: 'abc123',
        ),
      );
      await pumpEventQueue();

      expect(detector.inicios, 1);
      expect(l.controlador.estado, isA<EstadoRegistro>());
      expect(l.cliente.memoria.enviados, isEmpty);

      detector.emitirLeitura(const Leitura(0, 3));
      await pumpEventQueue();
      expect(l.cliente.memoria.enviados, isEmpty);
      expect(
        (l.controlador.estado as EstadoRegistro).visaoSemComprimidos,
        isTrue,
      );

      detector.emitirLeitura(const Leitura(7, 0));
      detector.emitirLeitura(const Leitura(7, 0));
      await pumpEventQueue();

      expect(l.cliente.memoria.enviados, hasLength(1));
      expect(l.cliente.memoria.enviados.single, contains('"cmd":"registrar_leitura"'));
      expect(l.cliente.memoria.enviados.single, contains('"quantidade":7'));

      l.cliente.receberMensagem(
        kTela(
          chave: 'registro_slot',
          mensagem: 'Cartela com 7 comprimidos. Coloque no slot 12.',
          fluxo: 'registro',
          slot: 12,
        ),
      );
      await pumpEventQueue();
      expect(detector.paradas, 1);
      expect((l.controlador.estado as EstadoRegistro).tela.slot, 12);

      l.controlador.dispose();
      await l.cliente.dispose();
    });

    test('sem detector (nulo) nada é confirmado sozinho', () async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'consuma_e_detectar',
          mensagem: 'Consuma o medicamento e coloque a cartela na posição de detecção',
          fase: 'AGUARDANDO_DETECCAO',
          passo: 2,
        ),
      );
      await pumpEventQueue();
      expect(l.cliente.memoria.enviados, isEmpty);
      expect(l.controlador.podeConfirmar, isFalse);
      l.controlador.dispose();
      await l.cliente.dispose();
    });
  });

  group('widgets', () {
    testWidgets('tela de repouso mostra hora e próxima dose', (tester) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(
        kAgenda(
          ocorrencias: [
            {
              'id': 'occ-1',
              'medicamento': 'Losartana 50 mg',
              'dosagem': '1 comprimido',
              'slot': 3,
              'horario': '14:00',
              'estado': 'AGUARDANDO',
            },
          ],
        ),
      );
      l.cliente.receberMensagem(kRepouso());
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.text('08:30'), findsOneWidget);
      expect(find.textContaining('14:00'), findsOneWidget);
      expect(find.textContaining('Losartana'), findsOneWidget);
      expect(find.byIcon(Icons.wifi), findsOneWidget);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('fluxo da dose mostra passo e frase, sem botão OK', (
      tester,
    ) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'abra_gaveta',
          mensagem: 'Abra a gaveta',
          fase: 'ALARME',
          passo: 1,
        ),
      );
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.text('Passo 1 de 4'), findsOneWidget);
      expect(find.text('Abra a gaveta'), findsOneWidget);
      expect(find.text('Pressione OK'), findsNothing);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('passo de detecção não mostra botão OK', (tester) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'consuma_e_detectar',
          mensagem:
              'Consuma o medicamento e coloque a cartela na posição de detecção',
          fase: 'AGUARDANDO_DETECCAO',
          passo: 2,
        ),
      );
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.text('Passo 2 de 4'), findsOneWidget);
      expect(find.text('Pressione OK'), findsNothing);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('passo 2 mostra o preview e o status de leitura estável', (
      tester,
    ) async {
      final detector = DetectorConsumoFake();
      final l = _ligado(detector: detector);
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'consuma_e_detectar',
          mensagem:
              'Consuma o medicamento e coloque a cartela na posição de detecção',
          fase: 'AGUARDANDO_DETECCAO',
          passo: 2,
        ),
      );
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      // Antes do primeiro frame: marcador de câmera, sem inventar instrução.
      expect(find.byType(Image), findsNothing);
      expect(find.byIcon(Icons.photo_camera_outlined), findsOneWidget);
      expect(find.text('Pressione OK'), findsNothing);
      expect(find.textContaining('Preparando câmera'), findsOneWidget);

      detector.emitirAviso('câmera falhou');
      await tester.pump();
      expect(find.textContaining('Câmera: câmera falhou'), findsOneWidget);

      detector.emitirQuadro(base64Decode(kPng1x1));
      await tester.pump();
      await tester.pump();

      expect(find.byType(Image), findsOneWidget);
      expect(find.textContaining('Aponte a cartela'), findsOneWidget);

      detector.confirmar();
      await tester.pump();
      expect(
        find.text('Leitura estável — aguardando liberação no painel'),
        findsOneWidget,
      );
      expect(l.cliente.memoria.enviados, isEmpty);

      // Ao sair do passo 2 o preview some junto com a câmera.
      l.cliente.receberMensagem(
        kTela(
          chave: 'devolva_slot',
          mensagem: 'Coloque de volta no slot 3',
          fase: 'AGUARDANDO_RETORNO',
          passo: 3,
          slot: 3,
        ),
      );
      await tester.pump();
      await tester.pump();

      expect(find.byType(Image), findsNothing);
      expect(find.byIcon(Icons.photo_camera_outlined), findsNothing);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('passo 2 sem câmera avisa que a liberação é no painel', (
      tester,
    ) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'consuma_e_detectar',
          mensagem:
              'Consuma o medicamento e coloque a cartela na posição de detecção',
          fase: 'AGUARDANDO_DETECCAO',
          passo: 2,
        ),
      );
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.textContaining('Câmera desativada'), findsOneWidget);
      expect(find.text('Pressione OK'), findsNothing);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('sem conexão avisa e não mostra botão', (tester) async {
      final l = _ligado();
      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.text('Sem conexão com o core'), findsWidgets);
      expect(find.text('Pressione OK'), findsNothing);
      expect(find.byIcon(Icons.wifi_off), findsOneWidget);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('conectando mostra o erro depois do limite de reconexões', (
      tester,
    ) async {
      var agora = DateTime(2026, 9, 29, 8, 30);
      final l = _ligado(
        relogio: () => agora,
        limiteSemTela: const Duration(seconds: 1),
        intervaloVigia: const Duration(seconds: 1),
      );
      l.cliente.receberMensagem({
        'v': 1,
        'type': 'health',
        'ts': '2026-09-29T08:00:00',
      });
      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      for (var i = 0; i < 5; i++) {
        agora = agora.add(const Duration(seconds: 1));
        await tester.pump(const Duration(seconds: 1));
      }

      expect(find.textContaining('Reinicie o core'), findsOneWidget);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('aviso do core aparece como faixa, sem cobrir a dose', (
      tester,
    ) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(
        kTela(
          chave: 'devolva_slot',
          mensagem: 'Devolva ao slot 3 e feche a gaveta',
          fase: 'AGUARDANDO_RETORNO',
          passo: 3,
          slot: 3,
        ),
      );
      l.cliente.receberMensagem({
        'v': 1,
        'type': 'alerta',
        'ts': '2026-09-29T08:05:00',
        'codigo': 'F003',
        'mensagem': 'Falha F003 no sensor. Avise o cuidador.',
      });
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.text('Devolva ao slot 3 e feche a gaveta'), findsOneWidget);
      // uma faixa só, com a mensagem do core e o código do sensor
      expect(find.byType(FaixaAviso), findsOneWidget);
      expect(
        find.text('Falha F003 no sensor. Avise o cuidador.'),
        findsOneWidget,
      );
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('repouso mostra os 12 slots em estoque', (tester) async {
      tester.view.physicalSize = const Size(1024, 600);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);

      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kEstoque());
      l.cliente.receberMensagem(kRepouso());
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.byType(GridEstoque), findsOneWidget);
      expect(find.text('Slot 1'), findsOneWidget);
      expect(find.text('Slot 12'), findsOneWidget);
      expect(find.text('Vazio'), findsNWidgets(11));
      expect(find.textContaining('Losartana · 7 comprimidos'), findsOneWidget);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('registro mostra a câmera e depois a dica do painel', (
      tester,
    ) async {
      final detector = DetectorConsumoFake();
      final l = _ligado(detector: detector);
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(
        kTela(
          chave: 'registro_posicionar',
          mensagem: 'Posicione a cartela na área de detecção',
          fluxo: 'registro',
          registroId: 'abc123',
        ),
      );
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.text('Posicione a cartela na área de detecção'), findsOneWidget);
      expect(find.byIcon(Icons.photo_camera_outlined), findsOneWidget);
      expect(find.textContaining('Preparando câmera'), findsOneWidget);

      detector.emitirQuadro(base64Decode(kPng1x1));
      await tester.pump();
      await tester.pump();
      expect(find.byType(Image), findsOneWidget);

      l.cliente.receberMensagem(
        kTela(
          chave: 'registro_slot',
          mensagem: 'Cartela com 7 comprimidos. Coloque no slot 12.',
          fluxo: 'registro',
          slot: 12,
        ),
      );
      await tester.pump();
      await tester.pump();

      expect(
        find.text('Cartela com 7 comprimidos. Coloque no slot 12.'),
        findsOneWidget,
      );
      expect(
        find.text('Confirme no painel após colocar a cartela'),
        findsOneWidget,
      );
      expect(find.byType(Image), findsNothing);
      expect(find.text('Pressione OK'), findsNothing);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });
  });
}
