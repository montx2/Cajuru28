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
from datetime import datetime, timedelta, timezone

import redis
from sqlalchemy import func

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Certificado,
    Empresa,
    ExecucaoImportacao,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.services import lotes_recebidos, sincronizacao
from app.services.importadores._distribuicao_dfe import CODIGO_IBGE_POR_UF
from app.services.periodo import Periodo

# Tipos cuja consulta ao Ambiente Nacional exige cUFAutor (NFe/CT-e).
TIPOS_COM_UF = {TipoDocumentoFiscal.NFE, TipoDocumentoFiscal.CTE}


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


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


# Curto de propósito: com o broker fora, o clique não pode esperar os retries
# do Celery (cerca de 20 s) para ouvir "não deu". Um segundo é folga de sobra
# para um Redis local responder — e evita recusar captura por host ocupado.
TIMEOUT_FILA_SEGUNDOS = 1.0


def fila_respondendo() -> bool:
    """
    O broker responde? Uma ida ao Redis resolve a dúvida em milissegundos.

    A checagem não substitui o enfileiramento (que continua sendo a verdade);
    ela existe para não criar execução nem segurar o operador quando a fila
    está fora — é o estado em que o painel já mostra "Redis não responde".
    """
    try:
        cliente = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=TIMEOUT_FILA_SEGUNDOS,
            socket_timeout=TIMEOUT_FILA_SEGUNDOS,
        )
        cliente.ping()
        return True
    except Exception:  # noqa: BLE001 — qualquer falha aqui significa "não respondeu"
        return False


def _disparar(empresa_id: int, tipo: str, execucao_id: int) -> None:
    """Import preguiçoso: `app.worker.tasks` importa este módulo (ciclo)."""
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


def em_andamento(
    db: Session, empresa_id: int, tipo: TipoDocumentoFiscal
) -> ExecucaoImportacao | None:
    """
    A varredura desta empresa+tipo está rodando agora?

    Público porque as rotas de prévia precisam responder isso ("vai rodar" ×
    "já está rodando") sem enfileirar nada. Duas definições de "em andamento"
    em lugares diferentes seriam duas telas discordando.
    """
    return _em_andamento(db, empresa_id, tipo)


def verificar_empresa(
    db: Session, empresa: Empresa, tipo: TipoDocumentoFiscal
) -> tuple[str, str]:
    """Pré-voo local (não custa requisição): devolve (status, mensagem)."""
    if not empresa.ativa:
        return "bloqueado", "Empresa inativa: reative o cadastro antes de capturar."
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

    validade = _aware(tem_certificado.validade)
    if validade is None or validade <= datetime.now(timezone.utc):
        return "sem_certificado", "Certificado A1 vencido ou sem validade: substitua-o antes de capturar."

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
    tem_lotes = lotes_recebidos.quantidade_pendente(empresa.id, tipo) > 0
    if not empresa.ativa:
        return ResultadoEnfileiramento("bloqueado", empresa.id, tipo.value, mensagem="Empresa inativa.")
    status_preflight, mensagem_preflight = verificar_empresa(db, empresa, tipo)
    if status_preflight != "ok" and not tem_lotes:
        return ResultadoEnfileiramento(status_preflight, empresa.id, tipo.value, mensagem=mensagem_preflight)
    libertacao = sincronizacao.liberacao_para(db, empresa.id, tipo)
    # Um lote ilegível não pode impedir a captura de notas NOVAS quando a
    # janela abrir. Somente o replay dispensa A1 e contorna uma janela fechada.
    recuperacao = tem_lotes and (status_preflight != "ok" or (not libertacao.pode and not forcar))

    andamento = _em_andamento(db, empresa.id, tipo)
    if andamento is not None:
        return ResultadoEnfileiramento(
            status="em_andamento",
            empresa_id=empresa.id,
            tipo=tipo.value,
            execucao_id=andamento.id,
            mensagem="Já existe uma varredura em andamento para esta empresa e tipo.",
        )

    if recuperacao and origem == "auto":
        anterior = db.query(ExecucaoImportacao).filter(
            ExecucaoImportacao.empresa_id == empresa.id, ExecucaoImportacao.tipo == tipo,
            ExecucaoImportacao.origem == "reprocessamento", ExecucaoImportacao.status == StatusExecucao.ERRO,
        ).order_by(ExecucaoImportacao.id.desc()).first()
        fim = _aware(anterior.finalizado_em) if anterior else None
        if fim and fim + timedelta(hours=1) > datetime.now(timezone.utc):
            return ResultadoEnfileiramento("em_cooldown", empresa.id, tipo.value,
                disponivel_em=fim + timedelta(hours=1), mensagem="Lote com erro de leitura preservado; reprocessamento automático local tentará novamente em uma hora.")
    libertacao = sincronizacao.liberacao_para(db, empresa.id, tipo)
    if not recuperacao and not libertacao.pode and not forcar:
        mensagem = (
            ("Bloqueado pela SEFAZ (consumo indevido). " if libertacao.bloqueado else "")
            + f"Nova tentativa automática em {libertacao.quando:%d/%m/%Y %H:%M}."
            + (f" ({libertacao.motivo})" if libertacao.motivo else "")
        )
        return ResultadoEnfileiramento(
            status="em_cooldown",
            empresa_id=empresa.id,
            tipo=tipo.value,
            disponivel_em=libertacao.quando,
            mensagem=mensagem,
        )

    execucao = ExecucaoImportacao(
        empresa_id=empresa.id,
        tipo=tipo,
        status=StatusExecucao.EM_ANDAMENTO,
        data_inicio=periodo.inicio if periodo else None,
        data_fim=periodo.fim if periodo else None,
        origem="reprocessamento" if recuperacao else origem,
        forcar=bool(forcar),
    )
    if forcar and not recuperacao and not libertacao.pode:
        execucao.aviso = (
            "Consulta FORÇADA dentro da janela de consumo. Se o ambiente "
            "responder 656, o bloqueio recomeça do zero."
        )
    # Última porta antes de criar a execução: fila fora do ar não gera linha
    # nem 20 s de espera. Nada foi consultado, então a cota fiscal segue inteira.
    if not fila_respondendo():
        return ResultadoEnfileiramento(
            status="fila_indisponivel",
            empresa_id=empresa.id,
            tipo=tipo.value,
            mensagem=(
                "A fila de processamento não respondeu, então nada foi consultado "
                "na SEFAZ. Confira se os serviços de fila e worker estão no ar e "
                "dispare de novo."
            ),
        )
    db.add(execucao)
    db.commit()
    db.refresh(execucao)

    try:
        _disparar(empresa.id, tipo.value, execucao.id)
    except Exception as exc:  # noqa: BLE001 — fila fora do ar não pode deixar execução zumbi
        execucao.status = StatusExecucao.ERRO
        execucao.falha = "fila_indisponivel"
        execucao.mensagem_erro = (
            "Não foi possível enfileirar a importação (Redis/Celery indisponível?): "
            f"{str(exc)[:300]}"
        )
        # ERRO é estado final: sem `finalizado_em`, a central de Execuções
        # desenha a duração de uma falha de dias atrás como "em curso", como se
        # a varredura ainda estivesse rodando. O fim registrado é o que separa
        # "falhou" de "não sei se terminou".
        execucao.finalizado_em = datetime.now(timezone.utc)
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
        mensagem="Reprocessamento local de lotes recebidos enfileirado (sem repetir consulta fiscal)." if recuperacao else "Varredura enfileirada.",
    )


