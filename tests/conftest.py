# Unionfixtures e helpers compartilhados dos testes do dispensador.

import pytest

from core.armazenamento import Database
from hardware.bridge.bridge_simulada import PonteSimulada


@pytest.fixture
def db(tmp_path):
    banco = Database(tmp_path / "test.db")
    banco.conectar()
    yield banco
    banco.fechar()


@pytest.fixture
def ponte_simulada():
    ponte = PonteSimulada(slots=4)
    ponte.conectar()
    yield ponte
    ponte.desconectar()