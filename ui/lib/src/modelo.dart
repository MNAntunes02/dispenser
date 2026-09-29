/// Mensagens do `dispenser-core` (espelha `core/protocolo_ui.py`).
///
/// Regra de segurança do paciente: a UI **não interpreta** o estado da dose.
/// Ela exibe `mensagem` (já renderizada em pt-BR pelo core) e devolve apenas
/// a intenção do botão. Se um campo faltar, o padrão é conservador (nada de
/// botão quando o core não pediu).
library;

import 'rotulos.dart';

class MensagemInvalida implements Exception {
  MensagemInvalida(this.motivo);

  final String motivo;

  @override
  String toString() => 'MensagemInvalida: $motivo';
}

/// Mensagem válida do protocolo (versão 1).
sealed class MensagemCore {
  const MensagemCore();

  /// Converte o JSON do socket em uma mensagem tipada.
  factory MensagemCore.deJson(Map<String, Object?> json) {
    if (json['v'] != 1) {
      throw MensagemInvalida('versão não suportada: ${json['v']}');
    }
    final tipo = json['type'];
    return switch (tipo) {
      'rotulos' => Rotulos.deJson(json),
      'agenda' => Agenda.deJson(json),
      'estado' => Tela.deJson(json),
      'alerta' => Aviso.deJson(json),
      'health' => const Health(),
      _ => throw MensagemInvalida('tipo fora do contrato: $tipo'),
    };
  }

  String get tipo;
}

/// Rótulos fixos e o total de passos (mensagem `rotulos` do retrato).
class Rotulos extends MensagemCore {
  const Rotulos(this.textos, this.totalPassos);

  final Map<String, String> textos;
  final int totalPassos;

  @override
  String get tipo => 'rotulos';

  /// Rótulo com parâmetros, como "Passo {atual} de {total}".
  ///
  /// Antes do primeiro retrato do core usamos a cópia local (ver
  /// `rotulos.dart`), que é conferida contra `core/textos.py` nos testes.
  String preenchido(String chave, Map<String, Object?> params) {
    final modelo = textos[chave] ?? kRotulosPadrao[chave];
    if (modelo == null) return '';
    return modelo.replaceAllMapped(
      RegExp(r'\{(\w+)\}'),
      (m) => '${params[m.group(1)] ?? ''}',
    );
  }

  factory Rotulos.deJson(Map<String, Object?> json) {
    final bruto = json['rotulos'];
    final textos = <String, String>{};
    if (bruto is Map) {
      for (final entrada in bruto.entries) {
        if (entrada.key is String && entrada.value is String) {
          textos[entrada.key as String] = entrada.value as String;
        }
      }
    }
    final total = json['totalPassos'];
    return Rotulos(textos, total is int ? total : 6);
  }

  static const vazio = Rotulos({}, 6);
}

/// Uma dose do dia (dentro da mensagem `agenda`).
class Ocorrencia {
  const Ocorrencia({
    required this.id,
    required this.medicamento,
    required this.horario,
    required this.estado,
    this.dosagem = '',
    this.slot,
  });

  final String id;
  final String medicamento;
  final String dosagem;
  final String horario;
  final int? slot;

  /// Estado da máquina (`ALARME`, `CONCLUIDA`, ...). A UI só mostra/usa para
  /// saber se a dose ainda está em aberto; a decisão é do core.
  final String estado;

  bool get emAberto => !const {'CONCLUIDA', 'NAO_ATENDIDA'}.contains(estado);

  factory Ocorrencia.deJson(Map<String, Object?> json) {
    final slot = json['slot'];
    return Ocorrencia(
      id: '${json['id'] ?? ''}',
      medicamento: '${json['medicamento'] ?? ''}',
      dosagem: '${json['dosagem'] ?? ''}',
      horario: '${json['horario'] ?? ''}',
      estado: '${json['estado'] ?? ''}',
      slot: slot is int ? slot : null,
    );
  }
}

/// Agenda do dia (mensagem `agenda`).
class Agenda extends MensagemCore {
  const Agenda(this.dia, this.ocorrencias);

  /// Dia no formato ISO do core (ex.: `2026-09-29`).
  final String dia;
  final List<Ocorrencia> ocorrencias;

  @override
  String get tipo => 'agenda';

  Ocorrencia? get emAberto =>
      ocorrencias.where((o) => o.emAberto).firstOrNull;

  Ocorrencia? get primeira => ocorrencias.isEmpty ? null : ocorrencias.first;

  factory Agenda.deJson(Map<String, Object?> json) {
    final lista = <Ocorrencia>[];
    final bruto = json['ocorrencias'];
    if (bruto is List) {
      for (final item in bruto) {
        if (item is Map) lista.add(Ocorrencia.deJson(item.cast<String, Object?>()));
      }
    }
    return Agenda('${json['dia'] ?? ''}', lista);
  }

  static const vazia = Agenda('', []);
}

/// A tela atual do fluxo, pronta para exibir (mensagem `estado`).
class Tela extends MensagemCore {
  const Tela({
    required this.chave,
    required this.mensagem,
    this.fase,
    this.ocorrenciaId,
    this.passo,
    this.totalPassos = 6,
    this.slot,
    this.proxima = '',
    this.esperaBotao = false,
    this.fluxo = 'dose',
  });

  final String chave;

  /// Frase em pt-BR montada pelo core — a UI mostra como veio.
  final String mensagem;
  final String? fase;
  final String? ocorrenciaId;

  /// Passo 1..6 do fluxo guiado (calculado pelo core) ou `null`.
  final int? passo;
  final int totalPassos;
  final int? slot;
  final String proxima;

  /// Só há botão quando o core pede (`ok` pendente).
  final bool esperaBotao;

  /// `dose` ou `alerta` (chave fora do fluxo guiado).
  final String fluxo;

  @override
  String get tipo => 'estado';

  bool get emFluxo => fluxo == 'dose' && passo != null;

  /// A dose está em uma fase que a UI deve mostrar como "em andamento".
  bool get doseEmAberto => emFluxo && chave != 'tudo_certo' && chave != 'tudo_certo_fim';

  factory Tela.deJson(Map<String, Object?> json) {
    final passo = json['passo'];
    final total = json['totalPassos'];
    final slot = json['slot'];
    return Tela(
      chave: '${json['chave'] ?? ''}',
      mensagem: '${json['mensagem'] ?? ''}',
      fase: json['fase'] as String?,
      ocorrenciaId: json['ocorrenciaId'] as String?,
      passo: passo is int ? passo : null,
      totalPassos: total is int ? total : 6,
      slot: slot is int ? slot : null,
      proxima: '${json['proxima'] ?? ''}',
      esperaBotao: json['esperaBotao'] == true,
      fluxo: '${json['fluxo'] ?? 'dose'}',
    );
  }
}

/// Aviso pontual (mensagem `alerta`): falha de sensor, socket, UI inválida.
class Aviso extends MensagemCore {
  const Aviso({required this.codigo, required this.mensagem});

  final String codigo;
  final String mensagem;

  @override
  String get tipo => 'alerta';

  factory Aviso.deJson(Map<String, Object?> json) => Aviso(
        codigo: '${json['codigo'] ?? '?'}',
        mensagem: '${json['mensagem'] ?? ''}',
      );
}

/// Heartbeat do core (mensagem `health`).
class Health extends MensagemCore {
  const Health();

  @override
  String get tipo => 'health';
}
