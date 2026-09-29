"""Testes de entrada do provisionamento: env 600 e UID da credencial.

Cobre também a recarga por SIGHUP (Fase 7): o app pareia com o core já no ar e
o aparelho precisa passar a sincronizar sem reiniciar — e sem trocar uma agenda
que funciona por uma incompleta.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.armazenamento import Database
from core.config import Config
from core.coordenador import AgendaMemo, Coordenador
from core.dispenser_main import (
    _aplicar_provisionamento,
    _carregar_env_arquivo,
)
from core.provision_main import _ler_uid
from core.sync import FonteAgendaLocal
from hardware.bridge.bridge_simulada import PonteSimulada


def test_carregar_env_arquivo(monkeypatch, tmp_path):
    env = tmp_path / "dispenser.env"
    env.write_text(
        "FIREBASE_PROJECT_ID=app\n"
        "DISPENSER_FIREBASE_API_KEY=chave\n"
        "DISPENSER_USER_ID=usuario\n"
        "# comentário\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DISPENSER_ENV_PATH", str(env))
    _carregar_env_arquivo()
    assert os.environ["FIREBASE_PROJECT_ID"] == "app"
    assert os.environ["DISPENSER_FIREBASE_API_KEY"] == "chave"
    assert os.environ["DISPENSER_USER_ID"] == "usuario"


def test_carregar_env_arquivo_respeita_variavel_existente(monkeypatch, tmp_path):
    env = tmp_path / "dispenser.env"
    env.write_text("FIREBASE_PROJECT_ID=arquivo\n", encoding="utf-8")
    monkeypatch.setenv("DISPENSER_ENV_PATH", str(env))
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "ambiente")
    _carregar_env_arquivo()
    assert os.environ["FIREBASE_PROJECT_ID"] == "ambiente"


def test_carregar_env_arquivo_inexistente_e_silencioso(monkeypatch, tmp_path):
    monkeypatch.setenv("DISPENSER_ENV_PATH", str(tmp_path / "nao.existe.env"))
    _carregar_env_arquivo()


def test_ler_uid_da_credencial(tmp_path):
    credencial = tmp_path / "credencial.json"
    credencial.write_text(
        json.dumps({"email": "disp@x.com", "senha": "s", "uid": "uid-dispenser"}),
        encoding="utf-8",
    )
    assert _ler_uid(credencial) == "uid-dispenser"


def test_ler_uid_ausente_ou_invalido(tmp_path):
    sem_uid = tmp_path / "sem-uid.json"
    sem_uid.write_text(json.dumps({"email": "e", "senha": "s"}), encoding="utf-8")
    assert _ler_uid(sem_uid) == ""
    assert _ler_uid(tmp_path / "nao-existe.json") == ""


# --- recarga por SIGHUP (Fase 7) ---------------------------------------------


def _coordenador(tmp_path, db):
    coord = Coordenador(
        Config(), db, AgendaMemo([]), PonteSimulada()
    )
    coord.conectar()
    return coord


def _provisionamento_completo(monkeypatch, tmp_path) -> None:
    credencial = tmp_path / "credencial.json"
    credencial.write_text(
        json.dumps({"email": "disp@x.com", "senha": "s", "uid": "uid-d"}),
        encoding="utf-8",
    )
    env = tmp_path / "dispenser.env"
    env.write_text(
        "FIREBASE_PROJECT_ID=app\n"
        "DISPENSER_FIREBASE_API_KEY=chave\n"
        "DISPENSER_USER_ID=usuario\n"
        f"DISPENSER_CREDENTIALS_PATH={credencial}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DISPENSER_ENV_PATH", str(env))
    for chave in (
        "FIREBASE_PROJECT_ID",
        "DISPENSER_USER_ID",
        "DISPENSER_FIREBASE_API_KEY",
        "DISPENSER_CREDENTIALS_PATH",
    ):
        monkeypatch.delenv(chave, raising=False)


def test_sighup_troca_a_agenda_pela_nuvem(monkeypatch, tmp_path):
    _provisionamento_completo(monkeypatch, tmp_path)
    db = Database(tmp_path / "s.db")
    db.conectar()
    coord = _coordenador(tmp_path, db)
    try:
        assert _aplicar_provisionamento(coord, db) is True
        assert isinstance(coord.fonte_agenda, FonteAgendaLocal)
        # Com entrega configurada, a dose tomada chega ao cuidador.
        assert coord.tentar_envio() == 0  # fila vazia, mas o caminho existe
    finally:
        coord.finalizar()


def test_recarga_incompleta_mantem_a_agenda_que_funciona(monkeypatch, tmp_path):
    """Trocar uma agenda boa por uma vazia seria pior que esperar o app."""
    _provisionamento_completo(monkeypatch, tmp_path)
    db = Database(tmp_path / "s.db")
    db.conectar()
    coord = _coordenador(tmp_path, db)
    try:
        assert _aplicar_provisionamento(coord, db) is True
        # O app reescreve o arquivo pela metade (pareamento interrompido).
        Path(tmp_path / "dispenser.env").write_text(
            "FIREBASE_PROJECT_ID=app\n", encoding="utf-8"
        )
        assert _aplicar_provisionamento(coord, db) is False
        assert isinstance(coord.fonte_agenda, FonteAgendaLocal)
    finally:
        coord.finalizar()


def test_sem_arquivo_de_provisionamento_nao_muda_nada(monkeypatch, tmp_path):
    monkeypatch.setenv("DISPENSER_ENV_PATH", str(tmp_path / "nao.existe.env"))
    for chave in (
        "FIREBASE_PROJECT_ID",
        "DISPENSER_USER_ID",
        "DISPENSER_FIREBASE_API_KEY",
        "DISPENSER_CREDENTIALS_PATH",
    ):
        monkeypatch.delenv(chave, raising=False)
    db = Database(tmp_path / "s.db")
    db.conectar()
    coord = _coordenador(tmp_path, db)
    try:
        assert _aplicar_provisionamento(coord, db) is False
        assert not isinstance(coord.fonte_agenda, FonteAgendaLocal)
    finally:
        coord.finalizar()