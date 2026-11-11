"""
Detecção em tempo real de 'pill' e 'no_pill' usando um modelo YOLO (best.pt).

Instalação:
    pip install ultralytics opencv-python

Uso:
    python detectar_pill.py
    python detectar_pill.py --modelo best.pt --camera 0 --conf 0.5

Teclas:
    q ou ESC -> sair
    s        -> salvar frame atual
"""

import argparse
import time

import cv2
from ultralytics import YOLO

# Cores em BGR (OpenCV). Qualquer classe fora desta lista usa a cor padrão.
CORES = {
    "pill": (0, 200, 0),       # verde
    "no_pill": (0, 0, 255),    # vermelho
}
COR_PADRAO = (255, 200, 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modelo", default="best.pt", help="caminho do modelo .pt")
    parser.add_argument("--camera", type=int, default=0, help="índice da câmera")
    parser.add_argument("--conf", type=float, default=0.5, help="confiança mínima")
    parser.add_argument("--imgsz", type=int, default=640, help="tamanho de inferência")
    args = parser.parse_args()

    modelo = YOLO(args.modelo)
    nomes = modelo.names  # dict {id: nome}
    print("Classes do modelo:", nomes)

    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"Não foi possível abrir a câmera {args.camera}")

    # MJPG é necessário para resolução alta com FPS aceitável via USB 2.0
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    t_anterior = time.time()
    contador_salvos = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Falha ao ler frame da câmera.")
            break

        resultados = modelo.predict(
            frame, conf=args.conf, imgsz=args.imgsz, verbose=False
        )[0]

        contagem = {}
        for caixa in resultados.boxes:
            x1, y1, x2, y2 = map(int, caixa.xyxy[0])
            cls_id = int(caixa.cls[0])
            conf = float(caixa.conf[0])
            nome = nomes[cls_id]
            cor = CORES.get(nome, COR_PADRAO)

            contagem[nome] = contagem.get(nome, 0) + 1

            texto = f"{nome} {conf:.2f}"
            (w, h), base = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(frame, (x1, y1), (x2, y2), cor, 2)
            cv2.rectangle(frame, (x1, y1 - h - base - 4), (x1 + w + 4, y1), cor, -1)
            cv2.putText(frame, texto, (x1 + 2, y1 - base - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        # FPS
        agora = time.time()
        fps = 1.0 / max(agora - t_anterior, 1e-6)
        t_anterior = agora

        # Painel de informações
        info = [f"FPS: {fps:.1f}"] + [f"{k}: {v}" for k, v in contagem.items()]
        for i, linha in enumerate(info):
            cv2.putText(frame, linha, (10, 25 + i * 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        cv2.imshow("Deteccao pill / no_pill", frame)

        tecla = cv2.waitKey(1) & 0xFF
        if tecla in (ord("q"), 27):
            break
        elif tecla == ord("s"):
            nome_arquivo = f"captura_{contador_salvos:03d}.jpg"
            cv2.imwrite(nome_arquivo, frame)
            print("Salvo:", nome_arquivo)
            contador_salvos += 1

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
