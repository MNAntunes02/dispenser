# ADR 009 — A UI exibe o que o core renderiza; ela nunca decide o estado da dose

Status: implementada (Fase 5, 2026-09-29).

## Contexto
A Fase 5 entrega a tela do LCD (`ui/`, Flutter Linux/arm64, ADR 002) guiada pelo core
(ADR 003). O paciente precisa ver **o que fazer agora** e apertar um único botão. A máquina
de estados (`core/maquina_estados.py`) já conhece a dose, os sensores e os timeouts
aprovados na Fase 2.

A tentação natural ao escrever a UI é fazer o widget decidir: "se a fase for X, mostro
Y", "se o usuário tocou, marco como tomado". Isso duplicaria as regras de segurança em
duas linguagens e criaria divergência: a UI pode mostrar `tomada` enquanto o core ainda
considera `AGUARDANDO_RETORNO`, e um paciente (ou um teste) poderia "confirmar" uma dose
sem sensor nenhum.

## Opções consideradas
- **UI decide o passo** (estados replicados no Dart) — simples de testar isoladamente, mas
  duplica a máquina de estados; qualquer mudança no core passa a ter dois lugares para
  mudar, e a tela pode afirmar uma dose que o core não confirmou.
- **Core publica texto pronto** e a UI só desenha e devolve a intenção do botão — o core
  continua sendo a única autoridade sobre a dose; a UI vira uma camada de apresentação
  com regras triviais (qual moldura usar, mostrar o botão).
- **HTML/servidor web no core** — dispensaria o socket, mas exige navegador embarcado no
  Pi e traz peso e risco de segurança desnecessários.

## Escolha
O core **renderiza** cada tela e a UI **exibe**:

- `core/textos.py` é a fonte única dos textos de domínio; a frase chega pronta em
  `estado.mensagem`. A UI não traduz nem monta frase de domínio.
- `estado` carrega `chave`, `passo` (1..6), `totalPassos`, `esperaBotao` e
  `fluxo` (`dose` | `reposo` | `alerta`). A UI escolhe a moldura com base em `fluxo` e
  no `passo`, sem conhecer a máquina de estados.
- A UI envia **apenas** `{"v":1,"type":"input","acao":"confirma"}`. A política aprovada
  não tem soneca, então não existe `cancela`/`silenciar`. O core decide se aquele OK
  vale, olhando sensores e fase.
- A UI **não** afirma nada quando o core está fora do ar: sem `health` por 6 s, ou socket
  fechado, ela volta para a tela "sem conexão" e **limpa** o passo em exibição, em vez de
  deixar um passo velho parecer atual.
- Fora do fluxo, o core publica explicitamente `reposo`/`reposo_sem_dose`: sem isso a UI
  ficaria em "conectando" indefinidamente depois do boot.
- O retrato (`rotulos`, `agenda`, `estado`) é servido de um cache em memória atualizado
  no `tick()`; a thread do socket nunca toca SQLite nem a FSM.

Consequência aceita: a UI não tem teste de fluxo próprio — quem testa o fluxo é o core
(`tests/test_fluxo_ui.py`) e o teste de integração `ui/test/integracao_core_test.dart`, que
sobe o core real e confirma a dose inteira pelo socket real.

## Alternativas rejeitadas depois
- **Espelhar textos no Dart** (`ui/lib/src/rotulos.dart`) foi adotado apenas como
  *fallback* antes do primeiro retrato (para não exibir identificadores crus no primeiro
  frame), protegido por `tests/test_textos_ui.py`, que falha se os arquivos divergirem.
- **Botão na UI decidindo dose**: descartado — é a violação de segurança que este ADR
  existe para impedir.
