"""Testes do sync: fila outbox, idempotência por chave e reenvio."""

from core.sync import SyncService


def test_enfileira_evento_e_idempotencia(db):
    sync = SyncService(db)
    sync.enfileirar_evento("m1|2026-09-19|08:00", "dose_tomada", {"horario_real": "x"})
    sync.enfileirar_evento("m1|2026-09-19|08:00", "dose_tomada", {"horario_real": "y"})
    pendentes = sync.pendentes()
    assert len(pendentes) == 1
    assert pendentes[0]["tipo"] == "dose_tomada"


def test_fila_preserva_ordem_e_tipos(db):
    sync = SyncService(db)
    for tipo in ("dose_tomada", "dose_concluida", "dose_perdida"):
        sync.enfileirar_evento("m1|2026-09-19|08:00", tipo, {})
    assert [p["tipo"] for p in sync.pendentes()] == [
        "dose_tomada",
        "dose_concluida",
        "dose_perdida",
    ]


def test_reenvio_marca_apenas_os_enviados_com_sucesso(db):
    sync = SyncService(db)
    sync.enfileirar_evento("a", "dose_tomada", {})
    sync.enfileirar_evento("b", "dose_perdida", {})
    sync.enfileirar_evento("c", "dose_tomada", {})

    def envio_com_mais_tempo(item):
        return item["ocorrencia_id"] != "b"

    enviados = sync.envia_emitidos(envio_com_mais_tempo)
    assert enviados == 2
    restantes = sync.pendentes()
    assert [p["ocorrencia_id"] for p in restantes] == ["b"]


def test_envio_que_falha_nao_perde_item(db):
    sync = SyncService(db)
    sync.enfileirar_evento("a", "dose_tomada", {})

    def envio_falho(_item):
        raise RuntimeError("rede fora")

    assert sync.envia_emitidos(envio_falho) == 0
    assert sync.pendentes() != []