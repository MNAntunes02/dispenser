# ADR 016 — Preview e detecção de consumo por visão no passo 4

Status: implementada (2026-11-11).

## Contexto

O passo 4 do fluxo guiado ("Tome o medicamento e pressione OK", chave
`tome_e_ok`) é o único em que o core espera uma ação do paciente sem um sensor
que comprove o consumo. O botão OK continua sendo o caminho de sempre, mas
sem câmera não há nenhuma evidência de que o comprimido saiu da cartela.

A primeira integração (commit `43449f2`) ligou um detector YOLO headless: a UI
iniciava um subprocesso Python no passo 4 e, quando a leitura estabilizava,
enviava o mesmo `input:confirma` do botão. Faltava a tela: o paciente via só o
texto e o botão, e não havia como validar o enquadramento da câmera em campo.

O modelo `best.pt` foi treinado com as classes `pill`/`no_pill` em imagens de
cartela (`blister`). O script de câmera já desenhava as caixas (`desenhar`),
mas o modo NDJSON descartava o frame anotado.

## Opções consideradas

- **Janela OpenCV separada** (`cv2.imshow`): reaproveitaria o script
  standalone, mas depende de X11/Wayland e fica fora da tela do kiosk; em
  DRM/KMS puro não abre. Rejeitada.
- **Foto estática do medicamento**: exigiria campo de imagem na agenda,
  mapeamento no core e widget novo — não resolve o enquadramento da câmera.
  Rejeitada para esta fase.
- **Preview ao vivo dentro da UI Flutter**: o Python publica um JPEG anotado
  junto do NDJSON e a UI desenha com `Image.memory`. Integra com o kiosk,
  reusa o detector e permite validar o passo 4 sem hardware extra. Escolhida.

## Escolha

- **Contrato NDJSON** (`detecta_pill/visao.py`): uma linha por frame, com
  `pill` e `no_pill` sempre presentes. Com `--preview`, a linha ganha
  `frame`: JPEG anotado (caixas desenhadas no Python), base64, ~5 fps.
- **Script de câmera** (`detecta_pill/detecta_pill_picamera2.py`):
  `--camera` escolhe a câmera libcamera (a UI já o passava e o argparse
  derrubava o processo); `--preview`/`--preview-fps`/`--preview-largura`
  controlam o JPEG. A captura converte RGB888→BGR, que é o que o YOLO e as
  cores do overlay esperam.
- **UI** (`ui/lib/src/visao.dart`): `Leitura` carrega o `quadro` opcional, mas
  a igualdade/estabilidade continua comparando só `pill`/`no_pill`; frame
  inválido não invalida a contagem. `DetectorConsumo.quadros` emite o JPEG e o
  controlador só o guarda no passo 4.
- **Tela** (`ui/lib/src/telas.dart`): no passo 4, o preview aparece entre a
  frase e o botão OK; antes do primeiro frame, um marcador de câmera. O botão
  OK **continua visível** e funcional (fallback sem câmera).
- **Instalação**: `detecta_pill/` e o modelo vão para `/opt/dispenser`; um
  venv próprio (`--system-site-packages`, para herdar o `picamera2` do apt)
  instala `ultralytics`, `opencv-python-headless` e `torch`. A unit da UI
  libera `/dev/video*` e `/dev/media*` e `AF_NETLINK` (libcamera/udev).
- **Painel de dev**: `ambiente_ui()` passa as `DISPENSER_VISAO_*` do `.env`
  para a UI, sem vazar credenciais do backend.

## Motivo

- O preview resolve o problema que o modo headless não resolvia: mostrar ao
  paciente (e a quem valida em campo) o que a câmera está vendo, com as caixas
  que o detector usou.
- O contrato NDJSON existente é preservado: quem só lê contagem continua
  funcionando; a chave `frame` é opcional.
- O botão OK permanece como fallback e o core continua o único decisor
  (ADR 009): a UI só envia `input:confirma`, nunca inventa estado de dose.

## Riscos e limites

- **Falso positivo**: a regra de estabilidade ainda confirma com leitura
  estável e `pill >= 1`, sem baseline/transição. Se a câmera vê a cartela
  cheia, ela pode confirmar antes de o paciente tomar o remédio. O preview
  torna o problema visível; a regra definitiva depende de definir se a câmera
  olha a cartela (consumo = `no_pill`) ou a mão/tray (consumo = `pill`).
- **Custo no Pi 3B**: converter o frame inteiro para BGR e gerar JPEG a 5 fps
  pesa; `--preview-fps` e `--preview-largura` são os ajustes. O processo sobe
  a cada passo 4 (carrega o modelo do zero).
- **Falha silenciosa**: `stderr` continua drenado e descartado; sem câmera, o
  preview mostra o marcador e o botão OK segue valendo.

## Testes

- Python (`tests/test_visao.py`): `linha_ndjson` com e sem `frame`, frame
  vazio omitido e base64 decodificando de volta para os bytes do JPEG.
- Dart (`ui/test/visao_test.dart`): leitura de frame, base64 inválido, frame
  fora da igualdade, configuração de preview, fake emitindo quadro e o
  contrato de argumentos (`--camera`, `--preview`, `--preview-fps`) entre a
  UI e o script.
- Widget (`ui/test/widget_test.dart`): passo 4 mostra o preview e mantém o
  botão; sem frame mostra o marcador; ao sair do passo 4 a imagem some.
