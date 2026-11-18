/// Telas do LCD. Todas exibem o que o core renderizou; nenhuma delas decide
/// o estado da dose.
///
/// Tamanhos de texto vêm de [Tipografia], espaços de [Espaco], raios de
/// [Medidas] e cores de [Cores]: não escreva números ou cores soltos aqui.
library;

import 'dart:typed_data';

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
          EstadoSemCore(:final momento, :final rotulos, :final erro) =>
            TelaSemCore(momento: momento, rotulos: rotulos, erro: erro),
          EstadoIniciando(:final momento, :final rotulos, :final erro) =>
            TelaIniciando(momento: momento, rotulos: rotulos, erro: erro),
          EstadoRepouso(
            :final momento,
            :final rotulos,
            :final agenda,
            :final aviso,
          ) =>
            TelaRepouso(
              momento: momento,
              rotulos: rotulos,
              agenda: agenda,
              aviso: aviso,
            ),
          EstadoDose(
            :final momento,
            :final rotulos,
            :final tela,
            :final aviso,
            :final visaoAtiva,
            :final visaoEstavel,
            :final visaoAviso,
            :final visaoEspera,
          ) =>
            TelaDose(
              momento: momento,
              rotulos: rotulos,
              tela: tela,
              aviso: aviso,
              quadro: controlador.quadro,
              visaoAtiva: visaoAtiva,
              visaoEstavel: visaoEstavel,
              visaoAviso: visaoAviso,
              visaoEspera: visaoEspera,
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
            const _Emblema(icone: Icons.link_off, cor: Cores.alerta),
            const SizedBox(height: Espaco.xl),
            Text(
              rotulos.preenchido('sem_conexao', const {}),
              style: Tipografia.h3.copyWith(fontWeight: Tipografia.negrito),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: Espaco.m),
            Text(
              rotulos.preenchido('sem_core_orientacao', const {}),
              style: Tipografia.h6.copyWith(color: Cores.textoFraco),
              textAlign: TextAlign.center,
            ),
            if (erro != null) ...[
              const SizedBox(height: Espaco.l),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: Espaco.l,
                  vertical: Espaco.s,
                ),
                decoration: BoxDecoration(
                  color: Cores.painel,
                  border: Border.all(color: Cores.borda, width: 2),
                  borderRadius: BorderRadius.circular(Medidas.raioMedio),
                ),
                child: Text(
                  '$erro',
                  style: Tipografia.legenda.copyWith(color: Cores.textoSuave),
                  textAlign: TextAlign.center,
                ),
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
  const TelaIniciando({
    super.key,
    required this.momento,
    required this.rotulos,
    this.erro,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final String? erro;

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
            const SizedBox(
              width: 96,
              height: 96,
              child: CircularProgressIndicator(
                color: Cores.destaque,
                strokeWidth: 8,
                strokeCap: StrokeCap.round,
              ),
            ),
            const SizedBox(height: Espaco.xl),
            Text(
              rotulos.preenchido('conectando', const {}),
              style: Tipografia.h3.copyWith(fontWeight: Tipografia.negrito),
              textAlign: TextAlign.center,
            ),
            if (erro != null) ...[
              const SizedBox(height: Espaco.l),
              Text(
                erro!,
                style: Tipografia.legenda.copyWith(color: Cores.alerta),
                textAlign: TextAlign.center,
              ),
            ],
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
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: Center(
              child: proxima == null
                  ? _Encolhe(
                      Text(
                        rotulos.preenchido('sem_dose_hoje', const {}),
                        style: Tipografia.h3.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                        textAlign: TextAlign.center,
                      ),
                    )
                  : CartaoProximaDose(rotulos: rotulos, ocorrencia: proxima),
            ),
          ),
          if (aviso != null) FaixaAviso(aviso: aviso!),
        ],
      ),
    );
  }
}

/// Cartão do repouso: o horário da próxima dose em destaque e, ao lado, o que
/// tomar. Tudo em uma faixa só, lida de relance à distância.
class CartaoProximaDose extends StatelessWidget {
  const CartaoProximaDose({
    super.key,
    required this.rotulos,
    required this.ocorrencia,
  });

  final Rotulos rotulos;
  final Ocorrencia ocorrencia;

