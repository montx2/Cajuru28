"""
Trilha do job e notificações internas.

Duas garantias:

- **toda** mudança de status passa por `registrar_evento`, então não existe
  job que mudou de estado sem linha de evento;
- nada de segredo entra em `detalhe_json`: o dicionário passa por um filtro de
  chaves sensíveis antes de virar texto.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from app.models import Usuario
from app.procuracoes.modelos import JobProcuracao, NotificacaoProcuracao

log = logging.getLogger("cajuru.procuracoes.eventos")

#: Chaves que nunca podem ser persistidas nem logadas, venham de onde vierem.
CHAVES_PROIBIDAS = frozenset(
    {
        "senha",
        "password",
        "pin",
        "pfx",
        "p12",
        "chave_privada",
        "private_key",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "cookies",
        "set-cookie",
        "secret",
        "segredo",
        "consumer_secret",
        "client_secret",
        "senha_certificado",
        "credencial",
    }
)

_LIMITE_TEXTO = 2000


def sanitizar(dados: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove chaves sensíveis em qualquer profundidade e limita o tamanho.

    A comparação é por *substring* em minúsculas: `senha_do_certificado`,
    `X-Auth-Token` e `clientSecret` caem todos no filtro.
    """
    if not dados:
        return {}

    def _limpar(valor: Any, profundidade: int = 0) -> Any:
        if profundidade > 6:
            return "…"
        if isinstance(valor, Mapping):
            saida: dict[str, Any] = {}
            for chave, item in valor.items():
                texto_chave = str(chave)
                normalizada = texto_chave.lower().replace("-", "_")
                if any(proibida in normalizada for proibida in CHAVES_PROIBIDAS):
                    saida[texto_chave] = "[redigido]"
                    continue
                saida[texto_chave] = _limpar(item, profundidade + 1)
            return saida
        if isinstance(valor, (list, tuple)):
            return [_limpar(item, profundidade + 1) for item in valor[:50]]
        if isinstance(valor, str):
            return valor[:500]
        if isinstance(valor, (int, float, bool)) or valor is None:
            return valor
        return str(valor)[:500]

    return _limpar(dict(dados))


