"""Testes do módulo puro de visão (contagem e NDJSON).

Roda sem câmera e sem ultralytics: `detecta_pill/visao.py` não importa as
dependências pesadas. O contrato aqui é o que a UI Flutter lê
(`ui/lib/src/visao.dart`).
"""

from detecta_pill import visao


def _deteccao(classe_id: int, conf: float = 0.9):
    # formato do script de câmera: x1,y1,x2,y2,classe_id,conf
    return (0, 0, 10, 10, classe_id, conf)


NOMES = {0: "no_pill", 1: "pill"}


def _nome(classe_id):
    return NOMES[classe_id]


def test_conta_pill_e_no_pill():
    deteccoes = [_deteccao(1), _deteccao(1), _deteccao(0)]
    assert visao.contar_classes(deteccoes, _nome) == {"pill": 2, "no_pill": 1}


def test_sem_deteccoes_zera_as_duas_classes():
    assert visao.contar_classes([], _nome) == {"pill": 0, "no_pill": 0}


def test_ignora_classes_desconhecidas():
    deteccoes = [_deteccao(1), _deteccao(7)]
    assert visao.contar_classes(deteccoes, lambda cid: {1: "pill", 7: "outro"}[cid]) == {
        "pill": 1,
        "no_pill": 0,
    }


def test_linha_ndjson_traz_sempre_as_duas_chaves():
    assert visao.linha_ndjson({"pill": 3}) == '{"pill": 3, "no_pill": 0}'
    assert visao.linha_ndjson({"no_pill": 2}) == '{"pill": 0, "no_pill": 2}'
    assert visao.linha_ndjson({}) == '{"pill": 0, "no_pill": 0}'


def test_linha_ndjson_e_json_de_uma_linha():
    import json

    linha = visao.linha_ndjson({"pill": 1, "no_pill": 1})
    assert "\n" not in linha
    assert json.loads(linha) == {"pill": 1, "no_pill": 1}


def test_linha_ndjson_sem_quadro_nao_traz_frame():
    import json

    linha = json.loads(visao.linha_ndjson({"pill": 1, "no_pill": 0}))
    assert "frame" not in linha


def test_linha_ndjson_com_quadro_traz_frame_base64_de_jpeg():
    import base64
    import json

    jpeg = b"\xff\xd8\xff\xe0" + b"conteudo" + b"\xff\xd9"
    quadro = base64.b64encode(jpeg).decode("ascii")

    linha = json.loads(visao.linha_ndjson({"pill": 2}, quadro))

    assert linha["pill"] == 2
    assert linha["no_pill"] == 0
    assert base64.b64decode(linha["frame"]) == jpeg


def test_linha_ndjson_com_quadro_vazio_omite_frame():
    import json

    assert "frame" not in json.loads(visao.linha_ndjson({}, ""))
    assert "frame" not in json.loads(visao.linha_ndjson({}, None))
