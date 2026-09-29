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
  'totalPassos': 6,
};

Map<String, Object?> kAgenda({List<Map<String, Object?>> ocorrencias = const []}) => {
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
}) =>
    {
      'v': 1,
      'type': 'estado',
      'ts': '2026-09-29T08:00:00',
      'chave': chave,
      'mensagem': mensagem,
      'totalPassos': 6,
      'esperaBotao': esperaBotao,
      'fluxo': fluxo,
      'fase': ?fase,
      'passo': ?passo,
      'slot': ?slot,
      if (proxima.isNotEmpty) 'proxima': proxima,
    };

/// Monta cliente + controlador prontos para o roteiro.
({ClienteCoreFake cliente, ControladorUI controlador}) _ligado() {
  final memoria = CanalMemoria();
  final cliente = ClienteCoreFake(memoria)..iniciar();
  final controlador = ControladorUI(
    cliente,
    relogio: () => DateTime(2026, 9, 29, 8, 30),
  )..iniciar();
  return (cliente: cliente, controlador: controlador);
}

void main() {
  group('modelo', () {
    test('lê o retrato de rótulos e agenda', () {
      final rotulos = MensagemCore.deJson(kRotulos);
      expect(rotulos, isA<Rotulos>());
      expect((rotulos as Rotulos).totalPassos, 6);
      expect(rotulos.preenchido('pressione_ok', const {}), 'Pressione OK');
      expect(
        rotulos.preenchido('passo', {'atual': 2, 'total': 6}),
        'Passo 2 de 6',
      );

      final agenda = MensagemCore.deJson(kAgenda(ocorrencias: [
        {
          'id': 'occ-1',
          'medicamento': 'Losartana 50 mg',
          'dosagem': '1 comprimido',
          'slot': 3,
          'horario': '08:00',
          'estado': 'ALARME',
        }
      ]));
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

    test('tela sem esperaBotao não habilita o botão', () {
      final tela = MensagemCore.deJson(
        kTela(chave: 'abra_gaveta', mensagem: 'Abra a gaveta', passo: 2),
      ) as Tela;
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
      cliente.receberMensagem(kTela(
        chave: 'hora_remedio',
        mensagem: 'Hora do remédio: Losartana (1 comprimido)',
        fase: 'ALARME',
        passo: 1,
        esperaBotao: true,
      ));
      await pumpEventQueue();
      expect(eventos.first, isA<ConexaoMudou>());
      final recebida = eventos.whereType<MensagemRecebida>().single.mensagem;
      expect((recebida as Tela).chave, 'hora_remedio');
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
      l.cliente.receberMensagem(kAgenda(ocorrencias: [
        {
          'id': 'occ-1',
          'medicamento': 'Losartana 50 mg',
          'dosagem': '1 comprimido',
          'slot': 3,
          'horario': '14:00',
          'estado': 'AGUARDANDO',
        }
      ]));
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
      l.cliente.receberMensagem(kTela(
        chave: 'hora_remedio',
        mensagem: 'Hora do remédio: Losartana 50 mg (1 comprimido)',
        fase: 'ALARME',
        passo: 1,
        esperaBotao: true,
      ));
      await pumpEventQueue();
      final estado = l.controlador.estado as EstadoDose;
      expect(estado.tela.mensagem, 'Hora do remédio: Losartana 50 mg (1 comprimido)');
      expect(estado.tela.passo, 1);
      expect(l.controlador.podeConfirmar, isTrue);
      await l.cliente.dispose();
    });

    test('tela de aviso não para o fluxo da dose', () async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(kTela(
        chave: 'hora_remedio',
        mensagem: 'Hora do remédio: Losartana 50 mg (1 comprimido)',
        fase: 'ALARME',
        passo: 1,
        esperaBotao: true,
      ));
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
      expect(estado.tela.chave, 'hora_remedio'); // a dose continua na tela
      await l.cliente.dispose();
    });

    test('perder o core limpa a tela (não mostra passo antigo)', () async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(kTela(
        chave: 'tome_e_ok',
        mensagem: 'Tome o medicamento e pressione OK',
        fase: 'MEDICAMENTO_RETIRADO',
        passo: 4,
        esperaBotao: true,
      ));
      await pumpEventQueue();
      expect(l.controlador.estado, isA<EstadoDose>());
      l.cliente.memoria.cair();
      await pumpEventQueue();
      expect(l.controlador.estado, isA<EstadoSemCore>());
      expect(l.controlador.podeConfirmar, isFalse);
      await l.cliente.dispose();
    });
  });

  group('widgets', () {
    testWidgets('tela de repouso mostra hora e próxima dose', (tester) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda(ocorrencias: [
        {
          'id': 'occ-1',
          'medicamento': 'Losartana 50 mg',
          'dosagem': '1 comprimido',
          'slot': 3,
          'horario': '14:00',
          'estado': 'AGUARDANDO',
        }
      ]));
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

    testWidgets('fluxo da dose mostra passo, frase e botão OK', (tester) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(kTela(
        chave: 'hora_remedio',
        mensagem: 'Hora do remédio: Losartana 50 mg (1 comprimido)',
        fase: 'ALARME',
        passo: 1,
        esperaBotao: true,
      ));
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.text('Passo 1 de 6'), findsOneWidget);
      expect(find.text('Hora do remédio: Losartana 50 mg (1 comprimido)'), findsOneWidget);
      expect(find.text('Pressione OK'), findsOneWidget);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('sem botão quando o core não pede OK', (tester) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(kTela(
        chave: 'retire_medicamento',
        mensagem: 'Retire o medicamento do slot 3',
        fase: 'GAVETA_ABERTA',
        passo: 3,
        slot: 3,
      ));
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.text('Passo 3 de 6'), findsOneWidget);
      expect(find.text('Pressione OK'), findsNothing);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('botão OK devolve apenas a intenção', (tester) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(kTela(
        chave: 'tome_e_ok',
        mensagem: 'Tome o medicamento e pressione OK',
        fase: 'MEDICAMENTO_RETIRADO',
        passo: 4,
        esperaBotao: true,
      ));
      await tester.pump();

      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();
      await tester.tap(find.text('Pressione OK'));
      await tester.pump();

      expect(jsonDecode(l.cliente.memoria.enviados.single), {
        'v': 1,
        'type': 'input',
        'acao': 'confirma',
      });
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('sem conexão avisa e não mostra botão', (tester) async {
      final l = _ligado();
      await tester.pumpWidget(DispenserApp(controlador: l.controlador));
      await tester.pump();

      expect(find.text('Sem conexão com o dispensador'), findsWidgets);
      expect(find.text('Pressione OK'), findsNothing);
      expect(find.byIcon(Icons.wifi_off), findsOneWidget);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });

    testWidgets('aviso do core aparece como faixa, sem cobrir a dose',
        (tester) async {
      final l = _ligado();
      l.cliente.receberMensagem(kRotulos);
      l.cliente.receberMensagem(kAgenda());
      l.cliente.receberMensagem(kRepouso());
      l.cliente.receberMensagem(kTela(
        chave: 'devolva_slot',
        mensagem: 'Devolva ao slot 3 e feche a gaveta',
        fase: 'AGUARDANDO_RETORNO',
        passo: 5,
        slot: 3,
      ));
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
      expect(find.text('Falha F003 no sensor. Avise o cuidador.'), findsOneWidget);
      l.controlador.dispose();
      await encerrar(tester, l.cliente);
    });
  });
}
