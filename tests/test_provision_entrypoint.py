"""Testes de entrada do provisionamento: env 600 e UID da credencial."""

from __future__ import annotations

import json
import os

from core.dispenser_main import _carregar_env_arquivo
from core.provision_main import _ler_uid


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