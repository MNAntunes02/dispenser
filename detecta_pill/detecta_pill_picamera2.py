import argparse
import base64
import os
import signal
import socket
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from libcamera import controls
from picamera2 import Picamera2
from ultralytics import YOLO

from desempenho import EstatisticasInferencia
from visao import contar_classes, linha_ndjson

CORES = {
    "pill": (0, 200, 0),
    "no_pill": (0, 0, 255),
}
COR_PADRAO = (255, 200, 0)

TUNING_NOIR = Path("/usr/share/libcamera/ipa/rpi/vc4/imx219_noir.json")

MODOS_AWB = {
    "auto": controls.AwbModeEnum.Auto,
    "normal": controls.AwbModeEnum.Auto,
    "incandescent": controls.AwbModeEnum.Incandescent,
    "tungsten": controls.AwbModeEnum.Tungsten,
    "fluorescent": controls.AwbModeEnum.Fluorescent,
    "indoor": controls.AwbModeEnum.Indoor,
    "daylight": controls.AwbModeEnum.Daylight,
    "cloudy": controls.AwbModeEnum.Cloudy,
    "custom": controls.AwbModeEnum.Custom,
}


def modo_awb(nome):
    try:
        return MODOS_AWB[nome]
    except KeyError:
        raise RuntimeError(f"Modo AWB invalido: {nome}") from None


def tuning_padrao():
    """Tuning NoIR do libcamera, quando disponivel (camera sem filtro IR).

    Sem o filtro IR o tuning padrao zera o canal verde e o preview fica
    magenta; o arquivo `*_noir.json` corrige a resposta de cor. Se o arquivo
    nao existir (outro hardware), devolve "" para usar o padrao do sistema.
    """
    return str(TUNING_NOIR) if TUNING_NOIR.exists() else ""


def ganhos_awb(texto):
    try:
        vermelho, azul = (float(valor) for valor in texto.split(","))
    except ValueError:
        raise RuntimeError("Ganhos AWB invalidos, use o formato R,B") from None
    return vermelho, azul


def criar_camera(largura, altura, fps, awb, awb_gains, camera_num=0, tuning=""):
    # O libcamera carrega o tuning ao criar o CameraManager; global_camera_info()
    # abaixo inicializa esse singleton. Por isso o ambiente precisa estar
    # definido antes, senao o Picamera2(tuning=...) chega tarde demais.
    if tuning:
        os.environ["LIBCAMERA_RPI_TUNING_FILE"] = tuning
    else:
        os.environ.pop("LIBCAMERA_RPI_TUNING_FILE", None)

    if not Picamera2.global_camera_info():
        raise RuntimeError("Nenhuma camera encontrada pelo libcamera")

    camera = Picamera2(camera_num=camera_num, tuning=tuning or None)
    config = camera.create_video_configuration(
        main={"size": (largura, altura), "format": "RGB888"},
        buffer_count=2,
        controls={"FrameRate": fps},
    )
    camera.configure(config)

    vermelho, azul = ganhos_awb(awb_gains)
    if vermelho > 0 and azul > 0:
        controles = {
            "AwbMode": controls.AwbModeEnum.Custom,
            "ColourGains": (vermelho, azul),
        }
    else:
        controles = {"AwbMode": modo_awb(awb)}
    camera.set_controls(controles)

    camera.start()
    time.sleep(0.5)
    return camera


def capturar(camera):
    # O stream "RGB888" do Picamera2 entrega os bytes em BGR na memoria
    # (request.py: FORMAT_TABLE["RGB888"] == "BGR"). E o formato que o YOLO,
    # o overlay (CORES) e o cv2.imencode esperam, entao nao ha conversao.
    return camera.capture_array("main")


def carregar_modelo(caminho):
    modelo = YOLO(caminho, task="detect")
    nomes = modelo.names
    valores = set(nomes.values()) if isinstance(nomes, dict) else set(nomes)
    faltando = {"pill", "no_pill"} - valores
    if faltando:
        print(f"Aviso: classes ausentes no modelo: {sorted(faltando)}")
    return modelo, nomes


def nome_da_classe(nomes, classe_id):
    if isinstance(nomes, dict):
        return nomes[int(classe_id)]
    return nomes[int(classe_id)]


def detectar(modelo, frame, conf, imgsz):
    inicio = time.perf_counter()
    resultado = modelo.predict(
        frame,
        conf=conf,
        imgsz=imgsz,
        device="cpu",
        verbose=False,
    )[0]
    duracao = time.perf_counter() - inicio

    deteccoes = []
    for caixa in resultado.boxes:
        x1, y1, x2, y2 = map(float, caixa.xyxy[0])
        deteccoes.append(
            (
                x1,
                y1,
                x2,
                y2,
                int(caixa.cls[0]),
                float(caixa.conf[0]),
            )
        )
    return deteccoes, duracao


