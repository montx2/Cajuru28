"""
Fila de importação — a decisão única de "posso disparar esta varredura?".

Existe um motivo para API, lote e agendador passarem por aqui em vez de cada
um chamar `importar_documentos.delay()`: as três portas precisam das mesmas
travas, e uma trava faltando é o que produz bloqueio de CNPJ na SEFAZ.

Travas aplicadas (nesta ordem, da mais barata para a mais cara):

1. **certificado ativo** — sem ele nada funciona, e a falha é de cadastro,
   não de ambiente;
2. **UF cadastrada** para NFe/CT-e (`cUFAutor` é obrigatório no SOAP);
3. **uma varredura por empresa+tipo** — duas simultâneas avançariam cursores
   diferentes, e "consultar fora da sequência" é regra de uso indevido;
4. **janela de consumo** (1h depois de "nada novo" ou de um 656) — só é
   ignorada com `forcar=True`, declarado explicitamente pelo operador.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func

from sqlalchemy.orm import Session

from app.models import (
    Certificado,
    Empresa,
    ExecucaoImportacao,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.services import sincronizacao
from app.services.importadores._distribuicao_dfe import CODIGO_IBGE_POR_UF
from app.services.periodo import Periodo

# Tipos cuja consulta ao Ambiente Nacional exige cUFAutor (NFe/CT-e).
TIPOS_COM_UF = {TipoDocumentoFiscal.NFE, TipoDocumentoFiscal.CTE}


@dataclass
class ResultadoEnfileiramento:
    """`status` vira texto no painel — por isso cada um traz a mensagem pronta."""

    status: str  # enfileirada | em_andamento | em_cooldown | sem_certificado | sem_uf | bloqueado
    empresa_id: int
    tipo: str
    execucao_id: int | None = None
    disponivel_em: datetime | None = None
    mensagem: str = ""

    @property
    def enfileirada(self) -> bool:
        return self.status == "enfileirada"


def _disparar(empresa_id: int, tipo: str, execucao_id: int) -> None:
    """Import preguiçoso: `app.worker.tasks` importa este módulo (ciclo).
    
    No modo desktop (.exe), não há Redis/Celery: dispara em thread local.
    No modo Docker, usa Celery normalmente.
    """
    from app.core.config import settings

    # Modo desktop: thread local, sem Celery
    if settings.is_desktop:
        import threading

        def _rodar():
            try:
                from app.worker.executor import executar_importacao
                executar_importacao(empresa_id=empresa_id, tipo=tipo, execucao_id=execucao_id)
            except Exception as exc:  # noqa: BLE001
                import logging
                logging.getLogger("notasflow.fila").exception("Falha na execução desktop %s/%s: %s", empresa_id, tipo, exc)

        thread = threading.Thread(target=_rodar, daemon=True, name=f"import-{empresa_id}-{tipo}-{execucao_id}")
        thread.start()
        return

    # Modo normal: Celery
    from app.worker.tasks import importar_documentos

    importar_documentos.delay(empresa_id=empresa_id, tipo=tipo, execucao_id=execucao_id)


def _em_andamento(db: Session, empresa_id: int, tipo: TipoDocumentoFiscal) -> ExecucaoImportacao | None:
    return (
        db.query(ExecucaoImportacao)
        .filter(
            ExecucaoImportacao.empresa_id == empresa_id,
            ExecucaoImportacao.tipo == tipo,
            ExecucaoImportacao.status.in_([StatusExecucao.EM_ANDAMENTO]),
        )
        .order_by(ExecucaoImportacao.id.desc())
        .first()
    )


def verificar_empresa(
    db: Session, empresa: Empresa, tipo: TipoDocumentoFiscal
) -> tuple[str, str]:
    """Pré-voo local (não custa requisição): devolve (status, mensagem)."""
    tem_certificado = (
        db.query(Certificado)
        .filter(Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True))
        .first()
    )
    if tem_certificado is None:
        return (
            "sem_certificado",
            "Envie o certificado A1 (.pfx) desta empresa antes de importar.",
        )

    if tipo in TIPOS_COM_UF:
        uf = (empresa.uf or "").strip().upper()
        if uf not in CODIGO_IBGE_POR_UF:
            return (
                "sem_uf",
                f"UF {empresa.uf!r} não é válida — a consulta {tipo.value.upper()} "
                "precisa dela para o cUFAutor do Ambiente Nacional.",
            )
    return ("ok", "")


def enfileirar(
    db: Session,
    empresa: Empresa,
    tipo: TipoDocumentoFiscal,
    *,
    forcar: bool = False,
    periodo: Periodo | None = None,
    origem: str = "manual",
) -> ResultadoEnfileiramento:
    """
    Decide e, sendo o caso, cria a execução + dispara a task.

    Nunca levanta erro de "já está rodando": reusar a execução em andamento é
    o comportamento certo para um clique duplo acidental (e para o agendador
    batendo na porta de uma varredura que ainda não terminou).
    """
    status_preflight, mensagem_preflight = verificar_empresa(db, empresa, tipo)
    if status_preflight != "ok":
        return ResultadoEnfileiramento(
            status=status_preflight,
            empresa_id=empresa.id,
            tipo=tipo.value,
            mensagem=mensagem_preflight,
        )

    andamento = _em_andamento(db, empresa.id, tipo)
    if andamento is not None:
        return ResultadoEnfileiramento(
            status="em_andamento",
            empresa_id=empresa.id,
            tipo=tipo.value,
            execucao_id=andamento.id,
            mensagem="Já existe uma varredura em andamento para esta empresa e tipo.",
        )

    libertacao = sincronizacao.liberacao_para(db, empresa.id, tipo)
    if not libertacao.pode and not forcar:
        return ResultadoEnfileiramento(
            status="em_cooldown",
            empresa_id=empresa.id,
            tipo=tipo.value,
            disponivel_em=libertacao.quando,
            mensagem=(
                ("Bloqueado pela SEFAZ (consumo indevido). " if libertacao.bloqueado else "")
                + f"Nova tentativa automática em {libertacao.quando:%d/%m/%Y %H:%M}."
                + (f" ({libertacao.motivo})" if libertacao.motivo else "")
            ),
        )

    execucao = ExecucaoImportacao(
        empresa_id=empresa.id,
        tipo=tipo,
        status=StatusExecucao.EM_ANDAMENTO,
        data_inicio=periodo.inicio if periodo else None,
        data_fim=periodo.fim if periodo else None,
        origem=origem,
        forcar=bool(forcar),
    )
    if forcar and not libertacao.pode:
        execucao.aviso = (
            "Consulta FORÇADA dentro da janela de consumo. Se o ambiente "
            "responder 656, o bloqueio recomeça do zero."
        )
    db.add(execucao)
    db.commit()
    db.refresh(execucao)

    try:
        _disparar(empresa.id, tipo.value, execucao.id)
    except Exception as exc:  # noqa: BLE001 — fila fora do ar não pode deixar execução zumbi
        execucao.status = StatusExecucao.ERRO
        execucao.mensagem_erro = (
            "Não foi possível enfileirar a importação (Redis/Celery indisponível?): "
            f"{str(exc)[:300]}"
        )
        db.commit()
        return ResultadoEnfileiramento(
            status="fila_indisponivel",
            empresa_id=empresa.id,
            tipo=tipo.value,
            execucao_id=execucao.id,
            mensagem=execucao.mensagem_erro,
        )

    return ResultadoEnfileiramento(
        status="enfileirada",
        empresa_id=empresa.id,
        tipo=tipo.value,
        execucao_id=execucao.id,
        mensagem="Varredura enfileirada.",
    )


def reagendar(db: Session, execucao: ExecucaoImportacao, quando: datetime, *, motivo: str) -> bool:
    """
    Marca a execução como "aguardando" e programa a continuação.

    No modo desktop, o scheduler interno retoma execuções vencidas — não precisa
    de Celery countdown.
    """
    agora = datetime.now(timezone.utc)
    quando_com_tz = quando if quando.tzinfo else quando.replace(tzinfo=timezone.utc)
    atraso = max(60, int((quando_com_tz - agora).total_seconds()))
    execucao.status = StatusExecucao.AGUARDANDO
    execucao.bloqueado_ate = quando
    execucao.tentativas = (execucao.tentativas or 0) + 1
    execucao.aviso = _acrescentar_aviso(execucao.aviso, motivo)
    db.commit()

    from app.core.config import settings

    if settings.is_desktop:
        # No desktop, o loop de sincronização retoma sozinho
        return True

    try:
        from app.worker.tasks import importar_documentos

        importar_documentos.apply_async(
            kwargs={
                "empresa_id": execucao.empresa_id,
                "tipo": execucao.tipo.value,
                "execucao_id": execucao.id,
            },
            countdown=atraso,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def retomar(db: Session, execucao: ExecucaoImportacao) -> bool:
    """
    Acorda uma execução que estava dormindo.
    No desktop, dispara thread local; no Docker, via Celery.
    """
    from app.core.config import settings

    execucao.status = StatusExecucao.EM_ANDAMENTO
    db.commit()

    if settings.is_desktop:
        try:
            _disparar(execucao.empresa_id, execucao.tipo.value, execucao.id)
            return True
        except Exception:  # noqa: BLE001
            execucao.status = StatusExecucao.AGUARDANDO
            db.commit()
            return False

    from app.worker.tasks import importar_documentos

    try:
        importar_documentos.delay(
            empresa_id=execucao.empresa_id,
            tipo=execucao.tipo.value,
            execucao_id=execucao.id,
        )
        return True
    except Exception:  # noqa: BLE001
        execucao.status = StatusExecucao.AGUARDANDO
        db.commit()
        return False


def _acrescentar_aviso(atual: str | None, novo: str) -> str:
    linhas = [linha for linha in (atual or "").split("\n") if linha and linha != novo]
    linhas.append(novo)
    return "\n".join(linhas[-5:])


def disponiveis_para_sincronismo_automatico(
    db: Session, limite: int | None = None
) -> list[tuple[Empresa, list[TipoDocumentoFiscal]]]:
    """
    Empresas com sincronização automática, na ordem mais justa possível.

    Ordena por "há mais tempo sem varrer" (usando o estado de sincronização;
    empresa nunca varrida vem primeiro). Assim o teto por varredura não
    transforma as últimas empresas da lista em clientes de segunda classe.
    """
    from sqlalchemy import case
    from app.models import SincronizacaoDFe

    consulta = (
        db.query(Empresa, func.min(SincronizacaoDFe.ultima_consulta_em).label("mais_antiga"))
        .outerjoin(SincronizacaoDFe, SincronizacaoDFe.empresa_id == Empresa.id)
        .filter(Empresa.ativa.is_(True), Empresa.sincronizar_automaticamente.is_(True))
        .group_by(Empresa.id)
        .order_by(
            case((func.min(SincronizacaoDFe.ultima_consulta_em).is_(None), 0), else_=1),
            func.min(SincronizacaoDFe.ultima_consulta_em).asc(),
            Empresa.id.asc(),
        )
    )
    if limite:
        consulta = consulta.limit(limite)

    resultados: list[tuple[Empresa, list[TipoDocumentoFiscal]]] = []
    for empresa, _mais_antiga in consulta.all():
        tipos = [
            TipoDocumentoFiscal(item.strip())
            for item in (empresa.quais_tipos_sincronizar or "").split(",")
            if item.strip()
        ]
        if not tipos:
            tipos = list(TipoDocumentoFiscal)
        resultados.append((empresa, tipos))
    return resultados
