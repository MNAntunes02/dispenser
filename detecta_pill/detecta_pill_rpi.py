"""
Detecção pill / no_pill na Raspberry Pi 3B priorizando QUALIDADE (não FPS).

- Modelo exportado em NCNN com imgsz=800 (mesmo valor usado aqui).
- Captura em resolução alta, sem redução antes do modelo.
- Inferência em uma thread separada: o vídeo na tela fica fluido e as
  caixas são atualizadas na velocidade que a Pi conseguir.
- Todo frame disponível é processado (sem pular frames).

Uso:
    python detectar_pill_rpi_hq.py --modelo best_ncnn_model --imgsz 800
    python detectar_pill_rpi_hq.py --largura 1920 --altura 1080
    python detectar_pill_rpi_hq.py --headless

Teclas (com janela):
    q ou ESC -> sair
    s        -> salvar frame anotado em resolução total
"""

import argparse
import threading
import time

import cv2
from ultralytics import YOLO

CORES = {
    "pill": (0, 200, 0),
    "no_pill": (0, 0, 255),
}
COR_PADRAO = (255, 200, 0)


class CameraThread:
    """Lê a câmera continuamente e guarda só o frame mais recente."""

    def __init__(self, indice, largura, altura):
        self.cap = cv2.VideoCapture(indice)
        if not self.cap.isOpened():
            raise RuntimeError(f"Não foi possível abrir a câmera {indice}")
        # MJPG é necessário para resolução alta com FPS aceitável via USB 2.0
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, largura)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, altura)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.frame = None
        self.id = 0  # incrementa a cada frame novo
        self.rodando = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while self.rodando:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = frame
                    self.id += 1

    def ler(self):
        with self.lock:
            if self.frame is None:
                return None, 0
            return self.frame.copy(), self.id

    def resolucao(self):
        return (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    def parar(self):
        self.rodando = False
        self.thread.join(timeout=1)
        self.cap.release()


class Detector(threading.Thread):
    """Roda o modelo em segundo plano sempre no frame mais recente."""

    def __init__(self, modelo, camera, conf, imgsz, headless):
        super().__init__(daemon=True)
        self.modelo = modelo
        self.nomes = modelo.names
        self.camera = camera
        self.conf = conf
        self.imgsz = imgsz
        self.headless = headless

        self.deteccoes = []
        self.fps = 0.0
        self.lock = threading.Lock()
        self.rodando = True

    def run(self):
        ultimo_id = 0
        t_anterior = time.time()
        while self.rodando:
            frame, fid = self.camera.ler()
            if frame is None or fid == ultimo_id:
                time.sleep(0.005)
                continue
            ultimo_id = fid

            res = self.modelo.predict(frame, conf=self.conf, imgsz=self.imgsz,
                                      device="cpu", verbose=False)[0]
            dets = []
            for c in res.boxes:
                x1, y1, x2, y2 = map(int, c.xyxy[0])
                dets.append((x1, y1, x2, y2,
                             self.nomes[int(c.cls[0])], float(c.conf[0])))

            agora = time.time()
            with self.lock:
                self.deteccoes = dets
                self.fps = 1.0 / max(agora - t_anterior, 1e-6)
            t_anterior = agora

            if self.headless:
                resumo = ", ".join(f"{d[4]} {d[5]:.2f}" for d in dets)
                print(f"[{self.fps:4.2f} inf/s] {resumo or 'nada detectado'}")

    def obter(self):
        with self.lock:
            return list(self.deteccoes), self.fps


def desenhar(frame, deteccoes):
    espessura = max(2, frame.shape[1] // 640)
    escala = max(0.5, frame.shape[1] / 1600)
    for x1, y1, x2, y2, nome, conf in deteccoes:
        cor = CORES.get(nome, COR_PADRAO)
        cv2.rectangle(frame, (x1, y1), (x2, y2), cor, espessura)
        cv2.putText(frame, f"{nome} {conf:.2f}", (x1, max(y1 - 8, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, escala, cor, espessura)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--modelo", default="best_ncnn_model")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--conf", type=float, default=0.5)
    p.add_argument("--imgsz", type=int, default=800,
                   help="deve ser igual ao imgsz usado na exportação NCNN")
    p.add_argument("--largura", type=int, default=1280)
    p.add_argument("--altura", type=int, default=720)
    p.add_argument("--headless", action="store_true",
                   help="sem janela; imprime detecções no terminal")
    args = p.parse_args()

    modelo = YOLO(args.modelo, task="detect")
    print("Classes:", modelo.names)

    cam = CameraThread(args.camera, args.largura, args.altura)
    print("Resolução real da câmera:", cam.resolucao())

    detector = Detector(modelo, cam, args.conf, args.imgsz, args.headless)
    detector.start()

    salvos = 0
    try:
        while True:
            if args.headless:
                time.sleep(0.2)
                continue

            frame, _ = cam.ler()
            if frame is None:
                time.sleep(0.01)
                continue

            deteccoes, fps = detector.obter()
            desenhar(frame, deteccoes)

            # Cópia em resolução total para salvar; a exibida é reduzida
            anotado = frame
            cv2.putText(frame, f"deteccao: {fps:.2f}/s", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            exibir = cv2.resize(frame, (960, int(960 * frame.shape[0] / frame.shape[1])))
            cv2.imshow("pill / no_pill", exibir)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla in (ord("q"), 27):
                break
            elif tecla == ord("s"):
                nome = f"captura_{salvos:03d}.jpg"
                cv2.imwrite(nome, anotado, [cv2.IMWRITE_JPEG_QUALITY, 95])
                print("Salvo:", nome)
                salvos += 1
    except KeyboardInterrupt:
        pass
    finally:
        detector.rodando = False
        cam.parar()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