def processar_frame(modelo, nomes, frame, conf, imgsz, infer_largura, infer_altura):
    inferencia = cv2.resize(
        frame,
        (infer_largura, infer_altura),
        interpolation=cv2.INTER_AREA,
    )
    deteccoes, duracao = detectar(modelo, inferencia, conf, imgsz)

    escala_x = frame.shape[1] / inferencia.shape[1]
    escala_y = frame.shape[0] / inferencia.shape[0]
    deteccoes_originais = [
        (
            int(x1 * escala_x),
            int(y1 * escala_y),
            int(x2 * escala_x),
            int(y2 * escala_y),
            classe_id,
            confianca,
        )
        for x1, y1, x2, y2, classe_id, confianca in deteccoes
    ]
    return deteccoes_originais, duracao


def desenhar(frame, deteccoes, nomes):
    altura, largura = frame.shape[:2]
    espessura = max(2, largura // 640)
    escala = max(0.5, largura / 1600)
    contagem = {}

    for x1, y1, x2, y2, classe_id, confianca in deteccoes:
        nome = nome_da_classe(nomes, classe_id)
        cor = CORES.get(nome, COR_PADRAO)
        contagem[nome] = contagem.get(nome, 0) + 1

        cv2.rectangle(frame, (x1, y1), (x2, y2), cor, espessura)
        texto = f"{nome} {confianca:.2f}"
        (texto_largura, texto_altura), base = cv2.getTextSize(
            texto,
            cv2.FONT_HERSHEY_SIMPLEX,
            escala,
            espessura,
        )
        topo_texto = max(y1, texto_altura + base + 4)
        cv2.rectangle(
            frame,
            (x1, topo_texto - texto_altura - base - 4),
            (x1 + texto_largura + 4, topo_texto),
            cor,
            -1,
        )
        cv2.putText(
            frame,
            texto,
            (x1 + 2, topo_texto - base - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            escala,
            (255, 255, 255),
            espessura,
        )

    return contagem


def escalar_deteccoes(deteccoes, escala_x, escala_y):
    return [
        (
            int(x1 * escala_x),
            int(y1 * escala_y),
            int(x2 * escala_x),
            int(y2 * escala_y),
            classe_id,
            confianca,
        )
        for x1, y1, x2, y2, classe_id, confianca in deteccoes
    ]


def preparar_exibicao(frame, deteccoes, largura):
    """Reduz o frame para a janela e ajusta as caixas para esse tamanho.

    O desenho acontece só na imagem reduzida: evita copiar e anotar o frame
    em resolução total a cada iteração. O frame original fica intacto para
    salvar capturas ou gerar o preview da UI.
    """
    largura_atual = frame.shape[1]
    if largura > 0 and largura_atual > largura:
        altura = max(2, int(frame.shape[0] * largura / largura_atual))
        exibir = cv2.resize(
            frame,
            (largura, altura),
            interpolation=cv2.INTER_AREA,
        )
        escala_x = largura / largura_atual
        escala_y = altura / frame.shape[0]
        return exibir, escalar_deteccoes(deteccoes, escala_x, escala_y)
    return frame.copy(), deteccoes


def anotar_frame(frame, deteccoes, nomes):
    anotado = frame.copy()
    desenhar(anotado, deteccoes, nomes)
    return anotado


def _interromper(signum, frame):
    raise KeyboardInterrupt


def _janela_disponivel():
    """Diz se há um servidor X acessível para o cv2.imshow.

    O DISPLAY pode estar definido no SSH mesmo sem X rodando (foi o que
    aconteceu quando o lightdm parou). Testar o socket evita o abort do Qt.
    """
    display = os.environ.get("DISPLAY", "")
    if not display.startswith(":"):
        return False
    numero = display[1:].split(".")[0]
    caminho = f"/tmp/.X11-unix/X{numero}"
    if not Path(caminho).exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect(caminho)
    except OSError:
        return False
    return True


class SaidaFramebuffer:
    """Desenha frames direto no framebuffer do console, sem X/Wayland.

    É o fallback quando o Qt não consegue abrir a janela (kiosk em tty/DRM).
    Suporta framebuffer de 16 bpp (RGB565) e 32 bpp (BGRA).
    """

    def __init__(self, caminho="/dev/fb0"):
        self.caminho = caminho
        base = Path("/sys/class/graphics") / Path(caminho).name
        try:
            largura, altura = (
                int(valor) for valor in (base / "virtual_size").read_text().split(",")
            )
            self.bpp = int((base / "bits_per_pixel").read_text())
            self.stride = int((base / "stride").read_text())
        except (OSError, ValueError) as erro:
            raise RuntimeError(
                f"nao foi possivel ler o framebuffer {caminho}: {erro}"
            ) from None
        if self.bpp not in (16, 32):
            raise RuntimeError(f"framebuffer com {self.bpp} bpp nao suportado")

        self.largura = largura
        self.altura = altura
        self.bytes_por_pixel = self.bpp // 8
        try:
            self.fd = os.open(caminho, os.O_RDWR)
        except OSError as erro:
            raise RuntimeError(
                f"nao foi possivel abrir {caminho}: {erro}"
            ) from None
        self.limpar()

    def limpar(self):
        linha = b"\x00" * self.stride
        for y in range(self.altura):
            os.pwrite(self.fd, linha, y * self.stride)

    def _converter(self, frame):
        if self.bpp == 16:
            rgb = frame[:, :, ::-1]
            vermelho = (rgb[:, :, 0] >> 3).astype(np.uint16)
            verde = (rgb[:, :, 1] >> 2).astype(np.uint16)
            azul = (rgb[:, :, 2] >> 3).astype(np.uint16)
            return (vermelho << 11) | (verde << 5) | azul
        alfa = np.full(frame.shape[:2], 255, dtype=np.uint8)
        return np.dstack(
            [frame[:, :, 0], frame[:, :, 1], frame[:, :, 2], alfa]
        )

    def mostrar(self, frame):
        altura, largura = frame.shape[:2]
        if largura > self.largura or altura > self.altura:
            escala = min(self.largura / largura, self.altura / altura)
            novo = (
                max(1, int(largura * escala)),
                max(1, int(altura * escala)),
            )
            frame = cv2.resize(frame, novo, interpolation=cv2.INTER_AREA)
            altura, largura = frame.shape[:2]

        x = max(0, (self.largura - largura) // 2)
        y = max(0, (self.altura - altura) // 2)
        pixels = self._converter(frame)

        forma = (altura, self.largura)
        if pixels.ndim == 3:
            forma += (pixels.shape[2],)
        faixa = np.zeros(forma, dtype=pixels.dtype)
        faixa[:, x : x + largura] = pixels
        dados = faixa.tobytes()

        linha_bytes = self.largura * self.bytes_por_pixel
        if linha_bytes == self.stride:
            os.pwrite(self.fd, dados, y * self.stride)
            return

        padding = b"\x00" * (self.stride - linha_bytes)
        for i in range(altura):
            inicio = i * linha_bytes
            fim = inicio + linha_bytes
            os.pwrite(
                self.fd,
                dados[inicio:fim] + padding,
                (y + i) * self.stride,
            )

    def fechar(self):
        os.close(self.fd)


def escolher_saida(args):
    if args.headless or args.ndjson:
        return "headless"
    if args.saida in ("janela", "framebuffer", "headless"):
        return args.saida
    if _janela_disponivel():
        return "janela"
    if Path("/dev/fb0").exists():
        return "framebuffer"
    return "headless"


def quadro_jpeg(frame, deteccoes, nomes, largura):
    """JPEG anotado em base64 para o preview da UI (passo 4).

    Desenha as caixas sobre uma cópia (o frame original continua valendo para
    a próxima inferência), reduz para `largura` e comprime com qualidade 70 —
    o suficiente para a tela e barato o bastante para o socket do Pi.
    """
    anotado = frame.copy()
    desenhar(anotado, deteccoes, nomes)

    altura_atual, largura_atual = anotado.shape[:2]
    if largura > 0 and largura_atual > largura:
        altura = max(2, int(altura_atual * largura / largura_atual))
        anotado = cv2.resize(anotado, (largura, altura), interpolation=cv2.INTER_AREA)

    ok, buffer = cv2.imencode(".jpg", anotado, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return None
    return base64.b64encode(buffer.tobytes()).decode("ascii")


def resumo_deteccoes(deteccoes, nomes):
    if not deteccoes:
        return "nada detectado"
    itens = []
    for _, _, _, _, classe_id, confianca in deteccoes:
        itens.append(f"{nome_da_classe(nomes, classe_id)} {confianca:.2f}")
    return ", ".join(itens)


def salvar_frame(frame, pasta, contador):
    destino = Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    arquivo = destino / f"captura_{contador:04d}.jpg"
    cv2.imwrite(str(arquivo), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    return arquivo


def dimensoes_inferencia(args):
    largura = max(2, args.infer_largura)
    altura = max(2, args.infer_altura)
    return largura, altura


def executar_imagem(args, modelo, nomes, infer_largura, infer_altura):
    frame = cv2.imread(args.imagem)
    if frame is None:
        raise RuntimeError(f"Nao foi possivel ler a imagem: {args.imagem}")

    deteccoes, duracao = processar_frame(
        modelo,
        nomes,
        frame,
        args.conf,
        args.imgsz,
        infer_largura,
        infer_altura,
    )
    anotado = frame.copy()
    contagem = desenhar(anotado, deteccoes, nomes)

    print(
        f"inferencia: {duracao:.3f}s | "
        f"{resumo_deteccoes(deteccoes, nomes)}"
    )
    if contagem:
        print("contagem:", ", ".join(f"{k}: {v}" for k, v in contagem.items()))

    if args.salvar_dir:
        arquivo = salvar_frame(anotado, args.salvar_dir, 0)
        print("salvo:", arquivo)

    if not args.headless:
        cv2.imshow("pill / no_pill - imagem", anotado)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def executar_camera(args, modelo, nomes, infer_largura, infer_altura):
    camera = criar_camera(
        args.largura,
        args.altura,
        args.fps_camera,
        args.awb,
        args.awbgains,
        args.camera,
        args.tuning,
    )
    print(
        f"camera: {args.camera} {args.largura}x{args.altura} | "
        f"inferencia: {infer_largura}x{infer_altura} @ {args.imgsz} | "
        f"awb: {args.awb} ({args.awbgains}) | "
        f"tuning: {args.tuning or 'padrao do sistema'}"
    )

    saida = escolher_saida(args)
    tela = None
    if saida == "framebuffer":
        try:
            tela = SaidaFramebuffer()
            print("saida: framebuffer /dev/fb0 (Ctrl+C encerra)")
        except RuntimeError as erro:
            print(f"aviso: {erro}; usando headless")
            saida = "headless"
    elif saida == "janela":
        print("saida: janela OpenCV")
    else:
        print("saida: headless")

    try:
        signal.signal(signal.SIGTERM, _interromper)
    except ValueError:
        pass

    estatisticas = EstatisticasInferencia()
    inicio_sessao = time.perf_counter()
    contador_salvos = 0
    contador_frames = 0
    ultimo_preview = 0.0
    intervalo_preview = 1.0 / args.preview_fps if args.preview_fps > 0 else 0.0
    try:
        while True:
            frame = capturar(camera)
            deteccoes, duracao = processar_frame(
                modelo,
                nomes,
                frame,
                args.conf,
                args.imgsz,
                infer_largura,
                infer_altura,
            )
            estatisticas.registrar(duracao)
            if args.ndjson:
                # Contrato com a UI (ui/lib/src/visao.dart): uma linha por
                # frame, sem janela. A UI aplica a regra de estabilidade e
                # mostra o `frame` (quando pedido) como preview ao vivo.
                contagem = contar_classes(
                    deteccoes, lambda classe_id: nome_da_classe(nomes, classe_id)
                )
                quadro = None
                if args.preview:
                    agora = time.monotonic()
                    if (
                        intervalo_preview <= 0
                        or agora - ultimo_preview >= intervalo_preview
                    ):
                        ultimo_preview = agora
                        quadro = quadro_jpeg(
                            frame, deteccoes, nomes, args.preview_largura
                        )
                print(linha_ndjson(contagem, quadro), flush=True)
                contador_frames += 1
                if args.max_frames and contador_frames >= args.max_frames:
                    break
                continue

            contagem = contar_classes(
                deteccoes, lambda classe_id: nome_da_classe(nomes, classe_id)
            )
            fps = 1.0 / max(duracao, 1e-9)

            if saida == "headless":
                print(
                    f"[{duracao:.2f}s | {fps:.2f} inf/s] "
                    f"{resumo_deteccoes(deteccoes, nomes)}"
                )
            else:
                exibir, deteccoes_exibir = preparar_exibicao(
                    frame, deteccoes, args.exibir_largura
                )
                desenhar(exibir, deteccoes_exibir, nomes)
                cv2.putText(
                    exibir,
                    f"inferencia: {duracao:.2f}s ({fps:.2f}/s)",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                )
                cv2.putText(
                    exibir,
                    f"media: {estatisticas.media:.2f}s "
                    f"({estatisticas.fps_inferencia:.2f}/s)",
                    (10, 60),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                )
                linha = 90
                for nome, quantidade in contagem.items():
                    cv2.putText(
                        exibir,
                        f"{nome}: {quantidade}",
                        (10, linha),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.8,
                        CORES.get(nome, COR_PADRAO),
                        2,
                    )
                    linha += 30

                if tela is not None:
                    tela.mostrar(exibir)
                else:
                    cv2.imshow("pill / no_pill", exibir)
                    tecla = cv2.waitKey(1) & 0xFF
                    if tecla in (ord("q"), 27):
                        break
                    if tecla == ord("s"):
                        arquivo = salvar_frame(
                            anotar_frame(frame, deteccoes, nomes),
                            args.salvar_dir or "capturas",
                            contador_salvos,
                        )
                        print("salvo:", arquivo)
                        contador_salvos += 1
                    if (
                        cv2.getWindowProperty(
                            "pill / no_pill", cv2.WND_PROP_VISIBLE
                        )
                        < 1
                    ):
                        break

            if (
                args.salvar_dir
                and args.salvar_intervalo > 0
                and contador_frames % args.salvar_intervalo == 0
            ):
                arquivo = salvar_frame(
                    anotar_frame(frame, deteccoes, nomes),
                    args.salvar_dir,
                    contador_salvos,
                )
                print("salvo:", arquivo)
                contador_salvos += 1

            contador_frames += 1
            if args.max_frames and contador_frames >= args.max_frames:
                break
    except KeyboardInterrupt:
        pass
    finally:
        camera.stop()
        camera.close()
        if tela is not None:
            tela.fechar()
        cv2.destroyAllWindows()
        if not args.ndjson:
            resumo = estatisticas.resumo(time.perf_counter() - inicio_sessao)
            print(resumo, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", default="best_ncnn_model")
    parser.add_argument("--camera", type=int, default=0, help="número da câmera (libcamera)")
    # Defaults para o Pi 3B: captura em 720p e frame de inferência próximo da
    # entrada fixa do NCNN (800x800). Em 3280x2464 o loop gasta a maior parte
    # do tempo copiando/redimensionando o frame; os argumentos continuam
    # sobrescrevíveis.
    parser.add_argument("--imgsz", type=int, default=800)
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--largura", type=int, default=1280)
    parser.add_argument("--altura", type=int, default=720)
    parser.add_argument("--infer-largura", type=int, default=800)
    parser.add_argument("--infer-altura", type=int, default=600)
    parser.add_argument("--fps-camera", type=float, default=15)
    parser.add_argument(
        "--awb",
        default="auto",
        choices=sorted(MODOS_AWB),
        help="modo de balanco de branco (igual ao rpicam-apps)",
    )
    parser.add_argument(
        "--awbgains",
        default="0,0",
        help="ganhos fixos de vermelho e azul, ex: 1.5,1.1 (0,0 usa --awb)",
    )
    parser.add_argument(
        "--tuning",
        default=tuning_padrao(),
        help="arquivo de tuning do libcamera; vazio usa o padrao do sistema "
        "(padrao: imx219_noir.json quando presente)",
    )
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument(
        "--exibir-largura",
        type=int,
        default=960,
        help="largura da tela em pixels (0 = sem redução)",
    )
    parser.add_argument(
        "--saida",
        choices=("auto", "janela", "framebuffer", "headless"),
        default="auto",
        help="onde desenhar: auto tenta janela OpenCV e cai no framebuffer "
        "quando nao ha X/Wayland",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--ndjson",
        action="store_true",
        help="imprime uma linha JSON por frame ({'pill':N,'no_pill':M}) "
        "no stdout, sem janela — consumido pela UI (detecção de consumo)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="inclui no NDJSON um JPEG anotado em base64 (chave 'frame') "
        "para o preview ao vivo da UI",
    )
    parser.add_argument(
        "--preview-fps",
        type=float,
        default=5.0,
        help="quadros de preview por segundo (0 = todo frame)",
    )
    parser.add_argument(
        "--preview-largura",
        type=int,
        default=640,
        help="largura do JPEG de preview em pixels (0 = sem redução)",
    )
    parser.add_argument("--salvar-dir", default="")
    parser.add_argument("--salvar-intervalo", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--imagem", default="")
    args = parser.parse_args()

    torch.set_num_threads(max(1, args.threads))
    infer_largura, infer_altura = dimensoes_inferencia(args)
    modelo, nomes = carregar_modelo(args.modelo)
    print("classes:", nomes)

    if args.imagem:
        executar_imagem(args, modelo, nomes, infer_largura, infer_altura)
    else:
        executar_camera(args, modelo, nomes, infer_largura, infer_altura)


if __name__ == "__main__":
    main()
