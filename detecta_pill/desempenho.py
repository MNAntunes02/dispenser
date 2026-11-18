"""Acumula tempos de inferência e gera o resumo da sessão.

Módulo **puro**: não importa cv2, picamera2 nem ultralytics. Assim pode ser
usado pelo script de câmera e testado fora do Raspberry Pi.

O resumo separa duas métricas:

- FPS de inferência: quantas inferências por segundo se só o tempo do modelo
  contasse (``1 / média``).
- FPS do loop: quantos frames a detecção realmente entregou por segundo,
  incluindo captura, inferência e desenho/exibição (``frames / tempo total``).
"""

from __future__ import annotations


class EstatisticasInferencia:
    """Soma, média, mínimo e máximo dos tempos de inferência da sessão."""

    def __init__(self) -> None:
        self.frames = 0
        self.total = 0.0
        self.minimo = 0.0
        self.maximo = 0.0

    def registrar(self, duracao: float) -> None:
        duracao = max(0.0, float(duracao))
        self.frames += 1
        self.total += duracao
        if self.frames == 1 or duracao < self.minimo:
            self.minimo = duracao
        if self.frames == 1 or duracao > self.maximo:
            self.maximo = duracao

    @property
    def media(self) -> float:
        if not self.frames:
            return 0.0
        return self.total / self.frames

    @property
    def fps_inferencia(self) -> float:
        media = self.media
        return 1.0 / media if media > 0 else 0.0

    def fps_loop(self, tempo_total: float) -> float:
        if tempo_total <= 0 or not self.frames:
            return 0.0
        return self.frames / tempo_total

    def resumo(self, tempo_total: float) -> str:
        if not self.frames:
            return (
                "--- resumo da sessao ---\n"
                f"frames: 0 | tempo: {tempo_total:.1f} s\n"
                "nenhuma inferencia concluida"
            )
        return (
            "--- resumo da sessao ---\n"
            f"frames: {self.frames} | tempo: {tempo_total:.1f} s\n"
            f"inferencia: media {self.media * 1000:.1f} ms | "
            f"min {self.minimo * 1000:.1f} ms | "
            f"max {self.maximo * 1000:.1f} ms\n"
            f"FPS inferencia: {self.fps_inferencia:.2f}/s | "
            f"FPS loop: {self.fps_loop(tempo_total):.2f}/s"
        )
