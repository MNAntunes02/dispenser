"""Transporte com o backend do app (Firestore via REST).

Fase 3: credencial própria — usuário dedicado do Firebase Auth (email/senha);
token obtido por `identitytoolkit` e usado como Bearer no Firestore HTTP v1.
Lê `Medicamentos` (agenda) e registra `Historico` de `dose_tomada` com docId
determinístico (reenvio idempotente). A Fase 6 (ADR 010) soma a gravação de
avisos em `Notificacoes` (dose perdida, não devolvido, falha). Sem nomes de
medicamento em logs (LGPD).
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime

import requests

from core.textos import aviso_cuidador, plural_doses

_AUTH_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
_FIRESTORE = (
    "https://firestore.googleapis.com/v1/projects/{projeto}"
    "/databases/(default)/documents"
)


class ErroTransporte(Exception):
    """Falha tratável de rede/backend; a fila permanece pendente."""


class AutenticacaoFalhou(ErroTransporte):
    """Credenciais inválidas ou acesso negado pelo backend."""


def doc_historico_id(ocorrencia_id: str) -> str:
    """docId determinístico do Histórico para idempotência em reenvios."""
    dig = hashlib.sha1(ocorrencia_id.encode("utf-8")).hexdigest()[:20]
    return f"h{dig}"


#: Tipo de evento da fila (outbox) -> motivo do aviso (ADR 010; `relogio` na
#: Fase 7, ADR 012).
MOTIVO_AVISO = {
    "dose_perdida": "dose_perdida",
    "retorno_pendente": "nao_devolvido",
    "falha": "falha",
    "relogio": "relogio",
}

#: Avisos que podem sair sem ocorrência no banco: os dois descrevem a
#: situação do aparelho, não uma dose (Fase 6 e Fase 7).
_MOTIVOS_SEM_OCORRENCIA = ("falha", "relogio")


def motivo_aviso(tipo: str) -> str | None:
    """Motivo do aviso de um tipo de evento, ou `None` se não é aviso."""
    return MOTIVO_AVISO.get(tipo)


def doc_notificacao_id(ocorrencia_id: str, tipo: str) -> str:
    """docId determinístico do aviso: reenvio sobrescreve o mesmo doc."""
    dig = hashlib.sha1(f"{ocorrencia_id}|{tipo}".encode("utf-8")).hexdigest()[:20]
    return f"n{dig}"


def _dd_mm_aaaa(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def _hh_mm(valor: object) -> str | None:
    if not isinstance(valor, str):
        return None
    try:
        return datetime.fromisoformat(valor).strftime("%H:%M")
    except ValueError:
        return None


def _inteiro(valor: object) -> int:
    try:
        return int(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def registro_historico(ocorrencia: dict, payload: dict) -> dict | None:
    """Monta o doc `Historico` compatível com o app.

    Campos do app: `dia` (dd/MM/yyyy), `horario_previsto`, `horario_real`
    (HH:mm) e `nome`. Sem `horario_real` válido o registro não é enviado.
    """
    horario_real = _hh_mm(payload.get("horario_real"))
    if horario_real is None:
        return None
    return {
        "dia": _dd_mm_aaaa(ocorrencia["dia"]),
        "horario_previsto": ocorrencia["horario"],
        "horario_real": horario_real,
        "nome": ocorrencia["medicamento_nome"],
    }


def registro_notificacao(ocorrencia: dict | None, payload: dict) -> dict | None:
    """Monta o doc de aviso do cuidador (Fase 6, ADR 010).

    `ocorrencia` é `None` nos avisos que descrevem o aparelho, não uma dose:
    falha de sensor com ociosidade e relógio incorreto. Nesses casos o aviso
    sai com dia (+ código ou contagem) e sem nome nem horário. Motivo
    desconhecido, ou aviso de dose sem ocorrência, devolvem `None` (não envia).
    """
    tipo = str(payload.get("tipo", ""))
    motivo = motivo_aviso(tipo)
    if motivo is None:
        return None
    if ocorrencia is None and motivo not in _MOTIVOS_SEM_OCORRENCIA:
        return None

    dados: dict[str, str] = {"motivo": motivo}
    em = _hh_mm(payload.get("horario_real"))
    if payload.get("horario_real"):
        dados["em"] = str(payload["horario_real"])
    if em is not None:
        dados["horario_real"] = em

    if ocorrencia is not None:
        dados["dia"] = _dd_mm_aaaa(ocorrencia["dia"])
        dados["horario_previsto"] = ocorrencia["horario"]
        dados["nome"] = ocorrencia["medicamento_nome"]
    elif payload.get("dia"):
        dados["dia"] = _dd_mm_aaaa(str(payload["dia"]))

    if motivo == "falha":
        codigo = str(payload.get("codigo") or "?")
        dados["codigo"] = codigo
        dados["mensagem"] = aviso_cuidador(motivo, codigo=codigo)
    elif motivo == "relogio":
        doses = _inteiro(payload.get("doses"))
        dados["doses"] = str(doses)
        dados["mensagem"] = aviso_cuidador(
            motivo, dia=dados.get("dia", ""), doses=plural_doses(doses)
        )
    else:
        dados["mensagem"] = aviso_cuidador(
            motivo,
            nome=ocorrencia["medicamento_nome"],
            dosagem=ocorrencia["dosagem"],
            horario=ocorrencia["horario"],
        )
    return dados


def _valor(campo: dict) -> object:
    if not isinstance(campo, dict):
        return None
    if "stringValue" in campo:
        return campo["stringValue"]
    if "integerValue" in campo:
        try:
            return str(int(campo["integerValue"]))
        except ValueError:
            return campo["integerValue"]
    if "arrayValue" in campo:
        return _lista(campo["arrayValue"].get("values", []))
    if "mapValue" in campo:
        return _mapa(campo["mapValue"].get("fields", {}))
    return None


def _lista(valores: list) -> list:
    saida: list = []
    for valor in valores:
        if not isinstance(valor, dict):
            continue
        if "stringValue" in valor:
            saida.append(valor["stringValue"])
        elif "mapValue" in valor:
            saida.append(_mapa(valor["mapValue"].get("fields", {})))
        else:
            saida.append(_valor(valor))
    return saida


def _mapa(campos: dict) -> dict:
    return {chave: _valor(valor) for chave, valor in campos.items()}


def _id_do_doc(nome: str) -> str:
    return nome.rsplit("/", 1)[-1]


def normalizar_medicamentos(docs: list[dict]) -> list[dict]:
    """Converte documentos Firestore `Medicamentos` na forma do agendador."""
    medicamentos: list[dict] = []
    for doc in docs:
        campos = doc.get("fields", {})
        nome = _valor(campos.get("nome"))
        if not nome:
            continue
        dias: list[dict] = []
        for item in _valor(campos.get("dias")) or []:
            if not isinstance(item, dict):
                continue
            dia_semana = item.get("dia_semana")
            horario = [h for h in item.get("horario") or [] if isinstance(h, str)]
            if not dia_semana:
                continue
            dias.append({"dia_semana": dia_semana, "horario": horario})
        medicamentos.append(
            {
                "id": _id_do_doc(doc.get("name", "")),
                "nome": nome,
                "dosagem": _valor(campos.get("dosagem")) or "",
                "dias": dias,
            }
        )
    return medicamentos


class Transporte:
    """Interface do transporte com o backend (real e simulado)."""

    def ler_medicamentos(self) -> list[dict]:
        raise NotImplementedError

    def gravar_historico(self, ocorrencia_id: str, registro: dict) -> bool:
        raise NotImplementedError

    def gravar_notificacao(self, ocorrencia_id: str, tipo: str, aviso: dict) -> bool:
        raise NotImplementedError


class TransporteFirestore(Transporte):
    """Transporte real via REST do Firestore com credencial própria."""

    def __init__(
        self,
        *,
        projeto: str,
        usuario_id: str,
        api_key: str,
        email: str,
        senha: str,
        timeout: float = 15.0,
    ) -> None:
        self._projeto = projeto
        self._usuario_id = usuario_id
        self._api_key = api_key
        self._email = email
        self._senha = senha
        self._timeout = timeout
        self._id_token: str | None = None
        self._refresh_token: str | None = None
        self._expira_em: float = 0.0

    @property
    def autenticado(self) -> bool:
        return self._id_token is not None

    def _base(self) -> str:
        return _FIRESTORE.format(projeto=self._projeto)

    def _chave(self) -> dict:
        return {"key": self._api_key}

    def _sobe_autenticacao(self, resposta: requests.Response) -> None:
        if resposta.status_code != 200:
            raise AutenticacaoFalhou(
                f"autenticação recusada: HTTP {resposta.status_code}"
            )
        corpo = resposta.json()
        token = corpo.get("idToken") or corpo.get("access_token")
        if not token:
            raise AutenticacaoFalhou("token ausente na resposta")
        self._id_token = token
        self._refresh_token = corpo.get("refreshToken")
        try:
            expira = float(corpo.get("expiresIn") or corpo.get("expires_in") or "3600")
        except ValueError:
            expira = 3600.0
        self._expira_em = time.time() + expira

    def _init_sessao(self) -> None:
        try:
            resposta = requests.post(
                _AUTH_URL,
                params=self._chave(),
                json={
                    "email": self._email,
                    "password": self._senha,
                    "returnSecureToken": True,
                },
                timeout=self._timeout,
            )
        except requests.RequestException as erro:
            raise ErroTransporte(f"rede indisponível no login: {erro}") from erro
        self._sobe_autenticacao(resposta)

    def _renovar(self) -> None:
        if not self._refresh_token:
            self._init_sessao()
            return
        try:
            resposta = requests.post(
                _TOKEN_URL,
                params=self._chave(),
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                timeout=self._timeout,
            )
        except requests.RequestException as erro:
            raise ErroTransporte(f"rede indisponível na renovação: {erro}") from erro
        self._sobe_autenticacao(resposta)

    def _token(self) -> str:
        if self._id_token is None:
            self._init_sessao()
        elif time.time() >= self._expira_em:
            self._renovar()
        return self._id_token or ""

    def _requisicao(self) -> bool:
        """Renova o token após um `401` observado num pedido."""
        try:
            self._renovar()
            return True
        except AutenticacaoFalhou:
            return False

    def _pedir(self, metodo: callable, url: str, **extra: object) -> requests.Response:
        try:
            return metodo(
                url,
                headers={"Authorization": f"Bearer {self._token()}"},
                timeout=self._timeout,
                **extra,
            )
        except requests.RequestException as erro:
            raise ErroTransporte(f"rede indisponível: {erro}") from erro

    def ler_medicamentos(self) -> list[dict]:
        url = f"{self._base()}/UsuarioMedicamento/{self._usuario_id}/Medicamentos"
        resposta = self._pedir(requests.get, url)
        if resposta.status_code == 401 and self._requisicao():
            resposta = self._pedir(requests.get, url)
        if resposta.status_code == 200:
            docs = resposta.json().get("documents", [])
            return normalizar_medicamentos(docs)
        if resposta.status_code == 403:
            raise AutenticacaoFalhou("acesso negado aos medicamentos")
        raise ErroTransporte(f"medicamentos: HTTP {resposta.status_code}")

    def _gravar(self, colecao: str, doc_id: str, registro: dict) -> bool:
        """PATCH idempotente em uma subcoleção do paciente (retry em `401`)."""
        url = f"{self._base()}/UsuarioMedicamento/{self._usuario_id}/{colecao}/{doc_id}"
        corpo = {"fields": {k: {"stringValue": v} for k, v in registro.items()}}
        resposta = self._pedir(requests.patch, url, json=corpo)
        if resposta.status_code == 401 and self._requisicao():
            resposta = self._pedir(requests.patch, url, json=corpo)
        if resposta.status_code in (200, 201):
            return True
        if resposta.status_code in (400, 401, 403, 404):
            return False
        raise ErroTransporte(f"{colecao}: HTTP {resposta.status_code}")

    def gravar_historico(self, ocorrencia_id: str, registro: dict) -> bool:
        return self._gravar("Historico", doc_historico_id(ocorrencia_id), registro)

    def gravar_notificacao(self, ocorrencia_id: str, tipo: str, aviso: dict) -> bool:
        return self._gravar("Notificacoes", doc_notificacao_id(ocorrencia_id, tipo), aviso)


class TransporteFake(Transporte):
    """Firestore em memória para testes herméticos (sem rede)."""

    def __init__(self, medicamentos: list[dict] | None = None) -> None:
        self.medicamentos: list[dict] = [
            dict(m) for m in (medicamentos or [])
        ]
        self.historico: dict[str, dict] = {}
        self.notificacoes: dict[str, dict] = {}
        self.offline = False

    def ler_medicamentos(self) -> list[dict]:
        if self.offline:
            raise ErroTransporte("offline")
        return [json.loads(json.dumps(m)) for m in self.medicamentos]

    def gravar_historico(self, ocorrencia_id: str, registro: dict) -> bool:
        if self.offline:
            raise ErroTransporte("offline")
        chave = doc_historico_id(ocorrencia_id)
        self.historico[chave] = dict(registro)
        return True

    def gravar_notificacao(self, ocorrencia_id: str, tipo: str, aviso: dict) -> bool:
        if self.offline:
            raise ErroTransporte("offline")
        chave = doc_notificacao_id(ocorrencia_id, tipo)
        self.notificacoes[chave] = dict(aviso)
        return True
