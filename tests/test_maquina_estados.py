"""Testes da máquina de estados: todos os cenários de docs/spec/03-fluxo-dose.md."""

from core.config import Config
from core.maquina_estados import Acao, Contexto, Fase, processar


def _ctx(tentativas=0, slot=None):
    return Contexto(nome="Losartana", dosagem="50mg", slot=slot, tentativas=tentativas)


def _acao(acoes, tipo):
    return next(a for a in acoes if a.tipo == tipo)


def _tem_acao(acoes, tipo):
    return any(a.tipo == tipo for a in acoes)


def test_fluxo_feliz_completo():
    cfg = Config()
    fase, acoes, tent = processar(Fase.AGUARDANDO, _ctx(), cfg, "horario_chegou")
    assert fase == Fase.ALARME
    assert tent == 0
    assert _acao(acoes, "buzzer").dados == {"padrao": "dose"}
    assert _acao(acoes, "led").dados == {"slot": None, "estado": "on"}
    assert _acao(acoes, "tela").dados["chave"] == "hora_remedio"

    fase, acoes, tent = processar(fase, _ctx(slot=2), cfg, "ok")
    assert fase == Fase.AGUARDANDO_GAVETA
    assert _tem_acao(acoes, "parar_buzzer")
    assert _acao(acoes, "tela").dados["chave"] == "abra_gaveta"

    fase, acoes, tent = processar(fase, _ctx(slot=2), cfg, "gaveta_aberta")
    assert fase == Fase.GAVETA_ABERTA
    assert _acao(acoes, "tela").dados == {"chave": "retire_medicamento", "slot": 2}

    fase, acoes, tent = processar(fase, _ctx(slot=2), cfg, "slot_ausente")
    assert fase == Fase.MEDICAMENTO_RETIRADO
    assert _acao(acoes, "tela").dados == {"chave": "tome_e_ok"}

    fase, acoes, tent = processar(fase, _ctx(slot=2), cfg, "ok")
    assert fase == Fase.AGUARDANDO_RETORNO
    registrar = _acao(acoes, "registrar")
    assert registrar.dados == {"tipo": "dose_tomada"}
    assert _acao(acoes, "tela").dados["chave"] == "devolva_slot"

    fase, acoes, tent = processar(fase, _ctx(slot=2), cfg, "retorno_ok")
    assert fase == Fase.CONCLUIDA
    assert _acao(acoes, "registrar").dados == {"tipo": "dose_concluida"}
    assert _acao(acoes, "tela").dados["chave"] == "tudo_certo"
    assert _aco_apagar_led(acoes) == 2


def _aco_apagar_led(acoes):
    return _acao(acoes, "apagar_led").dados["slot"]


def test_alarme_sem_resposta_repeticao_e_perdida():
    cfg = Config(max_tentativas=3)
    fase = Fase.AGUARDANDO
    tent = 0
    fase, _, tent = processar(fase, _ctx(tentativas=tent), cfg, "horario_chegou")
    repetidas = []
    for _ in range(3):
        fase, acoes, tent = processar(fase, _ctx(tentativas=tent), cfg, "timeout_alarme")
        if fase == Fase.ALARME:
            repetidas.append(acoes)
        else:
            break
    assert fase == Fase.NAO_ATENDIDA
    assert _tem_acao(acoes, "notificar")
    assert _acao(acoes, "registrar").dados == {"tipo": "dose_perdida"}
    assert _tem_acao(acoes, "parar_buzzer")


def test_timeout_sem_resposta_dentro_do_limite_repete():
    cfg = Config(max_tentativas=5)
    fase = Fase.ALARME
    fase, acoes, tent = processar(fase, _ctx(tentativas=1), cfg, "timeout_alarme")
    assert fase == Fase.ALARME
    assert tent == 2
    assert _acao(acoes, "buzzer").dados == {"padrao": "dose"}


def test_timeout_gaveta_conta_nova_tentativa():
    cfg = Config(max_tentativas=2)
    fase, acoes, tent = processar(
        Fase.AGUARDANDO_GAVETA, _ctx(tentativas=0), cfg, "timeout_gaveta"
    )
    assert fase == Fase.ALARME  # volta para alarme (nova tentativa)
    assert tent == 1
    assert _acao(acoes, "buzzer").dados == {"padrao": "dose"}

    fase, acoes, tent = processar(fase, _ctx(tentativas=1), cfg, "ok")
    assert fase == Fase.AGUARDANDO_GAVETA
    assert tent == 1


def test_dose_perdida_pela_gaveta_nao_aberta():
    cfg = Config(max_tentativas=1)
    fase, acoes, tent = processar(
        Fase.AGUARDANDO_GAVETA, _ctx(tentativas=0), cfg, "timeout_gaveta"
    )
    assert fase == Fase.NAO_ATENDIDA
    assert tent == 1
    assert _acao(acoes, "registrar").dados == {"tipo": "dose_perdida"}


