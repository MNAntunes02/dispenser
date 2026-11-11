"""Strings do painel de desenvolvimento em português do Brasil.

Regra 9 do AGENTS.md: toda a interface com o usuário final fica centralizada
num único arquivo. O painel é ferramenta de desenvolvimento, mas as mensagens
que aparecem na janela também são pt-BR e moram aqui.
"""

from __future__ import annotations

TEXTOS: dict[str, str] = {
    # Janela e cabeçalho
    "titulo": "Dispensador — painel de desenvolvimento",
    "subtitulo": (
        "Inicia o core e a UI Flutter neste computador, sem sudo, e acompanha "
        "os logs dos dois."
    ),
    "servico_core": "Core (dispenser-core)",
    "servico_ui": "UI Flutter (dispenser-ui)",
    # Botões
    "iniciar": "Iniciar",
    "parar": "Parar",
    "reiniciar": "Reiniciar",
    "iniciar_tudo": "Iniciar tudo",
    "parar_tudo": "Parar tudo",
    "limpar": "Limpar",
    "salvar": "Salvar log…",
    # Estados
    "estado_parado": "Parado",
    "estado_iniciando": "Iniciando…",
    "estado_rodando": "Rodando (PID {pid})",
    "estado_parando": "Parando…",
    "estado_encerrado": "Encerrado (código {codigo})",
    "estado_encerrado_sem_codigo": "Encerrado",
    # Logs e filtros
    "log_core": "Core",
    "log_ui": "UI",
    "filtrar": "Filtrar:",
    "auto_rolagem": "Auto-rolagem",
    # Agenda de demonstração
    "agenda_demo": "Agenda de demonstração (dose em 2 min)",
    "agenda_demo_gerada": "agenda de demonstração: dose às {horario}",
    # Simulador de hardware (ADR 015)
    "simulador": "Simulador de hardware",
    "simulador_dica": (
        "Injeta eventos de sensor no core pela ponte simulada; sem efeito "
        "com hardware real."
    ),
    "simular_abrir_gaveta": "Abrir gaveta",
    "simular_fechar_gaveta": "Fechar gaveta",
    "simular_retirar": "Retirar medicamento",
    "simular_devolver": "Devolver medicamento",
    "simular_slot": "Slot:",
    "simulado": "simulação enviada ao core: {acao}",
    "simulado_slot": "simulação enviada ao core: {acao} (slot {slot})",
    "erro_simular": "falha ao enviar simulação: {erro}",
    # Mensagens do gerenciador de processos
    "ja_rodando": "{servico} já está rodando (PID {pid})",
    "falha_iniciar": "falha ao iniciar: {erro}",
    "processo_iniciado": "iniciado (PID {pid})",
    "processo_parado": "parado",
    "processo_encerrado": "encerrado (código {codigo})",
    "processo_parando": "parando (SIGTERM)…",
    "processo_escalando": "não encerrou com SIGTERM; enviando SIGKILL",
    "processo_teimoso": "processo não encerrou nem com SIGKILL",
    "erro_parar": "erro ao parar: {erro}",
    "erro_reiniciar": "erro ao reiniciar: {erro}",
    # Rodapé
    "pasta_dev": "Dados de dev: {caminho}",
    "socket_core": "Socket: {caminho}",
    "aviso_venv": "venv do projeto não encontrado; usando o Python atual.",
    "aviso_ui_build": (
        "UI não compilada (ui/build/linux/<arq>/debug/bundle/dispenser_ui)."
    ),
    "aviso_backend": (
        "backend real configurado (.env): o core vai sincronizar com o "
        "Firestore — dados de saúde reais."
    ),
    # Diálogos
    "titulo_fechar": "Fechar painel",
    "aviso_fechar": "Parar os serviços iniciados pelo painel e fechar?",
    "titulo_erro": "Erro",
    "erro_salvar": "Não foi possível salvar o log:\n{erro}",
    "titulo_log_salvo": "Log salvo",
    "log_salvo": "Log salvo em:\n{caminho}",
    "tipo_log": "Arquivo de log",
    "tipo_todos": "Todos os arquivos",
    # Dicas de diagnóstico
    "dica_codigo_3": "outro core já está rodando com este banco",
    "dica_flutter_ausente": "instale o Flutter ou ajuste o PATH",
}


def texto(chave: str, **valores: object) -> str:
    """Formata uma string do dicionário, mantendo um único ponto de tradução."""
    return TEXTOS[chave].format(**valores)
