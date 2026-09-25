"""
Identidade, autenticação e saúde das estações (Cajuru Agent).

**Por que HMAC e não um bearer token simples.** O Agent roda numa máquina de
escritório, com usuário logado e antivírus mexendo em disco. Um bearer token
vazado é autenticação completa para quem o copiar. Com HMAC por requisição:

- o segredo nunca trafega na rede (só a assinatura);
- cada requisição carrega `nonce` + `timestamp`, então capturar o tráfego não
  permite repetir a chamada (proteção contra replay);
- revogar é um `UPDATE` numa linha — sem lista de tokens para caçar.

O que é assinado (string canônica, `\\n` como separador)::

    METODO
    CAMINHO
    TIMESTAMP_ISO8601
    NONCE
    SHA256_HEX_DO_CORPO

Cabeçalhos: `X-Cajuru-Agente`, `X-Cajuru-Timestamp`, `X-Cajuru-Nonce`,
`X-Cajuru-Assinatura`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import gerar_hash_senha, verificar_senha
from app.procuracoes.modelos import Agente, AgenteNonce, AgenteSessao, JobProcuracao

log = logging.getLogger("cajuru.procuracoes.agentes")

CABECALHO_AGENTE = "X-Cajuru-Agente"
CABECALHO_TIMESTAMP = "X-Cajuru-Timestamp"
CABECALHO_NONCE = "X-Cajuru-Nonce"
CABECALHO_ASSINATURA = "X-Cajuru-Assinatura"

#: Tolerância de relógio entre estação e servidor. Curta de propósito: é a
#: janela em que um replay seria teoricamente possível.
TOLERANCIA_RELOGIO = timedelta(minutes=5)

#: Duração de uma sessão de Agent (renovada a cada heartbeat).
DURACAO_SESSAO = timedelta(hours=12)


class AgenteAuthError(RuntimeError):
    """Falha de autenticação do Agent — mensagem genérica, sem pistas."""

    def __init__(self, motivo: str, status_code: int = 401):
        super().__init__(motivo)
        self.status_code = status_code


@dataclass(frozen=True)
class SessaoAberta:
    """Resultado de `abrir_sessao` — a chave em claro só existe aqui."""

    sessao: AgenteSessao
    jti: str
    chave: str
    expira_em: datetime


@dataclass(frozen=True)
class CredencialNova:
    """Devolvida uma única vez. O servidor guarda apenas o hash."""

    agente: Agente
    segredo: str


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def normalizar_identificador(valor: str) -> str:
    """Identificador da máquina: hex de 16..64, minúsculo. Nada de texto livre."""
    texto = "".join(ch for ch in str(valor or "").strip().lower() if ch in "0123456789abcdef")
    if not 16 <= len(texto) <= 64:
        raise ValueError(
            "Identificador de estação inválido: esperado hash hexadecimal de 16 a 64 caracteres."
        )
    return texto


def registrar_agente(
    db: Session,
    escritorio_id: int,
    *,
    nome: str,
    identificador: str,
    hostname: str = "",
    usuario_windows: str = "",
    sistema_operacional: str = "",
) -> CredencialNova:
    """Cadastra (ou re-credencia) uma estação e devolve o segredo em claro.

    Re-credenciar é o caminho de rotação: mesma máquina, segredo novo,
    `versao_credencial` incrementada — as assinaturas antigas param de valer
    imediatamente.
    """
    ident = normalizar_identificador(identificador)
    agente = (
        db.query(Agente)
        .filter(Agente.escritorio_id == escritorio_id, Agente.identificador == ident)
        .first()
    )
    segredo = secrets.token_urlsafe(48)
    if agente is None:
        agente = Agente(
            escritorio_id=escritorio_id,
            identificador=ident,
            nome=(nome or ident[:8])[:80],
            segredo_hash=gerar_hash_senha(segredo),
        )
        db.add(agente)
    else:
        agente.segredo_hash = gerar_hash_senha(segredo)
        agente.versao_credencial = int(agente.versao_credencial or 1) + 1
        agente.nome = (nome or agente.nome)[:80]
        agente.revogado_em = None
        agente.revogado_motivo = ""
        agente.ativo = True

    agente.hostname = (hostname or "")[:255]
    agente.usuario_windows = (usuario_windows or "")[:255]
    agente.sistema_operacional = (sistema_operacional or "")[:120]
    db.flush()

    # Credencial nova invalida sessões antigas.
    db.query(AgenteSessao).filter(
        AgenteSessao.agente_id == agente.id, AgenteSessao.encerrada_em.is_(None)
    ).update({AgenteSessao.encerrada_em: _agora()}, synchronize_session=False)
    db.flush()
    return CredencialNova(agente=agente, segredo=segredo)


def revogar(db: Session, agente: Agente, motivo: str = "") -> Agente:
    """Corta o acesso da estação e devolve à fila o que ela segurava."""
    agente.ativo = False
    agente.revogado_em = _agora()
    agente.revogado_motivo = (motivo or "Revogado pelo administrador.")[:255]
    agente.versao_credencial = int(agente.versao_credencial or 1) + 1
    db.query(AgenteSessao).filter(
        AgenteSessao.agente_id == agente.id, AgenteSessao.encerrada_em.is_(None)
    ).update({AgenteSessao.encerrada_em: _agora()}, synchronize_session=False)
    db.query(JobProcuracao).filter(
        JobProcuracao.agente_id == agente.id,
        JobProcuracao.lease_ate.isnot(None),
    ).update(
        {
            JobProcuracao.agente_id: None,
            JobProcuracao.lease_ate: None,
            JobProcuracao.lease_token: "",
        },
        synchronize_session=False,
    )
    db.flush()
    return agente


def assinatura_esperada(
    segredo: str, metodo: str, caminho: str, timestamp: str, nonce: str, corpo: bytes
) -> str:
    """Assinatura canônica. Igual no servidor e no Agent — mude nos dois."""
    digest_corpo = hashlib.sha256(corpo or b"").hexdigest()
    mensagem = "\n".join(
        [metodo.upper(), caminho, timestamp, nonce, digest_corpo]
    ).encode("utf-8")
    return hmac.new(segredo.encode("utf-8"), mensagem, hashlib.sha256).hexdigest()


def abrir_sessao(
    db: Session, agente: Agente, segredo: str, *, endereco: str = ""
) -> SessaoAberta:
    """Troca o segredo de matrícula por uma chave de sessão de curta duração.

    A chave de sessão é derivada do segredo do Agent e de um `jti` aleatório.
    Assim o segredo de matrícula não participa de cada requisição e encerrar a
    sessão invalida a chave derivada na hora. O servidor guarda apenas
    `sha256(chave)`; a chave em claro existe só nesta resposta.
    """
    if not verificar_senha(segredo, agente.segredo_hash):
        raise AgenteAuthError("Credencial de estação inválida.")
    if not agente.ativo or agente.revogado_em is not None:
        raise AgenteAuthError("Estação revogada.", 403)

    agora = _agora()
    db.query(AgenteSessao).filter(
        AgenteSessao.agente_id == agente.id, AgenteSessao.encerrada_em.is_(None)
    ).update({AgenteSessao.encerrada_em: agora}, synchronize_session=False)

    jti = secrets.token_hex(16)
    chave = _derivar_chave_sessao(segredo, jti, int(agente.versao_credencial or 1))
    sessao = AgenteSessao(
        agente_id=agente.id,
        jti=jti,
        token_hash=hashlib.sha256(chave.encode("utf-8")).hexdigest(),
        expira_em=agora + DURACAO_SESSAO,
        endereco_origem=(endereco or "")[:64],
    )
    db.add(sessao)
    db.flush()
    return SessaoAberta(sessao=sessao, jti=jti, chave=chave, expira_em=sessao.expira_em)


def encerrar_sessoes(db: Session, agente: Agente) -> int:
    """Logout do Agent — usado na parada limpa do serviço."""
    encerradas = (
        db.query(AgenteSessao)
        .filter(AgenteSessao.agente_id == agente.id, AgenteSessao.encerrada_em.is_(None))
        .update({AgenteSessao.encerrada_em: _agora()}, synchronize_session=False)
    )
    db.flush()
    return int(encerradas or 0)


def _derivar_chave_sessao(segredo: str, jti: str, versao: int) -> str:
    return hmac.new(
        segredo.encode("utf-8"),
        f"cajuru-agent-session|{jti}|{versao}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _sessao_viva(db: Session, agente: Agente, agora: datetime) -> AgenteSessao | None:
    return (
        db.query(AgenteSessao)
        .filter(
            AgenteSessao.agente_id == agente.id,
            AgenteSessao.encerrada_em.is_(None),
            AgenteSessao.expira_em > agora,
        )
        .order_by(AgenteSessao.id.desc())
        .first()
    )


def autenticar_com_chave(
    db: Session,
    *,
    identificador: str,
    chave_sessao: str,
    timestamp: str,
    nonce: str,
    assinatura: str,
    metodo: str,
    caminho: str,
    corpo: bytes,
    endereco: str = "",
) -> Agente:
    """Caminho real de autenticação usado pela API.

    O Agent envia `X-Cajuru-Agente: <identificador>.<jti>` e assina com a
    chave de sessão derivada. O servidor localiza a sessão pelo `jti`, confere
    `sha256(chave)` contra o que está gravado e só então valida o HMAC.
    """
    try:
        ident = normalizar_identificador(identificador)
    except ValueError as exc:
        raise AgenteAuthError("Credencial de estação inválida.") from exc

    agora = _agora()
    try:
        momento = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise AgenteAuthError("Credencial de estação inválida.") from exc
    momento = momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)
    if abs((agora - momento).total_seconds()) > TOLERANCIA_RELOGIO.total_seconds():
        raise AgenteAuthError("Relógio da estação fora da janela aceita.")

    if not nonce or not (16 <= len(nonce) <= 64) or not nonce.isalnum():
        raise AgenteAuthError("Credencial de estação inválida.")

    agente = db.query(Agente).filter(Agente.identificador == ident).first()
    if agente is None or not agente.ativo or agente.revogado_em is not None:
        raise AgenteAuthError("Credencial de estação inválida.")

    sessao = _sessao_viva(db, agente, agora)
    if sessao is None:
        raise AgenteAuthError("Sessão da estação expirada. Refaça a conexão.")
    if not hmac.compare_digest(
        sessao.token_hash, hashlib.sha256(chave_sessao.encode("utf-8")).hexdigest()
    ):
        raise AgenteAuthError("Credencial de estação inválida.")

    esperado = assinatura_esperada(
        chave_sessao, metodo, caminho, timestamp, nonce, corpo
    )
    if not hmac.compare_digest(esperado, assinatura):
        raise AgenteAuthError("Credencial de estação inválida.")

    _consumir_nonce(db, agente, nonce, agora)
    sessao.expira_em = agora + DURACAO_SESSAO
    if endereco:
        sessao.endereco_origem = endereco[:64]
    db.flush()
    return agente


def _consumir_nonce(db: Session, agente: Agente, nonce: str, agora: datetime) -> None:
    """Grava o nonce; colisão significa replay e derruba a requisição."""
    from sqlalchemy.exc import IntegrityError

    registro = AgenteNonce(
        agente_id=agente.id,
        nonce=nonce[:64],
        expira_em=agora + TOLERANCIA_RELOGIO * 2,
    )
    db.add(registro)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        log.warning("agente_replay_detectado", extra={"agente": agente.identificador})
        raise AgenteAuthError("Requisição repetida (replay) recusada.", 409)


def limpar_nonces(db: Session, *, agora: datetime | None = None) -> int:
    agora = agora or _agora()
    removidos = (
        db.query(AgenteNonce).filter(AgenteNonce.expira_em <= agora).delete(
            synchronize_session=False
        )
    )
    db.flush()
    return int(removidos or 0)


def registrar_heartbeat(
    db: Session,
    agente: Agente,
    *,
    versao_agente: str = "",
    versao_navegador: str = "",
    versao_assinador: str = "",
    assinador_ok: bool = False,
    assinador_detalhe: str = "",
    assinador_pendencias: tuple[str, ...] | list[str] = (),
) -> Agente:
    """Bate o coração e atualiza a ficha técnica da estação."""
    agente.ultimo_heartbeat_em = _agora()
    if versao_agente:
        agente.versao_agente = versao_agente[:30]
    if versao_navegador:
        agente.versao_navegador = versao_navegador[:80]
    agente.versao_assinador = (versao_assinador or "")[:30]
    agente.assinador_ok = bool(assinador_ok)
    agente.assinador_detalhe = (assinador_detalhe or "")[:255]
    agente.assinador_pendencias = ",".join(assinador_pendencias)[:255]
    agente.jobs_em_andamento = (
        db.query(func.count(JobProcuracao.id))
        .filter(
            JobProcuracao.agente_id == agente.id,
            JobProcuracao.lease_ate.isnot(None),
            JobProcuracao.lease_ate > _agora(),
        )
        .scalar()
        or 0
    )
    db.flush()
    return agente


def situacao(agente: Agente, tolerancia_segundos: int) -> str:
    """`online` | `processando` | `offline` | `revogado`."""
    if not agente.ativo or agente.revogado_em is not None:
        return "revogado"
    visto = _aware(agente.ultimo_heartbeat_em)
    if visto is None:
        return "offline"
    if (_agora() - visto).total_seconds() > max(30, tolerancia_segundos):
        return "offline"
    return "processando" if (agente.jobs_em_andamento or 0) > 0 else "online"
