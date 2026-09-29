/// Telas do LCD. Todas exibem o que o core renderizou; nenhuma delas decide
/// o estado da dose.
library;

import 'package:flutter/material.dart';

import 'controlador.dart';
import 'modelo.dart';
import 'tema.dart';

/// Formata horas/datas em pt-BR (a UI não traduz texto de domínio, só relógio).
String hora(DateTime momento) =>
    '${momento.hour.toString().padLeft(2, '0')}:${momento.minute.toString().padLeft(2, '0')}';

/// Rótulo de um passo, no formato do core ("Passo 2 de 6").
String rotuloPasso(Rotulos rotulos, int atual, int total) =>
    rotulos.preenchido('passo', {'atual': atual, 'total': total});

/// Tela principal: escolhe o estado e desenha.
class TelaDispensador extends StatelessWidget {
  const TelaDispensador({super.key, required this.controlador});

  final ControladorUI controlador;

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: controlador,
      builder: (context, _) => Scaffold(
        body: switch (controlador.estado) {
          EstadoSemCore(:final momento, :final rotulos, :final erro) => TelaSemCore(
            momento: momento,
            rotulos: rotulos,
            erro: erro,
          ),
          EstadoIniciando(:final momento, :final rotulos) => TelaIniciando(
            momento: momento,
            rotulos: rotulos,
          ),
          EstadoRepouso(
            :final momento,
            :final rotulos,
            :final agenda,
            :final aviso,
          ) => TelaRepouso(
            momento: momento,
            rotulos: rotulos,
            agenda: agenda,
            aviso: aviso,
          ),
          EstadoDose(:final momento, :final rotulos, :final tela, :final aviso) => TelaDose(
            momento: momento,
            rotulos: rotulos,
            tela: tela,
            aviso: aviso,
            aoConfirmar: controlador.confirmar,
          ),
        },
      ),
    );
  }
}

