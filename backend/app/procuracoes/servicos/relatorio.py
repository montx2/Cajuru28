"""
Relatório consolidado do lote e métricas por etapa.

Duas saídas, propósitos diferentes:

- `linhas()` + `para_csv()` / `para_json()` — a fotografia da carteira, uma
  linha por empresa, no formato que o escritório manda para o cliente ou
  arquiva: Cliente, Documento, Status, Validade, Procurador, Erro.
- `metricas()` — onde o tempo vai. Tempo médio por etapa, quanto se perde
  esperando humano, erros por categoria, taxa de sucesso.

A distinção que faz a métrica ser útil: **tempo de máquina e tempo de espera
humana são medidos separadamente**. Somados, escondem o único número que
permite dimensionar o dia de trabalho — quantas horas de operador o lote exige.
Um lote que leva 6 h de relógio mas só 20 min de atenção humana é ótimo; um que
leva 2 h todas de atenção humana é um problema. A média simples trata os dois
como iguais.

Sobre dado sensível: o CSV sai com o documento **mascarado** por padrão, porque
o arquivo circula por e-mail e fica em pasta compartilhada. Quem precisa do
documento completo (conciliação com outro sistema) pede explicitamente com
`mascarar=False`, e essa escolha fica registrada na auditoria da rota.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.mascaramento import mascarar_documento
from app.models import Empresa
from app.procuracoes.estados import (
    ESTADOS_ESPERANDO_HUMANO,
    ESTADOS_TERMINAIS,
    EtapaFluxo,
    StatusAutorizacao,
    StatusJob,
    regra_do_erro,
)
from app.procuracoes.modelos import Autorizacao, JobEvento, JobProcuracao

#: Cabeçalho do CSV, na ordem pedida pela operação.
COLUNAS: tuple[str, ...] = (
    "cliente",
    "documento",
    "situacao",
    "validade",
    "dias_para_vencer",
    "procurador",
    "prazo_aceite",
    "job_id",
    "job_status",
    "etapa",
    "erro",
    "atualizado_em",
)

#: Rótulos legíveis para a coluna `situacao`.
ROTULO_SITUACAO: dict[str, str] = {
    StatusAutorizacao.SEM_AUTORIZACAO.value: "Sem autorização",
    StatusAutorizacao.EM_ANALISE.value: "Em análise",
    StatusAutorizacao.AGUARDANDO_ACEITE.value: "Aguardando validação",
    StatusAutorizacao.ATIVA.value: "Ativa",
    StatusAutorizacao.EXPIRADA.value: "Expirada",
    StatusAutorizacao.CANCELADA.value: "Cancelada",
    StatusAutorizacao.REJEITADA.value: "Rejeitada",
    StatusAutorizacao.ERRO.value: "Erro",
    StatusAutorizacao.INTERVENCAO_MANUAL.value: "Intervenção manual",
}


@dataclass
class LinhaRelatorio:
    """Uma empresa no relatório final."""

    cliente: str
    documento: str
    situacao: str
    validade: date | None
    dias_para_vencer: int | None
    procurador: str
    prazo_aceite: date | None
    job_id: int | None
    job_status: str
    etapa: str
    erro: str
    atualizado_em: datetime | None

    def para_dict(self, *, mascarar: bool = True) -> dict[str, str]:
        return {
            "cliente": self.cliente,
            "documento": (
                mascarar_documento(self.documento) if mascarar else self.documento
            ),
            "situacao": ROTULO_SITUACAO.get(self.situacao, self.situacao or "—"),
            "validade": self.validade.isoformat() if self.validade else "",
            "dias_para_vencer": (
                str(self.dias_para_vencer) if self.dias_para_vencer is not None else ""
            ),
            "procurador": (
                mascarar_documento(self.procurador) if mascarar else self.procurador
            ),
            "prazo_aceite": self.prazo_aceite.isoformat() if self.prazo_aceite else "",
            "job_id": str(self.job_id) if self.job_id else "",
            "job_status": self.job_status or "",
            "etapa": self.etapa or "",
            "erro": self.erro or "",
            "atualizado_em": (
                self.atualizado_em.isoformat() if self.atualizado_em else ""
            ),
        }


def linhas(
    db: Session,
    escritorio_id: int,
    *,
    hoje: date | None = None,
    somente_pendentes: bool = False,
) -> list[LinhaRelatorio]:
    """Uma linha por empresa ativa, com a autorização e o último job."""
    hoje = hoje or date.today()

    empresas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .order_by(Empresa.razao_social)
        .all()
    )

    autorizacoes: dict[int, Autorizacao] = {}
    for autorizacao in (
        db.query(Autorizacao)
        .filter(Autorizacao.escritorio_id == escritorio_id)
        .order_by(Autorizacao.atualizado_em.desc())
        .all()
    ):
        autorizacoes.setdefault(autorizacao.empresa_id, autorizacao)

    ultimos: dict[int, JobProcuracao] = {}
    for job in (
        db.query(JobProcuracao)
        .filter(JobProcuracao.escritorio_id == escritorio_id)
        .order_by(JobProcuracao.criado_em.desc())
        .all()
    ):
        ultimos.setdefault(job.empresa_id, job)

    resultado: list[LinhaRelatorio] = []
    for empresa in empresas:
        autorizacao = autorizacoes.get(empresa.id)
        job = ultimos.get(empresa.id)

        situacao = (
            autorizacao.situacao if autorizacao else StatusAutorizacao.SEM_AUTORIZACAO.value
        )
        if somente_pendentes and situacao == StatusAutorizacao.ATIVA.value:
            continue

        validade = autorizacao.data_validade if autorizacao else None
        resultado.append(
            LinhaRelatorio(
                cliente=empresa.razao_social,
                documento=empresa.cnpj_cpf or "",
                situacao=situacao,
                validade=validade,
                dias_para_vencer=(validade - hoje).days if validade else None,
                procurador=(autorizacao.outorgado_documento if autorizacao else ""),
                prazo_aceite=(autorizacao.prazo_aceite_ate if autorizacao else None),
                job_id=job.id if job else None,
                job_status=job.status if job else "",
                etapa=job.etapa_atual if job else "",
                erro=(job.mensagem_erro or job.codigo_erro or "") if job else "",
                atualizado_em=(
                    autorizacao.atualizado_em
                    if autorizacao
                    else (job.atualizado_em if job else None)
                ),
            )
        )
    return resultado


def para_csv(registros: list[LinhaRelatorio], *, mascarar: bool = True) -> str:
    """CSV com `;` e BOM — o que o Excel brasileiro abre sem perguntar nada.

    Delimitador `;` porque o Excel em locale pt-BR usa vírgula como separador
    decimal e ignora CSV separado por vírgula. BOM porque sem ele o Excel lê
    UTF-8 como Latin-1 e "Autorização" vira "AutorizaÃ§Ã£o".
    """
    buffer = io.StringIO()
    escritor = csv.DictWriter(
        buffer, fieldnames=list(COLUNAS), delimiter=";", lineterminator="\r\n"
    )
    escritor.writeheader()
    for registro in registros:
        escritor.writerow(registro.para_dict(mascarar=mascarar))
    return "\ufeff" + buffer.getvalue()


def para_json(registros: list[LinhaRelatorio], *, mascarar: bool = True) -> dict:
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "total": len(registros),
        "colunas": list(COLUNAS),
        "linhas": [registro.para_dict(mascarar=mascarar) for registro in registros],
    }


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


@dataclass
class Metricas:
    """Onde o tempo do lote foi parar."""

    jobs_considerados: int = 0
    concluidos: int = 0
    falhados: int = 0
    cancelados: int = 0
    taxa_sucesso: float = 0.0

    #: Relógio: da criação do job até o encerramento.
    duracao_media_minutos: float = 0.0
    #: Parcela gasta em estados que dependem de uma pessoa agir.
    espera_humana_media_minutos: float = 0.0
    #: Parcela gasta em processamento.
    processamento_medio_minutos: float = 0.0

    #: etapa → minutos médios.
    tempo_por_etapa: dict[str, float] = field(default_factory=dict)
    #: código do erro → ocorrências.
    erros_por_codigo: dict[str, int] = field(default_factory=dict)
    #: classe do erro (transiente, manual, …) → ocorrências.
    erros_por_classe: dict[str, int] = field(default_factory=dict)

    total_retentativas: int = 0
    intervencoes_humanas: int = 0
    clientes_por_hora: float = 0.0

    def para_json(self) -> dict:
        return {
            "jobs_considerados": self.jobs_considerados,
            "concluidos": self.concluidos,
            "falhados": self.falhados,
            "cancelados": self.cancelados,
            "taxa_sucesso": self.taxa_sucesso,
            "duracao_media_minutos": self.duracao_media_minutos,
            "espera_humana_media_minutos": self.espera_humana_media_minutos,
            "processamento_medio_minutos": self.processamento_medio_minutos,
            "tempo_por_etapa": self.tempo_por_etapa,
            "erros_por_codigo": self.erros_por_codigo,
            "erros_por_classe": self.erros_por_classe,
            "total_retentativas": self.total_retentativas,
            "intervencoes_humanas": self.intervencoes_humanas,
            "clientes_por_hora": self.clientes_por_hora,
        }


_ESPERANDO_HUMANO = {estado.value for estado in ESTADOS_ESPERANDO_HUMANO}
_TERMINAIS = {estado.value for estado in ESTADOS_TERMINAIS}


def metricas(
    db: Session,
    escritorio_id: int,
    *,
    desde: datetime | None = None,
    agora: datetime | None = None,
) -> Metricas:
    """Agrega a trilha de eventos em tempo por etapa e por tipo de espera.

    O cálculo sai da trilha (`procuracao_job_eventos`), não de campos
    agregados no job: a trilha é append-only e já registra toda transição com
    horário, então a métrica é reconstruível e auditável. Guardar contadores
    no job criaria uma segunda fonte de verdade que diverge no primeiro crash.
    """
    agora = agora or datetime.now(timezone.utc)
    consulta = db.query(JobProcuracao).filter(
        JobProcuracao.escritorio_id == escritorio_id
    )
    if desde is not None:
        consulta = consulta.filter(JobProcuracao.criado_em >= desde)
    jobs = consulta.all()

    dados = Metricas(jobs_considerados=len(jobs))
    if not jobs:
        return dados

    ids = [job.id for job in jobs]
    eventos_por_job: dict[int, list[JobEvento]] = defaultdict(list)
    for evento in (
        db.query(JobEvento)
        .filter(JobEvento.job_id.in_(ids))
        .order_by(JobEvento.job_id, JobEvento.quando)
        .all()
    ):
        eventos_por_job[evento.job_id].append(evento)

    duracoes: list[float] = []
    esperas: list[float] = []
    processamentos: list[float] = []
    acumulado_etapa: dict[str, list[float]] = defaultdict(list)

    for job in jobs:
        if job.status == StatusJob.CONCLUIDO.value:
            dados.concluidos += 1
        elif job.status == StatusJob.FALHOU.value:
            dados.falhados += 1
        elif job.status == StatusJob.CANCELADO.value:
            dados.cancelados += 1

        dados.total_retentativas += job.tentativas or 0
        if job.codigo_erro:
            dados.erros_por_codigo[job.codigo_erro] = (
                dados.erros_por_codigo.get(job.codigo_erro, 0) + 1
            )
            classe = regra_do_erro(job.codigo_erro).classe.value
            dados.erros_por_classe[classe] = dados.erros_por_classe.get(classe, 0) + 1

        inicio = _aware(job.criado_em)
        fim = _aware(job.finalizado_em)
        if inicio and fim and fim >= inicio:
            duracoes.append((fim - inicio).total_seconds() / 60)

        espera, processamento, por_etapa = _fatiar(
            eventos_por_job.get(job.id, []), job=job, agora=agora
        )
        if espera is not None:
            esperas.append(espera)
        if processamento is not None:
            processamentos.append(processamento)
        for etapa, minutos in por_etapa.items():
            acumulado_etapa[etapa].append(minutos)

    dados.intervencoes_humanas = sum(
        1
        for job in jobs
        for evento in eventos_por_job.get(job.id, [])
        if evento.status_novo == StatusJob.INTERVENCAO_MANUAL.value
    )

    finalizados = dados.concluidos + dados.falhados + dados.cancelados
    if finalizados:
        dados.taxa_sucesso = round(100 * dados.concluidos / finalizados, 1)
    dados.duracao_media_minutos = _media(duracoes)
    dados.espera_humana_media_minutos = _media(esperas)
    dados.processamento_medio_minutos = _media(processamentos)
    dados.tempo_por_etapa = {
        etapa: _media(valores) for etapa, valores in sorted(acumulado_etapa.items())
    }

    # Clientes/hora usa o tempo de relógio do lote inteiro, não a soma das
    # durações: é o número que responde "quantos consigo fazer hoje?".
    if dados.concluidos:
        comecos = [_aware(job.criado_em) for job in jobs]
        fins = [_aware(job.finalizado_em) for job in jobs]
        validos_inicio = [d for d in comecos if d]
        validos_fim = [d for d in fins if d]
        if validos_inicio and validos_fim:
            janela = (max(validos_fim) - min(validos_inicio)).total_seconds() / 3600
            if janela > 0:
                dados.clientes_por_hora = round(dados.concluidos / janela, 2)

    return dados


def _fatiar(
    eventos: list[JobEvento], *, job: JobProcuracao, agora: datetime
) -> tuple[float | None, float | None, dict[str, float]]:
    """Divide a vida do job em espera humana, processamento e tempo por etapa.

    Cada evento marca o instante em que o job **entrou** em um estado. O tempo
    naquele estado é a distância até o próximo evento (ou até agora, se ainda
    está lá). Somar por categoria é o que separa "o robô estava trabalhando"
    de "o job estava parado esperando alguém".
    """
    if not eventos:
        return None, None, {}

    espera = 0.0
    processamento = 0.0
    por_etapa: dict[str, float] = defaultdict(float)

    for indice, evento in enumerate(eventos):
        inicio = _aware(evento.quando)
        if inicio is None:
            continue
        if indice + 1 < len(eventos):
            fim = _aware(eventos[indice + 1].quando)
        elif job.status in _TERMINAIS:
            fim = _aware(job.finalizado_em) or _aware(job.atualizado_em)
        else:
            fim = agora
        if fim is None or fim < inicio:
            continue

        minutos = (fim - inicio).total_seconds() / 60
        estado = evento.status_novo or ""
        if estado in _ESPERANDO_HUMANO:
            espera += minutos
        elif estado and estado not in _TERMINAIS:
            processamento += minutos

        if evento.etapa:
            por_etapa[evento.etapa] += minutos

    return espera, processamento, dict(por_etapa)


def _media(valores: list[float]) -> float:
    if not valores:
        return 0.0
    return round(sum(valores) / len(valores), 1)


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
