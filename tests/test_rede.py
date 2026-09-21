"""Testes da interface de rede (nmcli + fallback netplan + simulada)."""

from __future__ import annotations

from rede.rede import NETPLAN_ALVO, RedeLinux, RedeSimulada


def _executor_fake(resultados: dict[str, int]):
    def executor(comando: list[str], timeout: int) -> int:
        chave = " ".join(comando)
        return resultados.get(chave, 1)

    return executor


def test_rede_simulada_registra_chamadas():
    rede = RedeSimulada(sucesso=True, ping=False)
    assert rede.conectar_wifi("Rede", "senha") is True
    assert rede.pingar() is False
    assert rede.conexoes == [("Rede", "senha")]


def test_nmcli_sucede_sem_usar_netplan(monkeypatch, tmp_path):
    executer = _executor_fake(
        {
            "nmcli -t device wifi connect Rede password senha": 0,
        }
    )
    monkeypatch.setattr("rede.rede.NETPLAN_ALVO", tmp_path / "netplan.yaml")
    rede = RedeLinux(executor=executer)
    assert rede.conectar_wifi("Rede", "senha") is True
    assert not (tmp_path / "netplan.yaml").exists()


def test_nmcli_falha_e_cai_no_netplan(monkeypatch, tmp_path):
    alvo = tmp_path / "netplan.yaml"
    executer = _executor_fake(
        {
            "nmcli -t device wifi connect Rede password senha": 1,
            "netplan apply": 0,
        }
    )
    monkeypatch.setattr("rede.rede.NETPLAN_ALVO", alvo)
    rede = RedeLinux(executor=executer)
    assert rede.conectar_wifi("Rede", "senha") is True
    conteudo = alvo.read_text(encoding="utf-8")
    assert "Minha" not in conteudo  # sem nomes de app aqui
    assert "Rede" in conteudo
    assert "dhcp4: true" in conteudo


def test_tudo_falha_retorna_falso(monkeypatch, tmp_path):
    executer = _executor_fake(
        {
            "nmcli -t device wifi connect Rede password senha": 1,
            "netplan apply": 1,
        }
    )
    monkeypatch.setattr("rede.rede.NETPLAN_ALVO", tmp_path / "netplan.yaml")
    rede = RedeLinux(executor=executer)
    assert rede.conectar_wifi("Rede", "senha") is False


def test_pingar(monkeypatch):
    executer = _executor_fake({"ping -c 1 -W 3 8.8.8.8": 0})
    rede = RedeLinux(executor=executer)
    assert rede.pingar() is True