def reagendar(
    db: Session,
    execucao: ExecucaoImportacao,
    quando: datetime,
    *,
    motivo: str,
    tentativa: int | None = None,
) -> bool:
    """
    Marca a execução como "aguardando" e programa a continuação.

    Retorna False quando a task de reforço não pôde ser enfileirada (broker fora
    do ar). Nesse caso o agendador (Beat) assume, porque varre execuções
    `aguardando` vencidas — o processo não depende de um único mecanismo.
    """
    agora = datetime.now(timezone.utc)
    quando_com_tz = _aware(quando) or agora
    atraso = max(60, int((quando_com_tz - agora).total_seconds()))

    anterior = _aware(execucao.bloqueado_ate)
    ja_marcada = (
        execucao.status == StatusExecucao.AGUARDANDO
        and anterior is not None
        and abs((anterior - quando_com_tz).total_seconds()) < 1
    )
    if not ja_marcada:
        execucao.status = StatusExecucao.AGUARDANDO
        execucao.bloqueado_ate = quando_com_tz
        execucao.tentativas = (execucao.tentativas or 0) + 1
        execucao.aviso = _acrescentar_aviso(execucao.aviso, motivo)
        db.commit()
    else:
        # `worker.tasks` já gravou a execução como aguardando antes de chamar
        # aqui. Não incrementamos `tentativas` de novo — isso inflava contadores
        # e fazia o painel parecer que houve várias consultas bloqueadas.
        execucao.aviso = _acrescentar_aviso(execucao.aviso, motivo)
        db.commit()

    try:
        from app.worker.tasks import importar_documentos

        kwargs = {
            "empresa_id": execucao.empresa_id,
            "tipo": execucao.tipo.value,
            "execucao_id": execucao.id,
        }
        if tentativa is not None:
            kwargs["tentativa"] = tentativa
        importar_documentos.apply_async(kwargs=kwargs, countdown=atraso)
        return True
    except Exception:  # noqa: BLE001 — sem broker o Beat continua o trabalho
        return False


def retomar(db: Session, execucao: ExecucaoImportacao) -> bool:
    """
    Acorda uma execução que estava dormindo, sem criar outra por cima.

    É o caminho de recuperação: se o agendamento com countdown se perder
    (reinício de worker, flush do broker), o Beat assume a mesma execução e o
    checkpoint de NSU continua válido — nenhuma nota é baixada duas vezes.
    """
    from app.worker.tasks import importar_documentos

    execucao.status = StatusExecucao.EM_ANDAMENTO
    db.commit()
    try:
        importar_documentos.delay(
            empresa_id=execucao.empresa_id,
            tipo=execucao.tipo.value,
            execucao_id=execucao.id,
        )
        return True
    except Exception:  # noqa: BLE001 — sem broker, fica para o próximo tick
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
        configurados = (empresa.quais_tipos_sincronizar or "").strip()
        tipos = list(dict.fromkeys(
            TipoDocumentoFiscal(item.strip().lower())
            for item in configurados.split(",")
            if item.strip().lower() in {tipo.value for tipo in TipoDocumentoFiscal}
        ))
        if not configurados:
            tipos = list(TipoDocumentoFiscal)
        if not tipos:
            continue
        resultados.append((empresa, tipos))
    return resultados