  @override
  Widget build(BuildContext context) {
    final detalhes = [
      if (ocorrencia.dosagem.isNotEmpty) ocorrencia.dosagem,
      if (ocorrencia.slot != null)
        rotulos.preenchido('slot', {'slot': ocorrencia.slot}),
    ].join('  ·  ');

    // Faixa de destaque à esquerda feita com um Row: o Flutter não aceita
    // `borderRadius` junto de uma borda que não é uniforme.
    return Container(
      width: double.infinity,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: Cores.painel,
        borderRadius: BorderRadius.circular(Medidas.raioCartao),
        border: Border.all(color: Cores.borda, width: 2),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(width: Espaco.m, color: Cores.destaque),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: Espaco.xxxl,
                vertical: Espaco.xxl,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  _Etiqueta(
                    texto: rotulos
                        .preenchido('proxima_dose', const {})
                        .toUpperCase(),
                    estilo: Tipografia.h6.copyWith(
                      fontWeight: Tipografia.negrito,
                      letterSpacing: 3,
                    ),
                    icone: Icons.schedule_rounded,
                  ),
                  const SizedBox(height: Espaco.l),
                  Flexible(
                    child: _Encolhe(
                      Row(
                        crossAxisAlignment: CrossAxisAlignment.center,
                        children: [
                          Text(
                            ocorrencia.horario,
                            style: Tipografia.h1.copyWith(
                              height: 1,
                              fontWeight: Tipografia.negrito,
                              color: Cores.destaque,
                              fontFeatures: Tipografia.tabular,
                            ),
                          ),
                          const SizedBox(width: Espaco.xxxl),
                          Container(
                            width: 3,
                            height: 96,
                            decoration: BoxDecoration(
                              color: Cores.borda,
                              borderRadius: BorderRadius.circular(2),
                            ),
                          ),
                          const SizedBox(width: Espaco.xxxl),
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Text(
                                ocorrencia.medicamento,
                                style: Tipografia.h2.copyWith(
                                  fontWeight: Tipografia.negrito,
                                ),
                              ),
                              if (detalhes.isNotEmpty) ...[
                                const SizedBox(height: Espaco.xs),
                                Text(
                                  detalhes,
                                  style: Tipografia.h5.copyWith(
                                    color: Cores.textoFraco,
                                  ),
                                ),
                              ],
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Fluxo da dose: uma instrução por tela, com o número do passo.
///
/// No passo 2 (`consuma_e_detectar`) a tela mostra o preview ao vivo da câmera.
/// A leitura estável é só um status: a liberação do próximo passo é feita pelo
/// operador no painel/CLI, não por um botão da UI.
class TelaDose extends StatelessWidget {
  const TelaDose({
    super.key,
    required this.momento,
    required this.rotulos,
    required this.tela,
    required this.aoConfirmar,
    this.aviso,
    this.quadro,
    this.visaoAtiva = false,
    this.visaoEstavel = false,
    this.visaoAviso,
    this.visaoEspera = Duration.zero,
  });

  final DateTime momento;
  final Rotulos rotulos;
  final Tela tela;
  final VoidCallback aoConfirmar;
  final Aviso? aviso;

  /// JPEG anotado do preview (só chega no passo 2; `null` antes do 1º frame).
  final Uint8List? quadro;
  final bool visaoAtiva;
  final bool visaoEstavel;
  final String? visaoAviso;
  final Duration visaoEspera;

  String? get _statusVisao {
    if (tela.chave != 'consuma_e_detectar') return null;
    if (!visaoAtiva) {
      return 'Câmera desativada — libere o próximo passo no painel';
    }
    if (visaoEstavel) return 'Leitura estável — aguardando liberação no painel';
    if (visaoAviso != null) return 'Câmera: $visaoAviso';
    if (quadro == null) {
      final segundos = visaoEspera.inSeconds;
      return segundos < 3
          ? 'Preparando câmera...'
          : 'Preparando câmera... ${segundos}s (o primeiro frame demora)';
    }
    return 'Aponte a cartela para a câmera';
  }

  @override
  Widget build(BuildContext context) {
    final passo = tela.passo;
    final mostraPreview = tela.chave == 'consuma_e_detectar';
    final estiloMensagem = Tipografia.display.copyWith(height: 1.15);
    return _Moldura(
      momento: momento,
      rotulos: rotulos,
      conectado: true,
      alarme: true,
      filho: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (passo != null) ...[
            Align(
              alignment: Alignment.centerLeft,
              child: _Etiqueta(
                texto: rotuloPasso(rotulos, passo, tela.totalPassos),
                estilo: Tipografia.h5.copyWith(fontWeight: Tipografia.negrito),
              ),
            ),
            const SizedBox(height: Espaco.l),
            BarraPassos(atual: passo, total: tela.totalPassos),
            const SizedBox(height: Espaco.xl),
          ],
          Expanded(
            child: mostraPreview
                ? Column(
                    children: [
                      _Encolhe(
                        Text(
                          tela.mensagem,
                          style: estiloMensagem,
                          textAlign: TextAlign.center,
                        ),
                      ),
                      const SizedBox(height: Espaco.l),
                      Expanded(
                        child: PreviewCamera(
                          quadro: quadro,
                          status: _statusVisao,
                        ),
                      ),
                    ],
                  )
                : Container(
                    width: double.infinity,
                    padding: const EdgeInsets.symmetric(
                      horizontal: Espaco.xxl,
                      vertical: Espaco.l,
                    ),
                    decoration: BoxDecoration(
                      color: Cores.fundo.withValues(alpha: 0.55),
                      border: Border.all(color: Cores.borda, width: 2),
                      borderRadius: BorderRadius.circular(Medidas.raioCartao),
                    ),
                    child: Center(
                      child: _Encolhe(
                        Text(
                          tela.mensagem,
                          style: estiloMensagem,
                          textAlign: TextAlign.center,
                        ),
                      ),
                    ),
                  ),
          ),
          if (tela.proxima.isNotEmpty) ...[
            const SizedBox(height: Espaco.l),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(
                  Icons.arrow_forward_rounded,
                  size: 32,
                  color: Cores.textoSuave,
                ),
                const SizedBox(width: Espaco.s),
                Flexible(
                  child: Text(
                    tela.proxima,
                    style: Tipografia.h5.copyWith(color: Cores.textoFraco),
                  ),
                ),
              ],
            ),
            const SizedBox(height: Espaco.l),
          ],
          if (aviso != null) FaixaAviso(aviso: aviso!),
          if (tela.esperaBotao) ...[
            const SizedBox(height: Espaco.m),
            BotaoOk(rotulos: rotulos, aoConfirmar: aoConfirmar),
          ],
        ],
      ),
    );
  }
}

/// Preview ao vivo da câmera com as caixas desenhadas pelo detector.
///
/// O frame chega pronto do Python (JPEG anotado). Até o primeiro chegar, um
/// marcador discreto ocupa o lugar — sem inventar instrução de domínio.
class PreviewCamera extends StatelessWidget {
  const PreviewCamera({super.key, this.quadro, this.status});

  final Uint8List? quadro;
  final String? status;

  @override
  Widget build(BuildContext context) {
    final frame = quadro;
    final aviso = status;
    return Container(
      width: double.infinity,
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: Paleta.second10,
        borderRadius: BorderRadius.circular(Medidas.raioMedio),
        border: Border.all(color: Cores.destaque, width: 3),
      ),
      child: Stack(
        fit: StackFit.expand,
        children: [
          if (frame == null)
            const Center(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      Icons.photo_camera_outlined,
                      size: 72,
                      color: Cores.textoFraco,
                    ),
                    SizedBox(height: Espaco.s),
                    CircularProgressIndicator(color: Cores.destaque),
                  ],
                ),
              ),
            )
          else
            Image.memory(
              frame,
              gaplessPlayback: true,
              fit: BoxFit.contain,
              filterQuality: FilterQuality.medium,
            ),
          if (aviso != null && aviso.isNotEmpty)
            Align(
              alignment: Alignment.bottomCenter,
              child: Container(
                width: double.infinity,
                color: Cores.fundo.withValues(alpha: 0.88),
                padding: const EdgeInsets.symmetric(
                  horizontal: Espaco.l,
                  vertical: Espaco.s,
                ),
                child: Text(
                  aviso,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  textAlign: TextAlign.center,
                  style: Tipografia.legenda.copyWith(color: Cores.texto),
                ),
              ),
            ),
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
      padding: const EdgeInsets.all(Espaco.xxl),
      decoration: BoxDecoration(
        // Em dose o fundo ganha um degradê verde bem sutil: sinaliza "é com
        // você" sem tirar o contraste do texto.
        gradient: alarme
            ? const LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [Paleta.primary10, Cores.fundo],
              )
            : null,
        color: alarme ? null : Cores.fundo,
        border: Border.all(
          color: alarme ? Cores.destaque : Colors.transparent,
          width: 6,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: Espaco.l + Espaco.xxs,
              vertical: Espaco.m,
            ),
            decoration: BoxDecoration(
              color: Cores.painel,
              border: Border.all(color: Cores.borda, width: 2),
              borderRadius: BorderRadius.circular(Medidas.raioCartao),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                IconeConexao(conectado: conectado),
                const SizedBox(width: Espaco.m),
                Expanded(
                  child: Text(
                    rotulos.preenchido('dispensador', const {}),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Tipografia.h6.copyWith(color: Cores.textoFraco),
                  ),
                ),
                const SizedBox(width: Espaco.m),
                Text(
                  hora(momento),
                  style: Tipografia.h2.copyWith(
                    height: 1,
                    fontWeight: Tipografia.negrito,
                    fontFeatures: Tipografia.tabular,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: Espaco.xl),
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

/// Etiqueta em pílula (rótulo de seção ou número do passo).
class _Etiqueta extends StatelessWidget {
  const _Etiqueta({required this.texto, required this.estilo, this.icone});

  final String texto;
  final TextStyle estilo;
  final IconData? icone;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: Espaco.l,
        vertical: Espaco.s,
      ),
      decoration: BoxDecoration(
        color: Cores.destaqueContainer,
        borderRadius: BorderRadius.circular(Medidas.raioPilula),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icone != null) ...[
            Icon(icone, size: (estilo.fontSize ?? 28) + 8, color: Paleta.primary80),
            const SizedBox(width: Espaco.s),
          ],
          Text(texto, style: estilo.copyWith(color: Paleta.primary90)),
        ],
      ),
    );
  }
}