/// Sem core: nada é afirmado sobre a dose, só o que fazer.
class TelaSemCore extends StatelessWidget {
  const TelaSemCore({
    super.key,
    required this.momento,
    required this.rotulos,
    this.erro,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final Object? erro;

  @override
  Widget build(BuildContext context) {
    return _Moldura(
      momento: momento,
      rotulos: rotulos,
      conectado: false,
      filho: _Encolhe(
        Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.link_off, size: 96, color: Cores.alerta),
            const SizedBox(height: 24),
            Text(
              rotulos.preenchido('sem_conexao', const {}),
              style: const TextStyle(fontSize: 44, fontWeight: FontWeight.bold),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            Text(
              rotulos.preenchido('sem_core_orientacao', const {}),
              style: const TextStyle(fontSize: 26, color: Cores.textoFraco),
              textAlign: TextAlign.center,
            ),
            if (erro != null) ...[
              const SizedBox(height: 16),
              Text(
                '$erro',
                style: const TextStyle(fontSize: 20, color: Cores.textoFraco),
                textAlign: TextAlign.center,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Core conectado, retrato ainda a caminho.
class TelaIniciando extends StatelessWidget {
  const TelaIniciando({super.key, required this.momento, required this.rotulos});

  final DateTime momento;
  final Rotulos rotulos;

  @override
  Widget build(BuildContext context) {
    return _Moldura(
      momento: momento,
      rotulos: rotulos,
      conectado: true,
      filho: _Encolhe(
        Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const CircularProgressIndicator(color: Cores.destaque, strokeWidth: 8),
            const SizedBox(height: 24),
            Text(
              rotulos.preenchido('conectando', const {}),
              style: const TextStyle(fontSize: 40, fontWeight: FontWeight.bold),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

/// Repouso: hora, próxima dose e indicadores de conexão/falha.
class TelaRepouso extends StatelessWidget {
  const TelaRepouso({
    super.key,
    required this.momento,
    required this.rotulos,
    required this.agenda,
    this.aviso,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final Agenda agenda;
  final Aviso? aviso;

  @override
  Widget build(BuildContext context) {
    final proxima = agenda.emAberto ?? agenda.primeira;
    return _Moldura(
      momento: momento,
      rotulos: rotulos,
      conectado: true,
      filho: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Spacer(),
          // a hora fica no cabeçalho da moldura: aqui só a próxima dose
          _Encolhe(
            Text(
              proxima == null
                  ? rotulos.preenchido('sem_dose_hoje', const {})
                  : '${rotulos.preenchido('proxima_dose', const {})} — '
                      '${proxima.horario} · ${proxima.medicamento}',
              style: const TextStyle(fontSize: 36, fontWeight: FontWeight.w600),
            ),
          ),
          const Spacer(),
          if (aviso != null) FaixaAviso(aviso: aviso!),
        ],
      ),
    );
  }
}

/// Fluxo da dose: uma instrução por tela, com o número do passo.
class TelaDose extends StatelessWidget {
  const TelaDose({
    super.key,
    required this.momento,
    required this.rotulos,
    required this.tela,
    required this.aoConfirmar,
    this.aviso,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final Tela tela;
  final VoidCallback aoConfirmar;
  final Aviso? aviso;

  @override
  Widget build(BuildContext context) {
    final passo = tela.passo;
    return _Moldura(
      momento: momento,
      rotulos: rotulos,
      conectado: true,
      alarme: true,
      filho: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (passo != null) ...[
            Text(
              rotuloPasso(rotulos, passo, tela.totalPassos),
              style: const TextStyle(fontSize: 34, color: Cores.destaque, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 20),
            BarraPassos(atual: passo, total: tela.totalPassos),
            const SizedBox(height: 36),
          ],
          Expanded(
            child: Center(
              child: _Encolhe(
                Text(
                  tela.mensagem,
                  style: const TextStyle(fontSize: 52, fontWeight: FontWeight.bold, height: 1.15),
                  textAlign: TextAlign.center,
                ),
              ),
            ),
          ),
          if (tela.proxima.isNotEmpty) ...[
            Text(
              tela.proxima,
              style: const TextStyle(fontSize: 30, color: Cores.textoFraco),
            ),
            const SizedBox(height: 24),
          ],
          if (aviso != null) FaixaAviso(aviso: aviso!),
          if (tela.esperaBotao) ...[
            const SizedBox(height: 16),
            BotaoOk(rotulos: rotulos, aoConfirmar: aoConfirmar),
          ],
        ],
      ),
    );
  }
}

/// Moldura comum: cabeçalho com hora, título e indicadores.
class _Moldura extends StatelessWidget {
  const _Moldura({
    required this.momento,
    required this.rotulos,
    required this.conectado,
    required this.filho,
    this.alarme = false,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final bool conectado;
  final bool alarme;
  final Widget filho;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(40),
      decoration: BoxDecoration(
        color: alarme ? Cores.painel : Cores.fundo,
        border: Border.all(
          color: alarme ? Cores.destaque : Colors.transparent,
          width: 6,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Flexible(
                child: Text(
                  rotulos.preenchido('dispensador', const {}),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 26, color: Cores.textoFraco),
                ),
              ),
              const SizedBox(width: 12),
              IconeConexao(conectado: conectado),
              const SizedBox(width: 12),
              Text(
                hora(momento),
                style: const TextStyle(fontSize: 32, fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const SizedBox(height: 24),
          Expanded(child: filho),
        ],
      ),
    );
  }
}

/// Encolhe o conteúdo para caber na tela em vez de estourar.
///
/// O LCD real tem resolução indefinida até a Fase 4; encolher é melhor do que
/// cortar a frase do paciente.
class _Encolhe extends StatelessWidget {
  const _Encolhe(this.filho);

  final Widget filho;

  @override
  Widget build(BuildContext context) {
    return FittedBox(fit: BoxFit.scaleDown, child: filho);
  }
}

/// Indicador de conexão (spec 05 pede o indicador no repouso).
class IconeConexao extends StatelessWidget {
  const IconeConexao({super.key, required this.conectado});

  final bool conectado;

  @override
  Widget build(BuildContext context) {
    return Icon(
      conectado ? Icons.wifi : Icons.wifi_off,
      color: conectado ? Cores.ok : Cores.alerta,
      size: 34,
      semanticLabel: conectado ? 'conectado' : 'sem conexão',
    );
  }
}

/// Barra de progresso do fluxo (um bloco por passo).
class BarraPassos extends StatelessWidget {
  const BarraPassos({super.key, required this.atual, required this.total});

  final int atual;
  final int total;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: List.generate(total, (i) {
        final feito = i < atual;
        return Expanded(
          child: Container(
            height: 16,
            margin: EdgeInsets.only(right: i == total - 1 ? 0 : 8),
            decoration: BoxDecoration(
              color: feito ? Cores.destaque : Cores.textoFraco.withValues(alpha: 0.3),
              borderRadius: BorderRadius.circular(8),
            ),
          ),
        );
      }),
    );
  }
}

/// Botão OK do paciente. Só aparece quando o core pede (`esperaBotao`).
class BotaoOk extends StatelessWidget {
  const BotaoOk({super.key, required this.rotulos, required this.aoConfirmar});

  final Rotulos rotulos;
  final VoidCallback aoConfirmar;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 130,
      child: FilledButton(
        onPressed: aoConfirmar,
        style: FilledButton.styleFrom(
          backgroundColor: Cores.ok,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
        ),
        child: Text(
          rotulos.preenchido('pressione_ok', const {}),
          style: const TextStyle(fontSize: 46, fontWeight: FontWeight.bold),
        ),
      ),
    );
  }
}

/// Faixa de aviso: não bloqueia a tela, mas fica visível.
class FaixaAviso extends StatelessWidget {
  const FaixaAviso({super.key, required this.aviso});

  final Aviso aviso;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(top: 16),
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 18),
      decoration: BoxDecoration(
        color: Cores.alerta.withValues(alpha: 0.18),
        border: Border.all(color: Cores.alerta, width: 3),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded, color: Cores.alerta, size: 40),
          const SizedBox(width: 16),
          Expanded(
            child: Text(
              aviso.mensagem,
              style: const TextStyle(fontSize: 30, color: Cores.texto, fontWeight: FontWeight.w600),
            ),
          ),
          Text(
            aviso.codigo,
            style: const TextStyle(fontSize: 26, color: Cores.alerta, fontWeight: FontWeight.bold),
          ),
        ],
      ),
    );
  }
}