def test_medicamento_nao_devolvido_pendente_e_limite():
    cfg = Config()
    fase, acoes, tent = processar(
        Fase.AGUARDANDO_RETORNO, _ctx(tentativas=0), cfg, "timeout_retorno"
    )
    assert fase == Fase.RETORNO_PENDENTE
    assert tent == 0
    assert _acao(acoes, "buzzer").dados == {"padrao": "retorno"}
    assert _acao(acoes, "led").dados == {"slot": None, "estado": "on"}
    assert _acao(acoes, "tela").dados["chave"] == "aviso_retorno"

    fase, acoes, tent = processar(fase, _ctx(), cfg, "limite_retorno_excedido")
    assert fase == Fase.RETORNO_PENDENTE
    notificar = _acao(acoes, "notificar")
    assert notificar.dados == {"motivo": "nao_devolvido"}

    fase, acoes, tent = processar(fase, _ctx(slot=2), cfg, "retorno_ok")
    assert fase == Fase.CONCLUIDA
    assert _acao(acoes, "registrar").dados == {"tipo": "dose_concluida"}


def test_gaveta_aberta_fora_de_horario_permanece_aguardando():
    cfg = Config()
    fase, acoes, tent = processar(Fase.AGUARDANDO, _ctx(), cfg, "gaveta_aberta")
    assert fase == Fase.AGUARDANDO
    assert tent == 0
    assert _acao(acoes, "registrar").dados == {"tipo": "gaveta_fora_de_horario"}
    assert _acao(acoes, "led").dados == {"slot": -1, "estado": "pisca"}
    assert not _tem_acao(acoes, "buzzer")


def test_falha_de_sensor_vai_a_falha_sem_assumir_tomada():
    cfg = Config()
    fase, acoes, tent = processar(
        Fase.MEDICAMENTO_RETIRADO, _ctx(), cfg, "falha", {"codigo": "F003"}
    )
    assert fase == Fase.FALHA
    assert tent == 0
    assert _acao(acoes, "registrar").dados["tipo"] == "falha"
    assert not any(a.dados.get("tipo") == "dose_tomada" for a in acoes)
    assert _acao(acoes, "tela").dados["chave"] == "falha"
    assert _acao(acoes, "tela").dados["codigo"] == "F003"
    assert _acao(acoes, "notificar").dados == {
        "motivo": "falha",
        "codigo": "F003",
    }


def test_falha_em_qualquer_fase():
    cfg = Config()
    for fase in (Fase.ALARME, Fase.GAVETA_ABERTA, Fase.RETORNO_PENDENTE):
        nova, acoes, _ = processar(fase, _ctx(), cfg, "falha", {"codigo": "F001"})
        assert nova == Fase.FALHA
    from_aguardando, _, _ = processar(Fase.AGUARDANDO, _ctx(), cfg, "falha", {"codigo": "F002"})
    assert from_aguardando == Fase.FALHA


def test_terminal_nao_reabre_idempotencia():
    cfg = Config()
    for terminal in (Fase.CONCLUIDA, Fase.NAO_ATENDIDA):
        nova, acoes, tent = processar(terminal, _ctx(tentativas=0), cfg, "horario_chegou")
        assert nova == terminal
        assert acoes == []


def test_evento_repetido_em_fase_errada_ignorado():
    cfg = Config()
    fase, acoes, tent = processar(Fase.ALARME, _ctx(), cfg, "gaveta_aberta")
    assert fase == Fase.ALARME
    assert acoes == []
    fase, acoes, tent = processar(Fase.GAVETA_ABERTA, _ctx(), cfg, "gaveta_aberta")
    assert fase == Fase.GAVETA_ABERTA
    assert acoes == []
    fase, acoes, tent = processar(Fase.AGUARDANDO_RETORNO, _ctx(), cfg, "slot_ausente")
    assert fase == Fase.AGUARDANDO_RETORNO
    assert acoes == []
    # duplo 'ok' no mesma fase de retirada
    fase, acoes, tent = processar(Fase.MEDICAMENTO_RETIRADO, _ctx(), cfg, "ok")
    assert fase == Fase.AGUARDANDO_RETORNO
    fase2, acoes2, _ = processar(fase, _ctx(), cfg, "ok")
    assert fase2 == Fase.AGUARDANDO_RETORNO
    assert acoes2 == []


def test_retorno_confirmado_sem_tomar_nao_existe():
    # não existe caminho direto AGUARDANDO -> CONCLUIDA
    cfg = Config()
    fase, acoes, _ = processar(Fase.AGUARDANDO, _ctx(), cfg, "retorno_ok")
    assert fase == Fase.AGUARDANDO
    assert acoes == []