def _serializar(dados: Mapping[str, Any] | None) -> str:
    try:
        texto = json.dumps(sanitizar(dados), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        texto = "{}"
    return texto[:8000]


def rotulo_do_ator(
    db: Session, eventos: list, *, usuario_ids: set[int] | None = None
) -> dict[int, str]:
    """Resolve `usuario_id` → nome, para a trilha falar de gente.

    A trilha de auditoria guarda o ator como `operador:<id>` — identificador
    estável, sem vazar nome em log. Mas a tela precisa falar "Ana", não
    "operador:7". A resolução acontece na saída, nunca na persistência.
    """
    ids = {
        evento.usuario_id
        for evento in eventos
        if getattr(evento, "usuario_id", None) is not None
    }
    if usuario_ids:
        ids |= {i for i in usuario_ids if i is not None}
    if not ids:
        return {}
    from app.models import Usuario

    return {
        linha[0]: linha[1]
        for linha in db.query(Usuario.id, Usuario.nome).filter(Usuario.id.in_(ids)).all()
    }


def descrever_ator(ator: str, usuario_id: int | None, nomes: dict[int, str]) -> str:
    """Traduz `ator` bruto em rótulo humano, sem consulta adicional."""
    texto = (ator or "").strip()
    if usuario_id is not None and usuario_id in nomes:
        return nomes[usuario_id]
    if texto.startswith("operador:"):
        return f"Operador #{texto.split(':', 1)[1]}"
    if texto.startswith("agente:"):
        return f"Estação #{texto.split(':', 1)[1]}"
    if texto == "agendador":
        return "Agendador"
    if texto == "sistema":
        return "Sistema"
    return texto or "Sistema"


def para_saida(db: Session, eventos: list) -> list:
    """Eventos ORM → `EventoSaida` com `ator_rotulo` resolvido.

    Único ponto de montagem: o painel do job e o detalhe da empresa usam a
    mesma tradução, então a trilha nunca aparece "crua" em uma tela e legível
    na outra.
    """
    from app.procuracoes.esquemas import EventoSaida

    nomes = rotulo_do_ator(db, eventos)
    saida = []
    for evento in eventos:
        item = EventoSaida.model_validate(evento)
        item.ator_rotulo = descrever_ator(evento.ator, evento.usuario_id, nomes)
        saida.append(item)
    return saida


def registrar_evento(
    db: Session,
    job: JobProcuracao,
    tipo: str,
    *,
    mensagem: str = "",
    etapa: str = "",
    status_anterior: str = "",
    status_novo: str = "",
    codigo_erro: str = "",
    ator: str = "sistema",
    agente_id: int | None = None,
    usuario_id: int | None = None,
    detalhe: Mapping[str, Any] | None = None,
):
    """Grava o evento e dá flush; o commit é de quem chamou (padrão do projeto)."""
    from app.procuracoes.modelos import JobEvento

    evento = JobEvento(
        job_id=job.id,
        tipo=tipo[:40],
        mensagem=(mensagem or "")[:_LIMITE_TEXTO],
        etapa=(etapa or job.etapa_atual or "")[:40],
        status_anterior=(status_anterior or "")[:40],
        status_novo=(status_novo or "")[:40],
        codigo_erro=(codigo_erro or "")[:60],
        ator=(ator or "sistema")[:60],
        agente_id=agente_id,
        usuario_id=usuario_id,
        detalhe_json=_serializar(detalhe),
    )
    db.add(evento)
    db.flush()
    log.info(
        "procuracao_evento",
        extra={
            "job_id": job.id,
            "tipo": tipo,
            "status": status_novo or job.status,
            "codigo_erro": codigo_erro or None,
        },
    )
    return evento


def notificar(
    db: Session,
    escritorio_id: int,
    *,
    chave: str,
    tipo: str,
    titulo: str,
    nivel: str = "info",
    detalhe: str = "",
    empresa_id: int | None = None,
    job_id: int | None = None,
) -> NotificacaoProcuracao:
    """Cria (ou reaproveita) a notificação identificada por `chave`.

    A chave é o que impede "certificado vencendo" de virar uma notificação por
    varredura. Se a notificação já foi reconhecida e o fato voltou a valer, ela
    é reaberta — reconhecer não pode esconder um problema que persiste.
    """
    existente = (
        db.query(NotificacaoProcuracao)
        .filter(
            NotificacaoProcuracao.escritorio_id == escritorio_id,
            NotificacaoProcuracao.chave == chave[:160],
        )
        .first()
    )
    agora = datetime.now(timezone.utc)
    if existente is not None:
        existente.titulo = titulo[:160]
        existente.detalhe = (detalhe or "")[:_LIMITE_TEXTO]
        existente.nivel = nivel[:20]
        existente.empresa_id = empresa_id or existente.empresa_id
        existente.job_id = job_id or existente.job_id
        if existente.reconhecida_em is not None:
            existente.reconhecida_em = None
            existente.reconhecida_por = None
            existente.criado_em = agora
        db.flush()
        return existente

    notificacao = NotificacaoProcuracao(
        escritorio_id=escritorio_id,
        chave=chave[:160],
        tipo=tipo[:40],
        nivel=nivel[:20],
        titulo=titulo[:160],
        detalhe=(detalhe or "")[:_LIMITE_TEXTO],
        empresa_id=empresa_id,
        job_id=job_id,
    )
    db.add(notificacao)
    db.flush()
    return notificacao


def reconhecer(
    db: Session, escritorio_id: int, notificacao_id: int, usuario: Usuario | None
) -> bool:
    notificacao = (
        db.query(NotificacaoProcuracao)
        .filter(
            NotificacaoProcuracao.id == notificacao_id,
            NotificacaoProcuracao.escritorio_id == escritorio_id,
        )
        .first()
    )
    if notificacao is None:
        return False
    notificacao.reconhecida_em = datetime.now(timezone.utc)
    notificacao.reconhecida_por = usuario.id if usuario else None
    db.flush()
    return True
