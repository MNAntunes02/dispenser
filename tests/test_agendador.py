"""Testes do agendador: recorrência, virada de dia, simultâneas, regras do app."""

from datetime import date

from core.agendador import Agendador, abrev_dia_semana


def _med(**extra):
    base = {"id": "med1", "nome": "Medicamento", "dosagem": "10mg", "dias": []}
    base.update(extra)
    return base


def _meds_diarios(horarios):
    return [
        _med(
            id="med1",
            nome="Losartana",
            dias=[{"dia_semana": "sáb", "horario": horarios}],
        )
    ]


def test_abrev_dia_semana_pt_br():
    assert abrev_dia_semana(date(2026, 9, 19)) == "sáb"  # sábado
    assert abrev_dia_semana(date(2026, 9, 20)) == "dom"  # domingo
    assert abrev_dia_semana(date(2026, 9, 21)) == "seg"  # segunda


def test_ocorrencia_do_dia_correto():
    meds = [
        _med(
            id="m1",
            nome="Losartana",
            dosagem="50mg",
            dias=[{"dia_semana": "sáb", "horario": ["08:00", "20:00"]}],
        )
    ]
    ocorrencias = Agendador().ocorrencias_do_dia(meds, date(2026, 9, 19))
    assert len(ocorrencias) == 2
    assert [o.horario for o in ocorrencias] == ["08:00", "20:00"]
    assert ocorrencias[0].medicamento_nome == "Losartana"
    assert ocorrencias[0].dosagem == "50mg"
    assert ocorrencias[0].slot is None


def test_dia_diferente_nao_gera_ocorrencia():
    meds = _meds_diarios(["08:00"])
    assert Agendador().ocorrencias_do_dia(meds, date(2026, 9, 21)) == []


def test_id_deterministico_e_virada_de_dia():
    meds = _meds_diarios(["08:00"])
    sab = Agendador().ocorrencias_do_dia(meds, date(2026, 9, 19))
    sab_2 = Agendador().ocorrencias_do_dia(meds, date(2026, 9, 12))
    assert sab[0].id == "med1|2026-09-19|08:00"
    assert sab_2[0].id == "med1|2026-09-12|08:00"
    assert sab[0].id != sab_2[0].id


def test_horario_simples_normaliza():
    meds = [
        _med(
            id="m1",
            dias=[{"dia_semana": "sáb", "horario": ["8:05"]}],
        )
    ]
    ocorrencias = Agendador().ocorrencias_do_dia(meds, date(2026, 9, 19))
    assert ocorrencias[0].horario == "08:05"


def test_horario_invalido_ignorado():
    meds = [_med(id="m1", dias=[{"dia_semana": "sáb", "horario": ["aa:bb", "", "25:00"]}])]
    assert Agendador().ocorrencias_do_dia(meds, date(2026, 9, 19)) == []


def test_doses_simultaneas_ordenadas_por_horario():
    from datetime import date as _d

    meds = [
        _med(
            id="a",
            nome="Remédio A",
            dias=[{"dia_semana": "sáb", "horario": ["09:00"]}],
        ),
        _med(
            id="b",
            nome="Remédio B",
            dias=[{"dia_semana": "sáb", "horario": ["09:00"]}],
        ),
        _med(
            id="c",
            nome="Remédio C",
            dias=[{"dia_semana": "sáb", "horario": ["07:30"]}],
        ),
    ]
    ocorrencias = Agendador().ocorrencias_do_dia(meds, _d(2026, 9, 19))
    assert [o.medicamento for o in ocorrencias] == ["c", "a", "b"]


def test_med_sem_dias_ou_horarios_ignorado():
    meds = [_med(id="m1", dias=[]), _med(id="m2", dias=[{"dia_semana": "dom", "horario": []}])]
    assert Agendador().ocorrencias_do_dia(meds, date(2026, 9, 19)) == []