"""Caminhos, comandos e ambiente do painel de desenvolvimento.

O painel é uma ferramenta de apoio: roda o core e a UI como processos filhos,
sem `sudo`, sem systemd e sem tocar em `/var/lib/dispenser`. Todo o estado de
desenvolvimento fica em `dispenser/.run/`, que é ignorado pelo git.

O core sobe com a mesma configuração do roteiro manual: o `.env` da raiz é
carregado no ambiente do filho e os caminhos de estado apontam para `.run/`.
Credenciais herdadas do shell que abriu o painel continuam sendo removidas;
só o que está no `.env` (escolha explícita) chega ao core.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from core.agendador import abrev_dia_semana

#: Raiz do projeto `dispenser/` (este arquivo fica em `dispenser/painel/`).
RAIZ = Path(__file__).resolve().parent.parent
#: Estado local do painel; `*.db` e `.run/` estão no .gitignore.
DIR_DEV = RAIZ / ".run"
PASTA_UI = RAIZ / "ui"
ARQUIVO_AGENDA_DEMO = DIR_DEV / "agenda-demo.json"
#: Configuração de dev na raiz do projeto (gitignored, permissão 600). Quando
#: existe, o core de dev lê dela o backend real (Firestore) e os caminhos de
#: estado — mesmo formato `CHAVE=valor` que o provisionamento BLE grava no Pi,
#: pelo mesmo leitor (`DISPENSER_ENV_PATH`). Vazio/em branco: modo demo.
ARQUIVO_ENV_DEV = RAIZ / ".env"

#: Variáveis que apontam para o backend/produção. O painel as remove do
#: ambiente herdado do shell; o backend só entra pelo `.env` do projeto.
CHAVES_SENSIVEIS = (
    "FIREBASE_PROJECT_ID",
    "DISPENSER_USER_ID",
    "DISPENSER_FIREBASE_API_KEY",
    "DISPENSER_CREDENTIALS_PATH",
)

#: Variáveis do systemd que não podem vazar para um core iniciado à mão:
#: `NOTIFY_SOCKET` faria o processo mandar READY/WATCHDOG para o systemd da
#: sessão errada.
CHAVES_DO_SISTEMA = (
    "NOTIFY_SOCKET",
    "WATCHDOG_USEC",
    "WATCHDOG_PID",
    "JOURNAL_STREAM",
    "INVOCATION_ID",
)

#: Prefixo das variáveis que a UI consome (detecção de consumo, ADR 016).
#: Só elas passam do `.env` para a UI: o resto é do core/backend.
PREFIXO_VISAO = "DISPENSER_VISAO_"


def preparar_diretorio_dev() -> Path:
    """Cria `.run/` com permissão restrita e devolve o caminho."""
    DIR_DEV.mkdir(mode=0o700, parents=True, exist_ok=True)
    return DIR_DEV


def _python_do_projeto() -> Path:
    venv = RAIZ / ".venv" / "bin" / "python"
    return venv if venv.exists() else Path(sys.executable)


def comando_core() -> list[str]:
    """Comando do core, preferindo o venv do projeto quando ele existe."""
    return [str(_python_do_projeto()), "-m", "core.dispenser_main"]


#: Nome do diretório de build do Flutter por arquitetura (`platform.machine()`).
_ARQUITETURA_FLUTTER = {
    "aarch64": "arm64",
    "arm64": "arm64",
    "x86_64": "x64",
    "amd64": "x64",
}


def binario_ui() -> Path:
    """Executável da UI já compilada (bundle debug do Flutter para Linux).

    Equivale a `./build/linux/<arq>/debug/bundle/dispenser_ui`, com `<arq>`
    escolhido pela máquina atual (`arm64` no Raspberry Pi, `x64` no PC). Se o
    bundle dessa arquitetura não existir mas houver outro, usa o encontrado.
    """
    base = PASTA_UI / "build" / "linux"
    arq = _ARQUITETURA_FLUTTER.get(platform.machine().lower(), "arm64")
    preferido = base / arq / "debug" / "bundle" / "dispenser_ui"
    if preferido.exists():
        return preferido
    for candidato in sorted(base.glob("*/debug/bundle/dispenser_ui")):
        return candidato
    return preferido


def comando_ui() -> list[str]:
    """Comando da UI: o binário compilado, sem `flutter run`."""
    return [str(binario_ui())]


def _ambiente_limpo() -> dict[str, str]:
    """Copia o ambiente e remove o que não pode chegar aos processos filhos."""
    ambiente = os.environ.copy()
    for chave in (*CHAVES_SENSIVEIS, *CHAVES_DO_SISTEMA):
        ambiente.pop(chave, None)
    return ambiente


def ler_env_dev(caminho: Path | None = None) -> dict[str, str]:
    """Lê `.env` (`CHAVE=valor`) como o `source .env` do shell faria.

    Mesmas regras do leitor do core: ignora linhas vazias, comentários e linhas
    sem `=`. Aspas simples/duplas ao redor do valor são removidas. Arquivo
    ausente ou ilegível devolve `{}` (modo demo).
    """
    arquivo = ARQUIVO_ENV_DEV if caminho is None else caminho
    try:
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    valores: dict[str, str] = {}
    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        if linha.startswith("export "):
            linha = linha[len("export "):].lstrip()
        chave, valor = linha.split("=", 1)
        chave, valor = chave.strip(), valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if chave:
            valores[chave] = valor
    return valores


def ambiente_core() -> dict[str, str]:
    """Ambiente do core: o `.env` carregado e os caminhos apontando a `.run/`.

    Reproduz o roteiro manual (`sed` nos caminhos + `source .env` +
    `python -m core.dispenser_main`): as variáveis do `.env` entram no
    ambiente do filho e os caminhos de estado são sempre os do projeto atual
    (`RAIZ/.run`), sem editar o arquivo — o `.env` pode ter sido escrito em
    outra máquina.
    """
    ambiente = _ambiente_limpo()
    ambiente.pop("DISPENSER_AGENDA_JSON", None)
    ambiente.update(ler_env_dev())
    ambiente.update(
        {
            "PYTHONUNBUFFERED": "1",
            "DISPENSER_DB_PATH": str(DIR_DEV / "state.db"),
            "DISPENSER_SOCKET": str(DIR_DEV / "core.sock"),
            "DISPENSER_LOCK_PATH": str(DIR_DEV / "core.lock"),
            "DISPENSER_ENV_PATH": str(ARQUIVO_ENV_DEV),
        }
    )
    return ambiente


#: Ajustes da UI Flutter em hardware sem GPU (Raspberry Pi): renderização por
#: software e Impeller desligado.
_AMBIENTE_RENDER_UI = {
    "LIBGL_ALWAYS_SOFTWARE": "1",
    "FLUTTER_ENGINE_SWITCHES": "1",
    "FLUTTER_ENGINE_SWITCH_1": "enable-impeller=false",
}


def ambiente_ui() -> dict[str, str]:
    """Ambiente da UI: renderização por software, socket do core de dev e visão.

    Só as `DISPENSER_VISAO_*` do `.env` entram: o painel permite exercitar o
    preview/detecção do passo 4 sem exportar variáveis à mão, sem vazar as
    credenciais do backend para a UI.
    """
    ambiente = _ambiente_limpo()
    ambiente.update(_AMBIENTE_RENDER_UI)
    for chave, valor in ler_env_dev().items():
        if chave.startswith(PREFIXO_VISAO):
            ambiente[chave] = valor
    ambiente["DISPENSER_SOCKET"] = str(DIR_DEV / "core.sock")
    return ambiente


@dataclass(frozen=True)
class AgendaDemo:
    """Resultado da agenda de exemplo: onde ficou e para que horário."""

    caminho: Path
    horario: str


def gerar_agenda_demo(
    destino: Path = ARQUIVO_AGENDA_DEMO,
    *,
    agora: datetime | None = None,
) -> AgendaDemo:
    """Grava uma agenda de uma dose para daqui a 2 minutos.

    O formato é o mesmo que o app envia em `Medicamentos` e que o core lê de
    `DISPENSER_AGENDA_JSON` (recorrência semanal no dia atual). Não altera o
    core: é só um arquivo de exemplo em `.run/`.
    """
    momento = (agora or datetime.now()) + timedelta(minutes=2)
    horario = momento.strftime("%H:%M")
    dados = [
        {
            "id": "med-demo",
            "nome": "Medicamento de exemplo",
            "dosagem": "1 comprimido",
            "dias": [
                {
                    "dia_semana": abrev_dia_semana(momento.date()),
                    "horario": [horario],
                }
            ],
        }
    ]
    destino.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return AgendaDemo(caminho=destino, horario=horario)


def avisos_ambiente() -> list[str]:
    """Lista avisos do rodapé: dependências ausentes e backend configurado."""
    avisos: list[str] = []
    if not (RAIZ / ".venv" / "bin" / "python").exists():
        avisos.append("venv")
    if not binario_ui().exists():
        avisos.append("ui_build")
    if ARQUIVO_ENV_DEV.exists():
        # Backend real ligado no dev é decisão consciente — e precisa ser
        # visível: a partir daqui doses sincronizam com o Firestore de
        # verdade (dados de saúde, LGPD).
        avisos.append("backend")
    return avisos
