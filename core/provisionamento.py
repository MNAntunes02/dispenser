"""Provisionamento de primeiro uso do dispensador (Fase 3b).

O Pi headless recebe do app (via BLE/GATT), após validar um código de 6
dígitos mostrado na tela, o Wi-Fi e a configuração Firebase; aplica a rede,
persiste `/var/lib/dispenser/dispenser.env` (permissão 600) e para. Senha de
rede nunca é gravada em disco próprio nem em logs (fica no gestor de rede).
Tudo injetável (Rede, Tela) para testes sem hardware.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

VALIDADE_CODIGO_S = 600.0
ARQUIVO_ENV_PADRAO = Path("/var/lib/dispenser/dispenser.env")


class ProvisionamentoErro(Exception):
    """Falha genérica do provisionamento (traduzida em status GATT)."""


class CodigoInvalido(ProvisionamentoErro):
    """Código de pareamento incorreto ou expirado."""


class CargaInvalida(ProvisionamentoErro):
    """Payload de configuração malformado ou incompleto."""


@dataclass(frozen=True)
class ConfigFirebase:
    project_id: str
    api_key: str
    usuario_id: str


@dataclass(frozen=True)
class CargaProvisionamento:
    codigo: str
    ssid: str
    senha: str
    firebase: ConfigFirebase


def _exige(mapa: dict, chave: str) -> str:
    valor = mapa.get(chave)
    if not isinstance(valor, str) or not valor.strip():
        raise CargaInvalida(f"campo ausente: {chave}")
    return valor.strip()


def validar_carga(carga: object) -> CargaProvisionamento:
    """Valida o payload de configuração recebido via GATT."""
    if not isinstance(carga, dict):
        raise CargaInvalida("carga não é um objeto")
    wifi = carga.get("wifi")
    firebase = carga.get("firebase")
    if not isinstance(wifi, dict) or not isinstance(firebase, dict):
        raise CargaInvalida("wifi/firebase ausentes")
    codigo = carga.get("codigo")
    if not isinstance(codigo, str) or not (codigo.isdigit() and len(codigo) == 6):
        raise CargaInvalida("código inválido")
    senha = wifi.get("senha")
    if senha is None:
        raise CargaInvalida("senha ausente")
    if not isinstance(senha, str):
        raise CargaInvalida("senha inválida")
    return CargaProvisionamento(
        codigo=codigo,
        ssid=_exige(wifi, "ssid"),
        senha=senha,
        firebase=ConfigFirebase(
            project_id=_exige(firebase, "projectId"),
            api_key=_exige(firebase, "apiKey"),
            usuario_id=_exige(firebase, "usuarioId"),
        ),
    )


class MontadorChunks:
    """Remonta o payload de configuração recebido em pedaços BLE.

    Cada pedaço: `{"seq": int, "total": int, "dados": string}`.
    Retorna o JSON completo quando os `total` pedaços estiverem presentes.
    """

    TAM_MAX = 240
    MAX_PECAS = 8

    def __init__(self) -> None:
        self._pecas: dict[int, str] = {}
        self._total: int | None = None

    def adicionar(self, peca: object) -> str | None:
        if not isinstance(peca, dict):
            raise CargaInvalida("pedaço inválido")
        seq, total = peca.get("seq"), peca.get("total")
        dados = peca.get("dados")
        if not isinstance(seq, int) or not isinstance(total, int) or total <= 0:
            raise CargaInvalida("seq/total inválidos")
        if total > self.MAX_PECAS or not (0 <= seq < total):
            raise CargaInvalida("seq fora do intervalo")
        if not isinstance(dados, str) or len(dados) > self.TAM_MAX:
            raise CargaInvalida("dados inválidos")
        if self._total is not None and total != self._total:
            raise CargaInvalida("total divergente")
        self._total = total
        self._pecas[seq] = dados
        if len(self._pecas) != total:
            return None
        remontado = "".join(self._pecas[i] for i in range(total))
        self._pecas = {}
        self._total = None
        return remontado


class Provisionador:
    """Orquestra o provisionamento: código, validação, rede e persistência."""

    ESTADO_AGUARDANDO = "aguardando_codigo"
    ESTADO_APLICANDO = "aplicando_rede"
    ESTADO_OK = "ok"
    ESTADO_ERRO = "erro"

    def __init__(
        self,
        *,
        rede: object,
        tela: object,
        caminho_env: Path = ARQUIVO_ENV_PADRAO,
        uid: str = "",
        nome: str = "dispenser",
        relogio: Callable[[], float] | None = None,
        gerar: Callable[[], str] | None = None,
    ) -> None:
        self._rede = rede
        self._tela = tela
        self._caminho_env = Path(caminho_env)
        self._uid = uid
        self._nome = nome
        self._relogio = relogio or _relogio_interno
        self._gerar = gerar or _gerar_codigo
        self._codigo: str | None = None
        self._expira_em: float = 0.0
        self._provisionado = self._caminho_env.exists()
        self._estado = self.ESTADO_OK if self._provisionado else self.ESTADO_AGUARDANDO
        self._erro = ""
        self._ao_mudar: Callable[[], None] | None = None
        if not self._provisionado:
            self._novo_codigo()

    @property
    def provisionado(self) -> bool:
        return self._provisionado

    @property
    def estado(self) -> str:
        return self._estado

    def definir_ao_mudar(self, fn: Callable[[], None]) -> None:
        self._ao_mudar = fn

    def identidade(self) -> dict:
        return {"uid": self._uid, "nome": self._nome}

    def status(self) -> dict:
        corpo: dict = {"estado": self._estado}
        if self._estado == self.ESTADO_ERRO:
            corpo["erro"] = self._erro
        return corpo

    def reiniciar(self) -> None:
        """Reentra no modo provisionamento (botão/CLI)."""
        self._provisionado = False
        self._novo_codigo()

    def codigo_valido(self, codigo: str) -> bool:
        if self._codigo is None or self._relogio() >= self._expira_em:
            return False
        return secrets.compare_digest(self._codigo, codigo)

    def receber_carga(self, carga: object) -> bool:
        """Valida código+carga, aplica a rede e persiste a configuração."""
        if self._provisionado:
            self._falhar("já provisionado")
            return False
        try:
            dados = validar_carga(carga)
        except CargaInvalida as erro:
            self._falhar(f"carga inválida: {erro}")
            return False
        if not self.codigo_valido(dados.codigo):
            self._falhar("código inválido ou expirado")
            return False
        self._estado = self.ESTADO_APLICANDO
        self._emitir()
        if not self._rede.conectar_wifi(dados.ssid, dados.senha):
            self._falhar("falha no Wi-Fi")
            return False
        if not self._escrever_env(dados.firebase):
            self._falhar("falha ao gravar configuração")
            return False
        self._provisionado = True
        self._codigo = None
        self._estado = self.ESTADO_OK
        self._tela.mostrar("Provisionado: reiniciando o serviço principal...")
        self._emitir()
        return True

    def _novo_codigo(self) -> None:
        self._codigo = self._gerar()
        self._expira_em = self._relogio() + VALIDADE_CODIGO_S
        self._estado = self.ESTADO_AGUARDANDO
        self._tela.mostrar(f"Digite no app o código: {self._codigo}")
        self._emitir()

    def _falhar(self, motivo: str) -> None:
        self._erro = motivo
        self._estado = self.ESTADO_ERRO
        self._emitir()

    def _escrever_env(self, firebase: ConfigFirebase) -> bool:
        try:
            self._caminho_env.parent.mkdir(parents=True, exist_ok=True)
            self._caminho_env.write_text(
                f"FIREBASE_PROJECT_ID={firebase.project_id}\n"
                f"DISPENSER_FIREBASE_API_KEY={firebase.api_key}\n"
                f"DISPENSER_USER_ID={firebase.usuario_id}\n",
                encoding="utf-8",
            )
            os.chmod(self._caminho_env, 0o600)
            return True
        except OSError:
            return False

    def _emitir(self) -> None:
        if self._ao_mudar is not None:
            self._ao_mudar()


def _relogio_interno() -> float:
    import time

    return time.time()


def _gerar_codigo() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"