/// Ícone grande dentro de um círculo suave, para estados sem conteúdo.
class _Emblema extends StatelessWidget {
  const _Emblema({required this.icone, required this.cor});

  final IconData icone;
  final Color cor;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 168,
      height: 168,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: cor.withValues(alpha: 0.14),
        border: Border.all(color: cor.withValues(alpha: 0.5), width: 3),
      ),
      child: Icon(icone, size: 88, color: cor),
    );
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
      size: 44,
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
        final feito = i < atual - 1;
        final corrente = i == atual - 1;
        return Expanded(
          child: Container(
            height: Espaco.m,
            margin: EdgeInsets.only(right: i == total - 1 ? 0 : Espaco.xs),
            decoration: BoxDecoration(
              // Passos feitos em verde sólido; o atual mais claro; o resto
              // em cinza-azulado.
              color: feito
                  ? Paleta.primary40
                  : corrente
                  ? Cores.destaqueSuave
                  : Cores.painelElevado,
              borderRadius: BorderRadius.circular(Espaco.xs),
              boxShadow: corrente
                  ? [
                      BoxShadow(
                        color: Cores.destaque.withValues(alpha: 0.5),
                        blurRadius: 12,
                      ),
                    ]
                  : null,
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
          // Texto escuro sobre o verde vivo: contraste bem maior que branco.
          backgroundColor: Cores.ok,
          foregroundColor: Cores.destaqueEscuro,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(Medidas.raioCartao),
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.check_circle_rounded, size: 64),
            const SizedBox(width: Espaco.l),
            Flexible(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Text(
                  rotulos.preenchido('pressione_ok', const {}),
                  style: Tipografia.h3.copyWith(fontWeight: Tipografia.negrito),
                ),
              ),
            ),
          ],
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
      margin: const EdgeInsets.only(top: Espaco.m),
      padding: const EdgeInsets.symmetric(
        horizontal: Espaco.l,
        vertical: Espaco.m,
      ),
      decoration: BoxDecoration(
        color: Cores.alertaContainer,
        border: Border.all(color: Cores.alerta, width: 3),
        borderRadius: BorderRadius.circular(Medidas.raioMedio),
      ),
      child: Row(
        children: [
          const Icon(
            Icons.warning_amber_rounded,
            color: Cores.alerta,
            size: 44,
          ),
          const SizedBox(width: Espaco.m),
          Expanded(
            child: Text(
              aviso.mensagem,
              style: Tipografia.h5.copyWith(
                color: Cores.alertaTexto,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          const SizedBox(width: Espaco.m),
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: Espaco.m,
              vertical: Espaco.xxs,
            ),
            decoration: BoxDecoration(
              color: Cores.alerta.withValues(alpha: 0.2),
              borderRadius: BorderRadius.circular(Medidas.raioPilula),
            ),
            child: Text(
              aviso.codigo,
              style: Tipografia.h6.copyWith(
                color: Cores.alertaTexto,
                fontWeight: Tipografia.negrito,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
