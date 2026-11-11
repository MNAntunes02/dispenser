import argparse
import base64
import time
from pathlib import Path

import cv2
import torch
from libcamera import controls
from picamera2 import Picamera2
from ultralytics import YOLO

from visao import contar_classes, linha_ndjson

CORES = {
    "pill": (0, 200, 0),
    "no_pill": (0, 0, 255),
}
COR_PADRAO = (255, 200, 0)

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


def ganhos_awb(texto):
    try:
        vermelho, azul = (float(valor) for valor in texto.split(","))
    except ValueError:
        raise RuntimeError("Ganhos AWB invalidos, use o formato R,B") from None
    return vermelho, azul


def criar_camera(largura, altura, fps, awb, awb_gains, camera_num=0):
    if not Picamera2.global_camera_info():
        raise RuntimeError("Nenhuma camera encontrada pelo libcamera")

    camera = Picamera2(camera_num=camera_num)
    config = camera.create_video_configuration(
        main={"size": (largura, altura), "format": "RGB888"},
        buffer_count=2,
        controls={"FrameRate": fps},
    )
    camera.configure(config)

    controles = {"AwbMode": modo_awb(awb)}
    vermelho, azul = ganhos_awb(awb_gains)
    if vermelho and azul:
        controles["ColourGains"] = (vermelho, azul)
    camera.set_controls(controles)

    camera.start()
    time.sleep(0.5)
    return camera


def capturar(camera):
    # A câmera entrega RGB888; o YOLO e as cores do overlay (CORES) usam BGR.
    frame_rgb = camera.capture_array("main")
    return cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)


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
    )
    print(
        f"camera: {args.camera} {args.largura}x{args.altura} | "
        f"inferencia: {infer_largura}x{infer_altura} @ {args.imgsz} | "
        f"awb: {args.awb} ({args.awbgains})"
    )

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
            anotado = frame.copy()
            contagem = desenhar(anotado, deteccoes, nomes)
            fps = 1.0 / max(duracao, 1e-9)

            if args.headless:
                print(
                    f"[{duracao:.2f}s | {fps:.2f} inf/s] "
                    f"{resumo_deteccoes(deteccoes, nomes)}"
                )
            else:
                exibir = cv2.resize(
                    anotado,
                    (960, int(960 * anotado.shape[0] / anotado.shape[1])),
                    interpolation=cv2.INTER_AREA,
                )
                cv2.putText(
                    exibir,
                    f"inferencia: {duracao:.2f}s ({fps:.2f}/s)",
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 255),
                    2,
                )
                linha = 60
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

                cv2.imshow("pill / no_pill", exibir)
                tecla = cv2.waitKey(1) & 0xFF
                if tecla in (ord("q"), 27):
                    break
                if tecla == ord("s"):
                    arquivo = salvar_frame(
                        anotado,
                        args.salvar_dir or "capturas",
                        contador_salvos,
                    )
                    print("salvo:", arquivo)
                    contador_salvos += 1

            if (
                args.salvar_dir
                and args.salvar_intervalo > 0
                and contador_frames % args.salvar_intervalo == 0
            ):
                arquivo = salvar_frame(
                    anotado,
                    args.salvar_dir,
                    contador_salvos,
                )
                print("salvo:", arquivo)
                contador_salvos += 1

            contador_frames += 1
            if args.max_frames and contador_frames >= args.max_frames:
                break
    finally:
        camera.stop()
        camera.close()
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", default="best_ncnn_model")
    parser.add_argument("--camera", type=int, default=0, help="número da câmera (libcamera)")
    parser.add_argument("--imgsz", type=int, default=800)
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument("--largura", type=int, default=3280)
    parser.add_argument("--altura", type=int, default=2464)
    parser.add_argument("--infer-largura", type=int, default=800)
    parser.add_argument("--infer-altura", type=int, default=600)
    parser.add_argument("--fps-camera", type=float, default=21)
    parser.add_argument(
        "--awb",
        default="custom",
        choices=sorted(MODOS_AWB),
        help="modo de balanco de branco (igual ao rpicam-apps)",
    )
    parser.add_argument(
        "--awbgains",
        default="1.5,1.1",
        help="ganhos fixos de vermelho e azul, ex: 1.5,1.1 (0,0 = automatico)",
    )
    parser.add_argument("--threads", type=int, default=2)
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
        default=800,
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
