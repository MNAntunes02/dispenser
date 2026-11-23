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
  'proximas_doses': 'Próximas doses',
  'sem_dose_hoje': 'Nenhuma dose programada para hoje',
  'conectando': 'Conectando...',
  'sem_conexao': 'Sem conexão com o core',
  'sem_core_orientacao': 'Tente novamente em instantes. Não tome o medicamento sem a orientação do dispensador.',
  'dispensador': 'A.Y.D.A.N. v1.0',
  'aviso_falha': 'Falha no sensor',
  'slot': 'Slot {slot}',
  'estoque': 'Estoque de comprimidos',
  'vazio': 'Vazio',
  'comprimidos': '{quantidade} comprimidos',
  'registro': 'Registro de cartela',
  'registro_camera_desativada': 'Câmera desativada — informe a quantidade no painel',
  'registro_aguardando': 'Leitura estável — enviando contagem ao core',
  'registro_preparando': 'Preparando câmera...',
  'registro_apontar': 'Aponte a cartela para a câmera',
  'registro_sem_comprimidos': 'Nenhum comprimido detectado — informe a quantidade no painel',
  'registro_slot_dica': 'Confirme no painel após colocar a cartela',
};
