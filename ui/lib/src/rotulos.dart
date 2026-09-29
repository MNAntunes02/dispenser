/// Cópia de segurança dos rótulos do core (`core/textos.py`, `ROTULOS_UI`).
///
/// A fonte da verdade é o core, que manda `rotulos` no início do retrato. Esta
/// cópia só é usada antes do primeiro retrato — tipicamente justamente quando o
/// core está fora do ar e a tela precisa de texto em português.
///
/// Regra 9 do AGENTS.md: um único arquivo de textos. Para não quebrar a regra
/// na prática, `tests/test_textos_ui.py` (lado Python) confere que esta cópia
/// é idêntica a `ROTULOS_UI`. Se mudar lá, mude aqui — o teste avisa.
library;

const Map<String, String> kRotulosPadrao = {
  'pressione_ok': 'Pressione OK',
  'passo': 'Passo {atual} de {total}',
  'reposo': 'Aguardando a próxima dose',
  'proxima_dose': 'Próxima dose',
  'sem_dose_hoje': 'Nenhuma dose programada para hoje',
  'conectando': 'Conectando ao dispensador…',
  'sem_conexao': 'Sem conexão com o dispensador',
  'sem_core_orientacao':
      'Tente novamente em instantes. Não tome o medicamento sem a orientação do dispensador.',
  'dispensador': 'Dispensador de medicamentos',
  'aviso_falha': 'Falha no sensor',
  'slot': 'Slot {slot}',
};
