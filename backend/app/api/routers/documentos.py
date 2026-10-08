"""
Consulta e download dos documentos importados.

Três detalhes que parecem pequenos e são decisivos para quem usa isto todo
dia no escritório:

- **filtro de período obrigatório**: toda leitura do acervo exige um intervalo
  fechado (`data_inicio`/`data_fim`, ex.: 01/08/2026 a 31/08/2026) ou uma
  competência (`08/2026`, que vira o mês inteiro). Sem período não se lista —
  é o que impede a tela de despejar meses que ninguém pediu;
- **o recorte acontece no banco**, sobre a data de emissão do documento, então
  trocar de mês custa zero requisições à SEFAZ;
- **download em massa** (`/exportar`): um ZIP com os XMLs por empresa + uma
  planilha de relação, que é exatamente o pacote que se manda por e-mail. A
  pasta da empresa leva **só XML de nota** (classificado pelo conteúdo do
  arquivo); o que ficou de fora vai para `pendencias.csv` com o motivo e o que
  fazer — assim o importador da contabilidade não responde "isto é uma
  autorização de nota" no meio de um lote de NF-e.

O único caminho que dispensa período é a exportação por seleção explícita
(`documento_ids=12,34`): ali o operador já apontou nota a nota o que quer.
"""

import csv
import io
import json
import os
import re
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_escrita, requer_papel, usuario_atual
from app.core.plural import contagem, plural
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    DirecaoDocumento,
    DocumentoFiscal,
    DocumentoFiscalFonte,
    Empresa,
    ExecucaoImportacao,
    StatusDocumentoFiscal,
    TipoDocumentoFiscal,
    Usuario,
)
from app.services import auditoria, xml_integridade
from app.schemas import (
    DocumentoDetalhe,
    DocumentoFonteResposta,
    DocumentoFiscalResposta,
    DocumentosExcluirLote,
    ManifestacaoConclusiva,
    ResultadoManifestacaoConclusiva,
    EmpresaResumoDocumentos,
    EstimativaExportacao,
    ResumoDocumentos,
    ResultadoExclusaoDocumentos,
)
from app.services.periodo import (
    PeriodoInvalido,
    interpretar_periodo,
    interpretar_periodo_obrigatorio,
)
from app.services.referencia import data_referencia_sql

router = APIRouter(prefix="/documentos", tags=["documentos fiscais"])

DESCRICAO_DATA_INICIO = "Data inicial — 01/08/2026 ou 2026-08-01 (obrigatória)"
DESCRICAO_DATA_FIM = "Data final — 31/08/2026 ou 2026-08-31 (obrigatória)"
DESCRICAO_COMPETENCIA = "Atalho para o mês inteiro: MM/AAAA, ex.: 08/2026"


def _empresa_do_escritorio(db: Session, empresa_id: int, escritorio_id: int) -> Empresa:
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return empresa


def _periodo_obrigatorio(
    competencia: str | None,
    data_inicio: object,
    data_fim: object,
    *,
    onde: str = "consulta",
):
    """
    Lê o período do pedido e recusa (422) quando ele não veio completo.

    A mensagem é a que aparece na tela, então precisa dizer o que digitar.
    """
    try:
        return interpretar_periodo_obrigatorio(
            competencia, data_inicio, data_fim, onde=onde
        )
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _filtrar(
    consulta,
    *,
    ids: list[int] | None = None,
    tipo: TipoDocumentoFiscal | None = None,
    direcao: DirecaoDocumento | None = None,
    status: StatusDocumentoFiscal | None = None,
    leiaute: str | None = None,
    inicio: date | None = None,
    fim: date | None = None,
    busca: str | None = None,
    numero: str | None = None,
    serie: str | None = None,
    emitente_documento: str | None = None,
    destinatario_documento: str | None = None,
    origem: str | None = None,
    valor_min: float | None = None,
    valor_max: float | None = None,
    apenas_nao_canceladas: bool = False,
):
    """
    Única definição de "que documentos este filtro pega" — a listagem, o
    resumo e o ZIP usam exatamente esta função, para o número da tela bater com
    o número de arquivos que chegam.
    """
    if ids is not None:
        consulta = consulta.filter(DocumentoFiscal.empresa_id.in_(ids))
    if tipo is not None:
        consulta = consulta.filter(DocumentoFiscal.tipo == tipo)
    if direcao is not None:
        consulta = consulta.filter(DocumentoFiscal.direcao == direcao)
    if status is not None:
        consulta = consulta.filter(DocumentoFiscal.status == status)
    if leiaute:
        if leiaute not in {"completo", "resumo", "metadados"}:
            raise HTTPException(status_code=422, detail="leiaute deve ser 'completo', 'resumo' ou 'metadados'.")
        consulta = consulta.filter(DocumentoFiscal.leiaute == leiaute)
    if origem:
        consulta = consulta.filter(DocumentoFiscal.origem == origem.strip().lower())
    if apenas_nao_canceladas:
        consulta = consulta.filter(DocumentoFiscal.status != StatusDocumentoFiscal.CANCELADA)

    if numero and numero.strip():
        digitos = re.sub(r"\D", "", numero)
        alvo = digitos.lstrip("0") or digitos or numero.strip()
        consulta = consulta.filter(or_(DocumentoFiscal.numero == alvo, DocumentoFiscal.numero == digitos))
    if serie and serie.strip():
        serie_limpa = serie.strip()
        serie_sem_zeros = serie_limpa.lstrip("0") or "0"
        consulta = consulta.filter(or_(DocumentoFiscal.serie == serie_limpa, DocumentoFiscal.serie == serie_sem_zeros))
    if emitente_documento and emitente_documento.strip():
        consulta = consulta.filter(DocumentoFiscal.emitente_documento.like(f"%{_somente_digitos(emitente_documento) or emitente_documento.strip()}%"))
    if destinatario_documento and destinatario_documento.strip():
        consulta = consulta.filter(DocumentoFiscal.destinatario_documento.like(f"%{_somente_digitos(destinatario_documento) or destinatario_documento.strip()}%"))
    if valor_min is not None:
        consulta = consulta.filter(DocumentoFiscal.valor_total >= valor_min)
    if valor_max is not None:
        consulta = consulta.filter(DocumentoFiscal.valor_total <= valor_max)

    if busca and busca.strip():
        termo = busca.strip()
        padrao = f"%{termo}%"
        condicoes = [
            DocumentoFiscal.chave_acesso.like(padrao),
            DocumentoFiscal.nsu.like(padrao),
            DocumentoFiscal.numero.like(padrao),
            DocumentoFiscal.serie.like(padrao),
            DocumentoFiscal.emitente_nome.ilike(padrao),
            DocumentoFiscal.emitente_documento.like(padrao),
            DocumentoFiscal.destinatario_nome.ilike(padrao),
            DocumentoFiscal.destinatario_documento.like(padrao),
        ]
        digitos = re.sub(r"\D", "", termo)
        if digitos:
            # "3401" em busca por número: o contador digita assim o tempo todo.
            condicoes.append(DocumentoFiscal.numero == (digitos.lstrip("0") or "0"))
            condicoes.append(DocumentoFiscal.numero == digitos)
            condicoes.append(DocumentoFiscal.chave_acesso.like(f"%{digitos}%"))
        consulta = consulta.filter(or_(*condicoes))

    if inicio or fim:
        # Uma única expressão de data em todo o sistema: a data de emissão.
        # Ver app/services/referencia.py para o porquê.
        emissao = data_referencia_sql()
        if inicio:
            consulta = consulta.filter(emissao >= inicio)
        if fim:
            consulta = consulta.filter(emissao <= fim)
    return consulta


def _parse_ids(valor: str | None, *, nome: str) -> list[int] | None:
    if not valor or not valor.strip():
        return None
    ids = []
    for pedaco in valor.split(","):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        try:
            ids.append(int(pedaco))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{nome} inválido: {pedaco!r}") from exc
    return ids or None


def _parse_empresas(valor: str | None) -> list[int] | None:
    """`empresa_ids=1,2,3` (vazio = todas as empresas visíveis do escritório)."""
    return _parse_ids(valor, nome="empresa_id")


def _somente_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def _parse_empresa_id(valor: int | str | None) -> int | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return int(texto)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"empresa_id inválido: {valor!r}") from exc


def _ids_empresas_do_escritorio(
    db: Session,
    *,
    escritorio_id: int,
    empresa_id: int | str | None = None,
    empresa_ids: str | None = None,
) -> list[int]:
    """Resolve empresa única/lista/todas e barra ids de outro escritório."""
    ids = _parse_empresas(empresa_ids)
    empresa_unica = _parse_empresa_id(empresa_id)
    if empresa_unica is not None:
        _empresa_do_escritorio(db, empresa_unica, escritorio_id)
        ids = [empresa_unica]

    empresas_do_escritorio = {
        linha[0] for linha in db.query(Empresa.id).filter(Empresa.escritorio_id == escritorio_id).all()
    }
    if ids is None:
        return sorted(empresas_do_escritorio)

    invalidos = set(ids) - empresas_do_escritorio
    if invalidos:
        raise HTTPException(status_code=403, detail=f"{plural(len(invalidos), 'Empresa', 'Empresas')} fora deste escritório: {sorted(invalidos)}")
    # Deduplica preservando a ordem que veio da tela.
    vistos: list[int] = []
    for item in ids:
        if item not in vistos:
            vistos.append(item)
    return vistos


@router.get("/resumo", response_model=ResumoDocumentos)
def resumo_documentos(
    empresa_id: int | None = None,
    empresa_ids: str | None = Query(default=None, description="1,2,3 — vazio = todas"),
    tipo: TipoDocumentoFiscal | None = None,
    direcao: DirecaoDocumento | None = None,
    status: StatusDocumentoFiscal | None = None,
    leiaute: str | None = Query(default=None, description="completo | resumo | metadados"),
    competencia: str | None = Query(default=None, description=DESCRICAO_COMPETENCIA),
    data_inicio: str | None = Query(default=None, description=DESCRICAO_DATA_INICIO),
    data_fim: str | None = Query(default=None, description=DESCRICAO_DATA_FIM),
    busca: str | None = Query(default=None),
    numero: str | None = Query(default=None),
    serie: str | None = Query(default=None),
    emitente_documento: str | None = Query(default=None),
    destinatario_documento: str | None = Query(default=None),
    origem: str | None = Query(default=None),
    valor_min: float | None = Query(default=None),
    valor_max: float | None = Query(default=None),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Total de notas, separando canceladas — com exatamente o mesmo filtro de
    período da listagem (antes o resumo contava tudo e discordava da lista).
    """
    periodo = _periodo_obrigatorio(competencia, data_inicio, data_fim, onde="do resumo")

    ids = _ids_empresas_do_escritorio(
        db, escritorio_id=escritorio_id, empresa_id=empresa_id, empresa_ids=empresa_ids
    )
    if not ids:
        return ResumoDocumentos(total=0, normais=0, canceladas=0, por_tipo={})

    base = _filtrar(
        db.query(DocumentoFiscal).join(Empresa).filter(Empresa.escritorio_id == escritorio_id),
        ids=ids,
        tipo=tipo,
        direcao=direcao,
        status=status,
        leiaute=leiaute,
        inicio=periodo.inicio,
        fim=periodo.fim,
        busca=busca,
        numero=numero,
        serie=serie,
        emitente_documento=emitente_documento,
        destinatario_documento=destinatario_documento,
        origem=origem,
        valor_min=valor_min,
        valor_max=valor_max,
    )

    total = base.count()
    normais = base.filter(DocumentoFiscal.status == StatusDocumentoFiscal.NORMAL).count()
    canceladas = base.filter(DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA).count()

    por_tipo: dict[str, int] = {}
    for tipo, qtd in (
        base.with_entities(DocumentoFiscal.tipo, func.count(DocumentoFiscal.id))
        .group_by(DocumentoFiscal.tipo)
        .all()
    ):
        por_tipo[tipo.value if hasattr(tipo, "value") else str(tipo)] = qtd

    return ResumoDocumentos(total=total, normais=normais, canceladas=canceladas, por_tipo=por_tipo)


@router.get("", response_model=list[DocumentoFiscalResposta])
def listar_documentos(
    empresa_id: int | None = None,
    empresa_ids: str | None = Query(default=None, description="1,2,3 — vazio = todas"),
    tipo: TipoDocumentoFiscal | None = None,
    direcao: DirecaoDocumento | None = None,
    status: StatusDocumentoFiscal | None = None,
    leiaute: str | None = Query(default=None, description="completo | resumo | metadados"),
    competencia: str | None = Query(default=None, description=DESCRICAO_COMPETENCIA),
    data_inicio: str | None = Query(default=None, description=DESCRICAO_DATA_INICIO),
    data_fim: str | None = Query(default=None, description=DESCRICAO_DATA_FIM),
    busca: str | None = Query(default=None, description="chave, número, NSU, emitente ou destinatário"),
    numero: str | None = Query(default=None),
    serie: str | None = Query(default=None),
    emitente_documento: str | None = Query(default=None),
    destinatario_documento: str | None = Query(default=None),
    origem: str | None = Query(default=None),
    valor_min: float | None = Query(default=None),
    valor_max: float | None = Query(default=None),
    limit: int = Query(default=500, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Lista as notas do período pedido.

    O período é **obrigatório**: informe `data_inicio`/`data_fim`
    (01/08/2026 a 31/08/2026) ou `competencia` (08/2026, que vira o mês
    inteiro). Sem ele a resposta é 422 com a instrução — listar "tudo" era
    justamente o que enchia a tela de meses que ninguém pediu.
    """
    periodo = _periodo_obrigatorio(competencia, data_inicio, data_fim, onde="da listagem")

    ids = _ids_empresas_do_escritorio(
        db, escritorio_id=escritorio_id, empresa_id=empresa_id, empresa_ids=empresa_ids
    )
    if not ids:
        return []

    consulta = _filtrar(
        db.query(DocumentoFiscal),
        ids=ids,
        tipo=tipo,
        direcao=direcao,
        status=status,
        leiaute=leiaute,
        inicio=periodo.inicio,
        fim=periodo.fim,
        busca=busca,
        numero=numero,
        serie=serie,
        emitente_documento=emitente_documento,
        destinatario_documento=destinatario_documento,
        origem=origem,
        valor_min=valor_min,
        valor_max=valor_max,
    )
    return consulta.order_by(DocumentoFiscal.data_emissao.desc(), DocumentoFiscal.id.desc()).offset(offset).limit(limit).all()


@router.get("/por-empresa", response_model=list[EmpresaResumoDocumentos])
def resumo_por_empresa(
    competencia: str | None = Query(default=None, description=DESCRICAO_COMPETENCIA),
    data_inicio: str | None = Query(default=None, description=DESCRICAO_DATA_INICIO),
    data_fim: str | None = Query(default=None, description=DESCRICAO_DATA_FIM),
    tipo: TipoDocumentoFiscal | None = None,
    direcao: DirecaoDocumento | None = None,
    status: StatusDocumentoFiscal | None = None,
    leiaute: str | None = Query(default=None, description="completo | resumo | metadados"),
    busca: str | None = Query(default=None),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Quantas notas cada empresa tem no período/filtro pedido.

    Antes, quando só `tipo` era informado, `total` vinha filtrado mas
    canceladas/resumos/valor ficavam zerados; agora todos os números nascem da
    mesma consulta usada pela listagem/exportação.

    O período é obrigatório, como em todo o resto da tela.
    """
    periodo = _periodo_obrigatorio(
        competencia, data_inicio, data_fim, onde="do resumo por empresa"
    )

    empresas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id)
        .order_by(Empresa.razao_social)
        .all()
    )
    ids = [empresa.id for empresa in empresas]
    if not ids:
        return []

    consulta = _filtrar(
        db.query(
            DocumentoFiscal.empresa_id,
            func.count(DocumentoFiscal.id),
            func.sum(case((DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA, 1), else_=0)),
            func.sum(case((DocumentoFiscal.leiaute != "completo", 1), else_=0)),
            func.coalesce(
                func.sum(
                    case(
                        (DocumentoFiscal.status != StatusDocumentoFiscal.CANCELADA, DocumentoFiscal.valor_total),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
        ),
        ids=ids,
        tipo=tipo,
        direcao=direcao,
        status=status,
        leiaute=leiaute,
        inicio=periodo.inicio,
        fim=periodo.fim,
        busca=busca,
    ).group_by(DocumentoFiscal.empresa_id)

    por_empresa = {
        empresa_id: (total or 0, canceladas or 0, resumos or 0, float(soma or 0))
        for empresa_id, total, canceladas, resumos, soma in consulta.all()
    }

    saida = []
    for empresa in empresas:
        total, canceladas, resumos, soma = por_empresa.get(empresa.id, (0, 0, 0, 0.0))
        saida.append(
            EmpresaResumoDocumentos(
                empresa_id=empresa.id,
                razao_social=empresa.razao_social,
                total=total,
                normais=total - canceladas,
                canceladas=canceladas,
                sem_xml_completo=resumos,
                valor_total=soma,
            )
        )
    return saida

@router.get("/exportar/estimativa", response_model=EstimativaExportacao)
def estimativa_exportacao(
    empresa_id: str | None = None,
    empresa_ids: str | None = None,
    tipo: TipoDocumentoFiscal | None = None,
    direcao: DirecaoDocumento | None = None,
    status: StatusDocumentoFiscal | None = None,
    competencia: str | None = Query(default=None, description=DESCRICAO_COMPETENCIA),
    data_inicio: str | None = Query(default=None, description=DESCRICAO_DATA_INICIO),
    data_fim: str | None = Query(default=None, description=DESCRICAO_DATA_FIM),
    incluir_canceladas: bool = True,
    documento_ids: str | None = Query(default=None, description="seleção da tela: 12,34,56"),
    busca: str | None = Query(default=None, description="mesma busca da tela"),
    leiaute: str | None = Query(default=None, description="completo | resumo | metadados"),
    numero: str | None = Query(default=None),
    serie: str | None = Query(default=None),
    emitente_documento: str | None = Query(default=None),
    destinatario_documento: str | None = Query(default=None),
    origem: str | None = Query(default=None),
    valor_min: float | None = Query(default=None),
    valor_max: float | None = Query(default=None),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Quantos arquivos e quantos MB o download vai dar — sem montar o ZIP.

    Existe para o operador saber onde está pisando antes de clicar em
    "baixar tudo" (e para a tela avisar quando o filtro passa do teto).
    """
    ids, periodo, apenas_nao_canceladas, selecionados = _params_export(
        db,
        escritorio_id=escritorio_id,
        empresa_id=empresa_id,
        empresa_ids=empresa_ids,
        competencia=competencia,
        data_inicio=data_inicio,
        data_fim=data_fim,
        incluir_canceladas=incluir_canceladas,
        documento_ids=documento_ids,
    )
    consulta = _consulta_export(
        db,
        ids=ids,
        tipo=tipo,
        direcao=direcao,
        status=status,
        inicio=periodo.inicio,
        fim=periodo.fim,
        apenas_nao_canceladas=apenas_nao_canceladas,
        documento_ids=selecionados,
        busca=busca,
        leiaute=leiaute,
        numero=numero,
        serie=serie,
        emitente_documento=emitente_documento,
        destinatario_documento=destinatario_documento,
        origem=origem,
        valor_min=valor_min,
        valor_max=valor_max,
    )
    total = consulta.count()
    # Mesmo filtro, contando só o que não é nota inteira. É um COUNT no banco
    # (a estimativa existe para responder rápido, não para ler o acervo), então
    # vale o cadastro: uma linha "completo" que na verdade guarda um resNFe só
    # aparece na pendencias.csv do pacote. Melhor avisar "≈N" antes do clique do
    # que deixar o operador descobrir no arquivo.
    sem_xml_completo = (
        consulta.filter(
            or_(
                DocumentoFiscal.leiaute.is_(None),
                DocumentoFiscal.leiaute != "completo",
            )
        )
        .with_entities(func.count(DocumentoFiscal.id))
        .scalar()
        or 0
    )
    return EstimativaExportacao(
        documentos=total,
        limite=settings.limite_documentos_por_exportacao,
        empresas=len(ids or []),
        periodo=periodo.rotulo(),
        estimado_bytes=_estimar_bytes(db, ids, total),
        sem_xml_completo=int(sem_xml_completo),
    )


@router.get("/exportar/csv")
def exportar_relacao_csv(
    empresa_id: str | None = None,
    empresa_ids: str | None = None,
    tipo: TipoDocumentoFiscal | None = None,
    direcao: DirecaoDocumento | None = None,
    status: StatusDocumentoFiscal | None = None,
    competencia: str | None = Query(default=None, description=DESCRICAO_COMPETENCIA),
    data_inicio: str | None = Query(default=None, description=DESCRICAO_DATA_INICIO),
    data_fim: str | None = Query(default=None, description=DESCRICAO_DATA_FIM),
    incluir_canceladas: bool = True,
    documento_ids: str | None = Query(default=None, description="seleção da tela: 12,34,56"),
    busca: str | None = Query(default=None, description="mesma busca da tela"),
    leiaute: str | None = Query(default=None, description="completo | resumo | metadados"),
    numero: str | None = Query(default=None),
    serie: str | None = Query(default=None),
    emitente_documento: str | None = Query(default=None),
    destinatario_documento: str | None = Query(default=None),
    origem: str | None = Query(default=None),
    valor_min: float | None = Query(default=None),
    valor_max: float | None = Query(default=None),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(usuario_atual),
):
    """Relação CSV do mesmo filtro do ZIP, sem baixar os XMLs."""
    ids, periodo, apenas_nao_canceladas, selecionados = _params_export(
        db,
        escritorio_id=escritorio_id,
        empresa_id=empresa_id,
        empresa_ids=empresa_ids,
        competencia=competencia,
        data_inicio=data_inicio,
        data_fim=data_fim,
        incluir_canceladas=incluir_canceladas,
        documento_ids=documento_ids,
    )
    consulta = _consulta_export(
        db,
        ids=ids,
        tipo=tipo,
        direcao=direcao,
        status=status,
        inicio=periodo.inicio,
        fim=periodo.fim,
        apenas_nao_canceladas=apenas_nao_canceladas,
        documento_ids=selecionados,
        busca=busca,
        leiaute=leiaute,
        numero=numero,
        serie=serie,
        emitente_documento=emitente_documento,
        destinatario_documento=destinatario_documento,
        origem=origem,
        valor_min=valor_min,
        valor_max=valor_max,
    ).order_by(Empresa.razao_social, DocumentoFiscal.data_emissao.desc())

    total = consulta.count()
    auditoria.registrar(
        db, usuario, "exportacao_csv",
        detalhe=f"{contagem(total, 'documento', 'documentos')} · {periodo.rotulo()}" + (f" · tipo {tipo.value}" if tipo else ""),
    )
    db.commit()
    if total == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum documento no filtro escolhido ({periodo.rotulo()}).",
        )

    caminho, _linhas = _montar_csv_arquivo(consulta)
    nome = "Fluxa_relacao_" + re.sub(r"[^0-9A-Za-z_.-]+", "_", periodo.rotulo()) + ".csv"
    from starlette.background import BackgroundTask

    return FileResponse(
        caminho,
        media_type="text/csv; charset=utf-8",
        filename=nome,
        content_disposition_type="attachment",
        background=BackgroundTask(_apagar, caminho),
    )


@router.get("/exportar")
def exportar_xmls(
    empresa_id: str | None = None,
    empresa_ids: str | None = None,
    tipo: TipoDocumentoFiscal | None = None,
    direcao: DirecaoDocumento | None = None,
    status: StatusDocumentoFiscal | None = None,
    competencia: str | None = Query(default=None, description=DESCRICAO_COMPETENCIA),
    data_inicio: str | None = Query(default=None, description=DESCRICAO_DATA_INICIO),
    data_fim: str | None = Query(default=None, description=DESCRICAO_DATA_FIM),
    incluir_canceladas: bool = True,
    documento_ids: str | None = Query(default=None, description="seleção da tela: 12,34,56"),
    busca: str | None = Query(default=None, description="mesma busca da tela"),
    leiaute: str | None = Query(default=None, description="completo | resumo | metadados"),
    numero: str | None = Query(default=None),
    serie: str | None = Query(default=None),
    emitente_documento: str | None = Query(default=None),
    destinatario_documento: str | None = Query(default=None),
    origem: str | None = Query(default=None),
    valor_min: float | None = Query(default=None),
    valor_max: float | None = Query(default=None),
    incluir_relatorio: bool = Query(default=True, description="CSV com a relação, pronto para o Excel"),
    incluir_incompletos: bool = Query(
        default=False,
        description=(
            "leva também os documentos sem XML completo, em Fluxa/_sem-xml-completo/ "
            "(nunca misturados com as notas)"
        ),
    ),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(usuario_atual),
):
    """
    ZIP com **todas as notas** do filtro — a resposta para "baixar todos os XMLs
    encontrados", que antes só existia nota a nota.

    Estrutura: `Fluxa/<empresa>/<tipo>/<chave>.xml`, mais `relacao.csv` e
    `pendencias.csv` (separador `;` + BOM, abrem direto no Excel pt-BR). O
    arquivo é montado em streaming no disco temporário e apagado no fim — 25 mil
    XMLs não cabem na memória do container, e um navegador não precisa esperar o
    ZIP inteiro estar pronto para o download começar.

    **Só XML de nota entra na pasta da empresa.** Resumo, protocolo e evento
    ficam de fora e aparecem em `Fluxa/pendencias.csv` com o motivo e o que
    fazer — o pacote que o contador recebe é importável de primeira, em vez de
    devolver "isto é uma autorização de nota" no meio do lote.
    """
    ids, periodo, apenas_nao_canceladas, selecionados = _params_export(
        db,
        escritorio_id=escritorio_id,
        empresa_id=empresa_id,
        empresa_ids=empresa_ids,
        competencia=competencia,
        data_inicio=data_inicio,
        data_fim=data_fim,
        incluir_canceladas=incluir_canceladas,
        documento_ids=documento_ids,
    )
    consulta = _consulta_export(
        db,
        ids=ids,
        tipo=tipo,
        direcao=direcao,
        status=status,
        inicio=periodo.inicio,
        fim=periodo.fim,
        apenas_nao_canceladas=apenas_nao_canceladas,
        documento_ids=selecionados,
        busca=busca,
        leiaute=leiaute,
        numero=numero,
        serie=serie,
        emitente_documento=emitente_documento,
        destinatario_documento=destinatario_documento,
        origem=origem,
        valor_min=valor_min,
        valor_max=valor_max,
    )

    limite = settings.limite_documentos_por_exportacao
    total = consulta.count()
    registro_auditoria = auditoria.registrar(
        db, usuario, "exportacao_zip",
        detalhe=f"{contagem(total, 'documento', 'documentos')} · {periodo.rotulo()}" + (f" · tipo {tipo.value}" if tipo else ""),
    )
    db.commit()
    if total == 0:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Nenhum documento no filtro escolhido ({periodo.rotulo()}). "
                "Rode a importação do período antes ou amplie o filtro."
            ),
        )
    if total > limite:
        raise HTTPException(
            status_code=413,
            detail=(
                f"{total} documentos-passam o teto de {limite} por download. "
                "Reduza o período (ex.: um mês por vez) ou exporte por empresa."
            ),
        )

    caminho, notas_no_pacote, total_pendencias = _montar_zip(
        consulta.order_by(Empresa.razao_social, DocumentoFiscal.data_emissao.desc()).yield_per(200),
        periodo,
        incluir_relatorio=incluir_relatorio,
        incluir_incompletos=incluir_incompletos,
    )

    # A auditoria é o único rastro de "o que o contador recebeu naquele dia".
    # Sem a contagem de pendências não dá para responder depois a pergunta
    # "por que o lote de 09 faltou 14 notas?" — agora dá.
    registro_auditoria.detalhe = (
        f"{contagem(total, 'documento', 'documentos')} no filtro · {contagem(notas_no_pacote, 'XML de nota', 'XMLs de nota')} no pacote · "
        f"{contagem(total_pendencias, 'pendência', 'pendências')} · {periodo.rotulo()}"
        + (f" · tipo {tipo.value}" if tipo else "")
        + (" · incluiu incompletos" if incluir_incompletos else "")
    )
    db.commit()

    nome = "Fluxa_" + re.sub(r"[^0-9A-Za-z_.-]+", "_", periodo.rotulo()) + ".zip"
    from starlette.background import BackgroundTask

    return FileResponse(
        caminho,
        media_type="application/zip",
        filename=nome,
        content_disposition_type="attachment",
        background=BackgroundTask(_apagar, caminho),
    )


def _params_export(
    db: Session,
    *,
    escritorio_id: int,
    empresa_id: int | str | None,
    empresa_ids: str | None,
    competencia: str | None,
    data_inicio: object,
    data_fim: object,
    incluir_canceladas: bool,
    documento_ids: str | None = None,
):
    """
    Parâmetros comuns das três saídas (estimativa, CSV e ZIP).

    Período obrigatório, com **uma** exceção: quando o pedido traz
    `documento_ids`, o operador já escolheu nota a nota na tela — exigir data
    ali seria pedir duas vezes a mesma informação (e o "baixar seleção"
    deixaria de funcionar).
    """
    # A checagem de escritório vem primeiro de propósito: pedir XML de outro
    # cliente é 403 mesmo que o período também esteja faltando. Trocar a ordem
    # transformaria uma tentativa de acesso indevido num inofensivo "faltou a
    # data", escondendo o que realmente aconteceu.
    ids = _ids_empresas_do_escritorio(
        db, escritorio_id=escritorio_id, empresa_id=empresa_id, empresa_ids=empresa_ids
    )
    selecao = _parse_ids(documento_ids, nome="documento_id")
    if selecao:
        try:
            periodo = interpretar_periodo(competencia, data_inicio, data_fim)
        except PeriodoInvalido as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        periodo = _periodo_obrigatorio(
            competencia, data_inicio, data_fim, onde="do download"
        )
    return ids, periodo, (not incluir_canceladas), selecao


def _consulta_export(
    db: Session,
    *,
    ids: list[int],
    tipo: TipoDocumentoFiscal | None,
    direcao: DirecaoDocumento | None,
    status: StatusDocumentoFiscal | None,
    inicio: date | None,
    fim: date | None,
    apenas_nao_canceladas: bool,
    documento_ids: list[int] | None = None,
    busca: str | None = None,
    leiaute: str | None = None,
    numero: str | None = None,
    serie: str | None = None,
    emitente_documento: str | None = None,
    destinatario_documento: str | None = None,
    origem: str | None = None,
    valor_min: float | None = None,
    valor_max: float | None = None,
):
    """
    `documento_ids` é a seleção da tela ("baixar estes 12 XMLs"). O resto do
    filtro continua valendo, então a seleção nunca atravessa o escritório de
    outro cliente: um id de fora simplesmente não volta no resultado.
    """
    consulta = _filtrar(
        db.query(DocumentoFiscal, Empresa).join(
            Empresa, Empresa.id == DocumentoFiscal.empresa_id
        ),
        ids=ids or [-1],
        tipo=tipo,
        direcao=direcao,
        status=status,
        inicio=inicio,
        fim=fim,
        busca=busca,
        leiaute=leiaute,
        numero=numero,
        serie=serie,
        emitente_documento=emitente_documento,
        destinatario_documento=destinatario_documento,
        origem=origem,
        valor_min=valor_min,
        valor_max=valor_max,
        apenas_nao_canceladas=apenas_nao_canceladas,
    )
    if documento_ids:
        consulta = consulta.filter(DocumentoFiscal.id.in_(documento_ids))
    return consulta


def _estimar_bytes(db: Session, ids: list[int] | None, total: int) -> int:
    """
    Estimativa de tamanho: XML fiscal médio ≈ 6 KB, refinado pela média real
    dos arquivos do caso (se já houver alguns no disco, usamos o que existe).
    """
    if not total:
        return 0
    media = 6000
    try:
        amostra = (
            db.query(DocumentoFiscal.xml_path)
            .filter(DocumentoFiscal.empresa_id.in_(ids or [-1]))
            .limit(25)
            .all()
        )
        tamanhos = [
            os.path.getsize(caminho)
            for (caminho,) in amostra
            if caminho and os.path.isfile(caminho)
        ]
        if tamanhos:
            media = sum(tamanhos) // len(tamanhos)
    except OSError:  # pragma: no cover - disco indisponível não derruba a estimativa
        pass
    return media * total


def _slug(texto: str) -> str:
    limpo = re.sub(r"[^\w\s-]", "", texto or "", flags=re.UNICODE).strip()
    limpo = re.sub(r"\s+", "-", limpo)
    return limpo[:60] or "empresa"


def _cabecalho_relatorio() -> list[str]:
    return [
        "empresa",
        "cnpj",
        "tipo",
        "direcao",
        "competencia",
        "data_emissao",
        "numero",
        "serie",
        "chave_acesso",
        "emitente_cnpj_cpf",
        "emitente_razao_social",
        "destinatario_cnpj_cpf",
        "destinatario_razao_social",
        "valor_total",
        "situacao",
        "xml_completo",
        "origem",
        "nsu",
        "arquivo",
    ]


def _situacao_do_xml(
    documento: DocumentoFiscal,
    conteudo: bytes | None,
    *,
    arquivo_ausente_no_disco: bool = False,
) -> tuple[str, str | None]:
    """Diz, do mesmo jeito para todo o pacote, se o XML daquele documento é a NOTA.

    Devolve `(situacao_csv, leiaute_real)`. É **uma** função porque o ZIP, a
    `relacao.csv` e a `pendencias.csv` precisam concordar — antes cada um
    classificava por conta própria e o pacote podia levar um `resNFe` na pasta
    da empresa enquanto o CSV dizia "so-resumo": dois relatos diferentes do
    mesmo arquivo, e o importador da contabilidade era quem pagava a conta.

    `situacao_csv` é o valor da coluna `xml_completo`:

    - `sim`                       → o pacote tem a nota inteira;
    - `so-resumo`                 → o arquivo é resNFe/protNFe/evento (não é a nota);
    - `metadados-sem-xml`         → a fonte nunca entregou XML (NFS-e por metadados);
    - `arquivo-ausente-no-disco`  → o banco diz "completo", o arquivo sumiu.

    A decisão sai do CONTEÚDO, não do cadastro: no legado há linha marcada
    "completo" com `resNFe` no disco, e é justamente essa linha que fazia o
    importador responder "isto é uma autorização de nota".
    """
    if arquivo_ausente_no_disco:
        # O banco diz "XML completo" (leiaute == completo), mas o arquivo não
        # está no disco na hora de montar o pacote — sem isto o contador via
        # "sim" e "arquivo" vazio sem entender por quê, achando que o download
        # simplesmente falhou. Aparece separado de "so-resumo"/"metadados-sem-xml"
        # porque a causa é outra: perda/ausência do arquivo, não falta de captura.
        return "arquivo-ausente-no-disco", None

    real = xml_integridade.classificar_bytes(conteudo) or xml_integridade.leiaute_do_arquivo(
        documento.xml_path
    )
    if real is None:
        # Sem arquivo legível não há o que conferir: vale o cadastro.
        return (
            (
                "sim"
                if documento.leiaute == "completo"
                else "metadados-sem-xml"
                if documento.leiaute == "metadados"
                else "so-resumo"
            ),
            None,
        )
    if xml_integridade.nao_e_a_nota(real):
        return "so-resumo", real
    return "sim", real


def _cabecalho_pendencias() -> list[str]:
    """Cabeçalho da `pendencias.csv` — o que ficou FORA do pacote de notas."""
    return [
        "empresa",
        "cnpj",
        "tipo",
        "chave_acesso",
        "competencia",
        "data_emissao",
        "numero",
        "serie",
        "emitente_cnpj_cpf",
        "emitente_razao_social",
        "valor_total",
        "situacao",
        "motivo",
        "o_que_fazer",
        "arquivo_no_pacote",
    ]


def _motivo_e_acao(
    documento: DocumentoFiscal,
    situacao_xml: str,
    leiaute_real: str | None,
) -> tuple[str, str]:
    """Causa e saída de cada documento que não entrou no pacote de notas.

    A `pendencias.csv` existe para a pergunta que o operador fazia abrindo o
    ZIP: "cadê a nota X?". Sem esta lista a resposta era abrir a
    `relacao.csv`, ler `so-resumo` e adivinhar o resto. Cada linha sai com o
    porquê e a ação, usando os MESMOS rótulos da tela ("Buscar XML completo",
    "Manifestar operação") para ninguém ter que traduzir.
    """
    if situacao_xml == "arquivo-ausente-no-disco":
        return (
            "o cadastro diz 'XML completo', mas o arquivo não está no disco do servidor",
            "Recapturar o XML pela SEFAZ (distribuição) e gerar o pacote de novo",
        )
    if situacao_xml == "metadados-sem-xml":
        return (
            "a fonte de origem não disponibilizou XML (NFS-e recebida por metadados)",
            "Escriturar pelo JSON normalizado na pasta metadados/, ou pedir o XML ao prestador",
        )
    if documento.manifestacao_cstat == "596":
        return (
            "a SEFAZ não aceita mais a Ciência da Operação nesta nota "
            "(cStat 596 — passou dos 10 dias da autorização)",
            "Manifestar operação (Confirmação da Operação, evento 210200) para liberar o XML completo",
        )
    if documento.manifestacao_erro:
        return (
            f"a manifestação foi recusada pela SEFAZ: {documento.manifestacao_erro}",
            "Manifestar operação — conferindo antes a recusa registrada na SEFAZ",
        )
    if leiaute_real == "protocolo":
        return (
            "o arquivo em disco é só o protocolo de autorização (protNFe), sem a nota",
            "Buscar XML completo",
        )
    if leiaute_real == "evento":
        return (
            "o arquivo em disco é um evento da nota (cancelamento/carta de correção), não a nota",
            "Buscar XML completo",
        )
    if documento.manifestado_em is None:
        return (
            "a SEFAZ distribui apenas o resumo (resNFe) enquanto a nota não for manifestada",
            "Manifestar operação (Ciência da Operação) e depois Buscar XML completo",
        )
    return (
        "a nota já foi manifestada, mas o XML completo ainda não foi capturado",
        "Buscar XML completo",
    )


def _linha_pendencias(
    documento: DocumentoFiscal,
    empresa: Empresa,
    situacao_xml: str,
    leiaute_real: str | None,
    arquivo_no_pacote: str,
) -> list[str]:
    """Uma linha da `pendencias.csv`: quem é, por que ficou fora e o que fazer."""
    motivo, acao = _motivo_e_acao(documento, situacao_xml, leiaute_real)
    return [
        empresa.razao_social,
        empresa.cnpj_cpf,
        documento.tipo.value if hasattr(documento.tipo, "value") else str(documento.tipo),
        documento.chave_acesso,
        documento.competencia.strftime("%m/%Y") if documento.competencia else "",
        documento.data_emissao.strftime("%d/%m/%Y") if documento.data_emissao else "",
        documento.numero or "",
        documento.serie or "",
        documento.emitente_documento or "",
        documento.emitente_nome or "",
        f"{documento.valor_total:.2f}".replace(".", ","),
        situacao_xml,
        motivo,
        acao,
        arquivo_no_pacote,
    ]


def _linha_relatorio(
    documento: DocumentoFiscal,
    empresa: Empresa,
    arquivo_zip: str,
    *,
    arquivo_ausente_no_disco: bool = False,
    conteudo: bytes | None = None,
) -> list[str]:
    """Uma linha da relacao.csv — e a coluna `xml_completo` não pode mentir.

    A coluna é o que o contador usa para saber se aquele XML serve. Ela já
    checava cadastro × disco; agora checa também o CONTEÚDO do arquivo: um
    `resNFe`/`protNFe` gravado por engano (o caso do `consChNFe` devolvendo
    resumo) aparece como `so-resumo`, e não como "sim" — é o que separa um
    pacote fiscal de um pacote de autorizações.
    """
    situacao_xml, _ = _situacao_do_xml(
        documento, conteudo, arquivo_ausente_no_disco=arquivo_ausente_no_disco
    )
    return [
        empresa.razao_social,
        empresa.cnpj_cpf,
        documento.tipo.value if hasattr(documento.tipo, "value") else str(documento.tipo),
        documento.direcao.value if hasattr(documento.direcao, "value") else str(documento.direcao),
        documento.competencia.strftime("%m/%Y") if documento.competencia else "",
        documento.data_emissao.strftime("%d/%m/%Y") if documento.data_emissao else "",
        documento.numero or "",
        documento.serie or "",
        documento.chave_acesso,
        documento.emitente_documento or "",
        documento.emitente_nome or "",
        documento.destinatario_documento or "",
        documento.destinatario_nome or "",
        f"{documento.valor_total:.2f}".replace(".", ","),
        "CANCELADA" if documento.status == StatusDocumentoFiscal.CANCELADA else "NORMAL",
        situacao_xml,
        documento.origem or "",
        documento.nsu or "",
        arquivo_zip,
    ]


def _montar_csv_arquivo(consulta) -> tuple[str, int]:
    fd, caminho = tempfile.mkstemp(prefix="notasflow-relacao-", suffix=".csv")
    os.close(fd)
    linhas = 0
    with open(caminho, "w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";", lineterminator="\r\n")
        escritor.writerow(_cabecalho_relatorio())
        for documento, empresa in consulta.yield_per(500):
            # Mesma checagem do ZIP: "leiaute completo" no banco não garante
            # que o arquivo ainda existe no disco — sem isto o CSV avulso
            # (sem baixar XML nenhum) mentia "sim" para uma nota cujo XML já
            # não pode mais ser baixado individualmente.
            ausente = documento.leiaute == "completo" and not (
                documento.xml_path and os.path.isfile(documento.xml_path)
            )
            escritor.writerow(_linha_relatorio(documento, empresa, "", arquivo_ausente_no_disco=ausente))
            linhas += 1
    return caminho, linhas


def _montar_zip(
    consulta,
    periodo,
    *,
    incluir_relatorio: bool,
    incluir_incompletos: bool = False,
) -> tuple[str, int, int]:
    """
    Escreve o ZIP num arquivo temporário e devolve
    `(caminho, notas_no_pacote, pendencias)`. O chamador serve via FileResponse
    e apaga no `BackgroundTask`.

    ## A regra que este pacote obedece

    A árvore do ZIP contém **só XML de nota** — o arquivo que tem `infNFe` /
    `infCTe` / `infNFSe` dentro. Nada mais entra na pasta da empresa.

    Por quê: o importador do sistema contábil lê o que está na pasta e reclama
    "isto é uma autorização de nota" quando acha um `resNFe` ou um `protNFe`
    entre as NF-e. O operador baixava o período, mandava por e-mail e recebia
    um erro que não dizia qual arquivo era o culpado. Separar por conteúdo (e
    não pelo `leiaute` do cadastro, que mente no legado) é o que torna o
    pacote importável de primeira.

    O que ficou de fora não some: vai para `Fluxa/pendencias.csv`, com o motivo
    e a ação por documento. Com `incluir_incompletos=True` os XMLs incompletos
    também são gravados, mas em `Fluxa/_sem-xml-completo/` — nunca misturados
    com as notas.
    """
    fd, caminho = tempfile.mkstemp(prefix="notasflow-export-", suffix=".zip")
    os.close(fd)

    relatorio = io.StringIO()
    escritor = csv.writer(relatorio, delimiter=";", lineterminator="\r\n")
    escritor.writerow(_cabecalho_relatorio())

    pendencias = io.StringIO()
    escritor_pendencias = csv.writer(pendencias, delimiter=";", lineterminator="\r\n")
    escritor_pendencias.writerow(_cabecalho_pendencias())

    usados: set[str] = set()
    arquivos_ausentes = 0
    total_pendencias = 0
    notas_no_pacote = 0
    with zipfile.ZipFile(caminho, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as pacote:
        for documento, empresa in consulta.yield_per(200):
            nome_arquivo = f"{documento.chave_acesso}.xml"
            pasta_empresa = f"Fluxa/{_slug(empresa.razao_social)}/{documento.tipo.value}"

            conteudo = b""
            if documento.xml_path and os.path.isfile(documento.xml_path):
                try:
                    with open(documento.xml_path, "rb") as arquivo:
                        conteudo = arquivo.read()
                except OSError:
                    conteudo = b""

            ausente_no_disco = documento.leiaute == "completo" and not conteudo
            if ausente_no_disco:
                arquivos_ausentes += 1
            situacao_xml, leiaute_real = _situacao_do_xml(
                documento, conteudo, arquivo_ausente_no_disco=ausente_no_disco
            )

            arquivo_relatorio = ""
            if situacao_xml == "sim":
                # É a nota inteira: é isto que o pacote existe para entregar.
                endereco = f"{pasta_empresa}/{nome_arquivo}"
                if endereco in usados:  # chave repetida entre empresas diferentes já tem pasta própria
                    endereco = f"{pasta_empresa}/{documento.id}_{nome_arquivo}"
                pacote.writestr(endereco, conteudo)
                usados.add(endereco)
                arquivo_relatorio = endereco
                notas_no_pacote += 1
            elif conteudo and incluir_incompletos:
                # Pedido explícito do operador (checkbox na tela): leva o
                # incompleto também, mas numa árvore à parte. Sem isto o
                # importador voltava a reclamar de "autorização de nota".
                endereco = f"Fluxa/_sem-xml-completo/{_slug(empresa.razao_social)}/{documento.tipo.value}/{nome_arquivo}"
                if endereco in usados:
                    endereco = (
                        f"Fluxa/_sem-xml-completo/{_slug(empresa.razao_social)}"
                        f"/{documento.tipo.value}/{documento.id}_{nome_arquivo}"
                    )
                pacote.writestr(endereco, conteudo)
                usados.add(endereco)
                arquivo_relatorio = endereco
            elif documento.leiaute == "metadados":
                # Algumas fontes entregam NFS-e como metadados, sem contrato
                # de download de XML. Em vez de omitir a nota do pacote (ou
                # fingir que JSON é XML), entregamos sua representação
                # normalizada e deixamos isso explícito no relatório.
                endereco_metadados = (
                    f"{pasta_empresa}/metadados/{documento.id}_{documento.chave_acesso}.json"
                )
                pacote.writestr(
                    endereco_metadados,
                    json.dumps(
                        {
                            "aviso": "A fonte de origem não disponibilizou XML original para esta NFS-e.",
                            "empresa": {
                                "id": empresa.id,
                                "razao_social": empresa.razao_social,
                                "cnpj_cpf": empresa.cnpj_cpf,
                            },
                            "documento": {
                                "id": documento.id,
                                "tipo": documento.tipo.value,
                                "chave_acesso": documento.chave_acesso,
                                "numero": documento.numero,
                                "serie": documento.serie,
                                "data_emissao": (
                                    documento.data_emissao.isoformat()
                                    if documento.data_emissao
                                    else None
                                ),
                                "competencia": (
                                    documento.competencia.isoformat()
                                    if documento.competencia
                                    else None
                                ),
                                "valor_total": f"{documento.valor_total:.2f}",
                                "situacao": documento.situacao,
                                "origem": documento.origem,
                                "identificador_fonte": documento.nsu,
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
                arquivo_relatorio = endereco_metadados

            escritor.writerow(
                _linha_relatorio(
                    documento,
                    empresa,
                    arquivo_relatorio,
                    arquivo_ausente_no_disco=ausente_no_disco,
                    conteudo=conteudo or None,
                )
            )

            if situacao_xml != "sim":
                # Tudo que não é nota entra na lista de pendências — inclusive o
                # JSON de metadados, que está no pacote mas não é importável
                # pela rotina de NF-e/NFS-e do sistema contábil.
                total_pendencias += 1
                escritor_pendencias.writerow(
                    _linha_pendencias(
                        documento, empresa, situacao_xml, leiaute_real, arquivo_relatorio
                    )
                )

        if incluir_relatorio:
            # BOM: sem ele o Excel pt-BR abre "empresa;razao" numa coluna só.
            pacote.writestr("Fluxa/relacao.csv", "\ufeff" + relatorio.getvalue())
            pacote.writestr("Fluxa/pendencias.csv", "\ufeff" + pendencias.getvalue())
            pacote.writestr(
                "Fluxa/LEIA-ME.txt",
                _leia_me(
                    periodo,
                    notas_no_pacote,
                    arquivos_ausentes,
                    pendencias=total_pendencias,
                    incluir_incompletos=incluir_incompletos,
                ),
            )
    return caminho, notas_no_pacote, total_pendencias

def _leia_me(
    periodo,
    quantidade: int,
    arquivos_ausentes: int = 0,
    *,
    pendencias: int = 0,
    incluir_incompletos: bool = False,
) -> str:
    aviso_ausentes = (
        (
            f"\nATENÇÃO: {contagem(arquivos_ausentes, 'documento', 'documentos')} "
              f"{plural(arquivos_ausentes, 'consta', 'constam')} como 'XML completo'\n"
            "no cadastro, mas o arquivo não foi encontrado no disco na hora de\n"
            "gerar este pacote (procure 'arquivo-ausente-no-disco' na coluna\n"
            "xml_completo da relacao.csv). Confira o backup/disco do servidor;\n"
            "não há como recuperar o arquivo original sem capturar de novo pela\n"
            "SEFAZ, dentro do horizonte de distribuição.\n"
        )
        if arquivos_ausentes > 0
        else ""
    )
    if pendencias > 0:
        aviso_pendencias = (
            f"\n{contagem(pendencias, 'documento', 'documentos')} do filtro NÃO "
              f"{plural(pendencias, 'entrou', 'entraram')} no pacote de notas.\n"
            "Estão listados em pendencias.csv, com o motivo e o que fazer em\n"
            "cada caso (buscar XML completo, manifestar operação, recapturar).\n"
            + (
                "Os XMLs deles foram gravados em Fluxa/_sem-xml-completo/ porque\n"
                "você marcou 'incluir incompletos' — não misture essa pasta com\n"
                "as notas na importação.\n"
                if incluir_incompletos
                else ""
            )
        )
    else:
        aviso_pendencias = (
            "\nNenhum documento do filtro ficou de fora: tudo que está aqui é\n"
            "XML de nota inteira (pendencias.csv saiu só com o cabeçalho).\n"
        )
    return (
        "Fluxa — pacote de XMLs fiscais\n"
        "====================================\n"
        f"Período (competência): {periodo.rotulo()}\n"
        f"XMLs de nota no pacote: {quantidade}\n"
        f"Gerado em: {datetime.now(timezone.utc):%d/%m/%Y %H:%M} UTC\n"
        f"{aviso_ausentes}{aviso_pendencias}\n"
        "Estrutura: Fluxa/<empresa>/<tipo>/<chave>.xml\n"
        "  — SÓ XML de nota entra nessas pastas. O pacote é classificado pelo\n"
        "  CONTEÚDO do arquivo, não pelo cadastro: se o XML no disco é um\n"
        "  resNFe/protNFe (resumo/autorização), ele NÃO vai para a pasta da\n"
        "  empresa. É o que impede o importador contábil de responder \"isso é\n"
        "  uma autorização de nota\" no meio de um lote de NF-e.\n"
        "relacao.csv lista TUDO do filtro (coluna xml_completo diz a verdade).\n"
        "pendencias.csv lista o que ficou de fora, com motivo e o que fazer.\n"
        "Ambos abrem direto no Excel (separador ';').\n\n"
        "Notas com 'so-resumo' na coluna xml_completo: a SEFAZ distribui o\n"
        "resumo até que a nota seja manifestada. Use 'Buscar XML completo'\n"
        "no painel — a busca pela chave é limitada a 20 consultas/h por CNPJ.\n"
        "Se a nota passou dos 10 dias da autorização (cStat 596), a Ciência\n"
        "não é mais aceita: a saída é 'Manifestar operação'.\n\n"
        "NFS-e (pasta nfse/): o XML está no leiaute NACIONAL (SPED,\n"
        "nfse.gov.br) — o mesmo documento que a prefeitura/emissor entrega,\n"
        "com a DPS e a assinatura digital dentro. Importe pela rotina de\n"
        "NFS-e do sistema contábil, NÃO pela rotina de NF-e (nota de\n"
        "produto): a rotina de NF-e não lê nota de serviço e rejeita o\n"
        "arquivo com \"não é um arquivo NF-e válido\" / \"arquivo de\n"
        "autorização\" — é aviso do importador, não defeito do XML. Se o\n"
        "sistema contábil só importar NFS-e no leiaute ABRASF, avise o\n"
        "administrador antes de converter por fora: o XML nacional é o\n"
        "documento fiscal original.\n\n"
        "Notas com 'metadados-sem-xml' chegaram de uma fonte que não forneceu o\n"
        "XML original. O pacote contém um JSON normalizado em /metadados,\n"
        "sem inventar um XML fiscal inexistente.\n"
    )


def _apagar(caminho: str) -> None:
    try:
        os.unlink(caminho)
    except OSError:
        pass


def _mensagem_xml_incompleto(real: str | None, documento: DocumentoFiscal) -> str:
    """Explica, em português, por que este download foi bloqueado."""
    if documento.manifestacao_cstat == "596":
        return (
            "Esta nota passou dos 10 dias da Ciência da Operação (cStat 596 da SEFAZ), "
            "que não é mais aceita para ela. O XML completo só é liberado com uma "
            "manifestação conclusiva: use 'Manifestar operação' na ficha da nota "
            "(Confirmação da Operação, se a operação ocorreu)."
        )
    if real == xml_integridade.LEIAUTE_PROTOCOLO:
        return (
            "O arquivo armazenado é somente o protocolo de autorização (protNFe). "
            "A NF-e completa (procNFe) ainda precisa ser recuperada pela SEFAZ. "
            "Use 'Completar XMLs' e baixe novamente após a conclusão."
        )
    if real == xml_integridade.LEIAUTE_EVENTO:
        return (
            "O arquivo armazenado é um EVENTO da NF-e (cancelamento, carta de correção), "
            "não a nota fiscal. O XML completo ainda precisa ser recuperado na SEFAZ."
        )
    return (
        "Esta nota ainda está apenas em resumo (resNFe): a SEFAZ libera o XML "
        "completo depois da manifestação do destinatário. O sistema registra a "
        "Ciência da Operação e baixa a NF-e inteira (procNFe) sozinho — aguarde "
        "alguns instantes e baixe de novo."
    )


@router.get("/{documento_id}/xml")
def baixar_xml(
    documento_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Entrega somente o XML fiscal completo, buscando-o na SEFAZ sob demanda quando ainda em resumo."""
    documento = _documento_do_escritorio(db, documento_id, escritorio_id)
    # O cadastro pode estar desatualizado (versões anteriores gravavam o resumo
    # e marcavam "completo"): o operador está olhando exatamente esta nota,
    # então é aqui que o conserto é feito — e ela volta para a fila de captura.
    if xml_integridade.reconciliar(db, documento):
        db.commit()
    tem_arquivo = bool(documento.xml_path and os.path.isfile(documento.xml_path))
    real_no_disco = xml_integridade.leiaute_do_arquivo(documento.xml_path) if tem_arquivo else None
    eh_resumo_ou_prot = documento.leiaute == "resumo" or xml_integridade.nao_e_a_nota(real_no_disco)

    mensagem_tentativa = ""
    if documento.tipo == TipoDocumentoFiscal.NFE and (eh_resumo_ou_prot or not tem_arquivo):
        from app.worker.tasks import completar_xml_documento_imediato

        _, mensagem_tentativa = completar_xml_documento_imediato(db, documento)
        db.refresh(documento)
        tem_arquivo = bool(documento.xml_path and os.path.isfile(documento.xml_path))

    real = xml_integridade.leiaute_do_arquivo(documento.xml_path) if tem_arquivo else None
    if documento.leiaute == "resumo" or (tem_arquivo and xml_integridade.nao_e_a_nota(real)):
        # Nunca entregar resumo/protocolo/evento com a chave da nota no nome do
        # arquivo: é assim que um XML que não serve para escriturar entra na
        # contabilidade do cliente sem ninguém perceber.
        raise HTTPException(
            status_code=409,
            detail=mensagem_tentativa or _mensagem_xml_incompleto(real, documento),
        )

    if not tem_arquivo:
        if documento.leiaute == "metadados":
            raise HTTPException(
                status_code=409,
                detail="Esta NFS-e foi registrada somente com metadados: a fonte de origem não forneceu XML original. Exporte o período para baixar o JSON normalizado junto da relação CSV.",
            )
        raise HTTPException(status_code=404, detail="Arquivo XML não encontrado no disco")

    return FileResponse(
        documento.xml_path,
        media_type="application/xml",
        filename=f"{documento.chave_acesso}.xml",
    )


@router.post("/{documento_id}/completar-xml", response_model=DocumentoDetalhe)
def completar_xml_individual(
    documento_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """Registra Ciência da Operação (210210) e baixa o XML completo (`procNFe`) pela chave imediatamente."""
    documento = _documento_do_escritorio(db, documento_id, escritorio_id)
    from app.worker.tasks import completar_xml_documento_imediato

    documento.manifestacao_erro = None
    db.commit()
    ok, mensagem = completar_xml_documento_imediato(db, documento)
    auditoria.registrar(
        db,
        usuario,
        "xml_completar_individual",
        entidade="documento_fiscal",
        entidade_id=documento.id,
        detalhe=f"{documento.chave_acesso} ({'completo' if ok else 'pendente'})",
    )
    db.commit()
    if not ok and documento.leiaute != "completo":
        raise HTTPException(status_code=409, detail=mensagem)
    return detalhe_documento(documento_id=documento.id, db=db, escritorio_id=escritorio_id)


@router.post("/completar-xmls")
def completar_xmls(
    empresa_id: int | None = None,
    limite: int = Query(default=20, le=200, ge=1),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """
    Manda o worker buscar, pela chave (`consChNFe`), o XML completo das NFe que
    chegaram só em resumo. Respeita o teto de 20 consultas/h por CNPJ.
    """
    if empresa_id is not None:
        _empresa_do_escritorio(db, empresa_id, escritorio_id)
    from app.worker.tasks import completar_xmls_pendentes

    auditoria.registrar(
        db, usuario, "xmls_completar",
        entidade="empresa" if empresa_id else None,
        entidade_id=empresa_id,
        detalhe=f"limite {min(limite, 20)}/h",
    )
    db.commit()
    completar_xmls_pendentes.delay(empresa_id=empresa_id, limite=min(limite, 20))
    return {
        "disparado": True,
        "aviso": (
            "Ciência da Operação e busca do XML completo pela chave foram disparadas "
            "(respeitando o limite oficial de 20 consultas/h por CNPJ na SEFAZ)."
        ),
    }


@router.post("/manifestar-conclusiva", response_model=list[ResultadoManifestacaoConclusiva])
def manifestar_conclusiva_documentos(
    payload: ManifestacaoConclusiva,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """Registra a manifestação conclusiva das notas selecionadas e busca o XML completo.

    Existe por causa de um prazo da norma, não de uma preferência: a **Ciência
    da Operação** (a via automática) só é aceita até **10 dias** contados da
    autorização da NF-e; depois disso a SEFAZ devolve `cStat 596` e a nota fica
    presa em resumo — sem XML completo para escriturar. As manifestações
    **conclusivas** (Confirmação, Desconhecimento, Operação não Realizada) são
    aceitas por mais tempo — o Ajuste SINIEF 14/2026 fixou **90 dias** (antes
    180) e, vencidos sem evento, a operação é tida como tacitamente confirmada —
    e também liberam a NF-e no Ambiente Nacional, exceto o Desconhecimento.

    É ato de negócio, então não roda sozinho: o operador escolhe o tipo e
    confirma na tela, e a decisão fica registrada na auditoria.
    """
    from app.services.importadores.manifestacao import (
        TIPO_EVENTO_CONFIRMACAO,
        TIPO_EVENTO_DESCONHECIMENTO,
        TIPO_EVENTO_NAO_REALIZADA,
    )
    from app.worker.tasks import manifestar_conclusiva_lote

    documentos = (
        db.query(DocumentoFiscal)
        .join(Empresa)
        .filter(DocumentoFiscal.id.in_(payload.ids), Empresa.escritorio_id == escritorio_id)
        .all()
    )
    encontrados = {documento.id for documento in documentos}
    faltando = [item for item in payload.ids if item not in encontrados]
    if faltando:
        raise HTTPException(status_code=404, detail=f"{plural(len(faltando), 'Documento', 'Documentos')} não {plural(len(faltando), 'encontrado', 'encontrados')}: {faltando}")

    tipos = {
        "confirmacao": TIPO_EVENTO_CONFIRMACAO,
        "desconhecimento": TIPO_EVENTO_DESCONHECIMENTO,
        "nao_realizada": TIPO_EVENTO_NAO_REALIZADA,
    }
    tipo_evento = tipos[payload.tipo]
    if tipo_evento in {TIPO_EVENTO_DESCONHECIMENTO, TIPO_EVENTO_NAO_REALIZADA} and len(
        payload.justificativa
    ) < 15:
        raise HTTPException(
            status_code=422,
            detail=(
                "A SEFAZ exige justificativa de 15 a 255 caracteres para "
                "Desconhecimento e Operação não Realizada."
            ),
        )

    documentos = [documento for documento in documentos if documento.tipo == TipoDocumentoFiscal.NFE]
    if not documentos:
        # CT-e/NFS-e não têm evento de manifestação do destinatário: aceitar a
        # seleção e devolver "nada feito" deixaria o operador achando que o
        # evento foi enviado.
        raise HTTPException(
            status_code=422,
            detail="A manifestação conclusiva existe apenas para NF-e (CT-e e NFS-e não têm o evento).",
        )
    resultados = manifestar_conclusiva_lote(
        db,
        documentos,
        tipo_evento=tipo_evento,
        justificativa=payload.justificativa,
    )
    auditoria.registrar(
        db,
        usuario,
        "manifestacao_conclusiva",
        entidade="documento_fiscal",
        entidade_id=None,
        detalhe=(
            f"{payload.tipo} em {contagem(len(documentos), 'nota', 'notas')}: "
            f"{contagem(sum(1 for item in resultados if item['ok']), 'registrada', 'registradas')}, "
            f"{contagem(sum(1 for item in resultados if not item['ok']), 'recusada', 'recusadas')}"
        ),
    )
    db.commit()
    return resultados


@router.delete("/{documento_id}", response_model=ResultadoExclusaoDocumentos)
def excluir_documento(
    documento_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """Exclui uma nota/documento do escritório logado e remove o XML arquivado."""
    documento = _documento_do_escritorio(db, documento_id, escritorio_id)
    arquivos = _arquivos_exclusivos(db, [documento])
    auditoria.registrar(
        db,
        usuario,
        "documento_excluir",
        entidade="documento_fiscal",
        entidade_id=documento.id,
        detalhe=f"{documento.tipo.value} {documento.chave_acesso}",
    )
    db.delete(documento)
    db.commit()
    removidos = _remover_arquivos(arquivos)
    return ResultadoExclusaoDocumentos(excluidos=1, ids=[documento_id], arquivos_removidos=removidos)


@router.post("/excluir-lote", response_model=ResultadoExclusaoDocumentos)
def excluir_documentos_lote(
    payload: DocumentosExcluirLote,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_papel("admin")),
):
    """Exclui as notas marcadas na tela; ids fora do escritório não são aceitos."""
    documentos = (
        db.query(DocumentoFiscal)
        .join(Empresa)
        .filter(DocumentoFiscal.id.in_(payload.ids), Empresa.escritorio_id == escritorio_id)
        .all()
    )
    encontrados = {doc.id for doc in documentos}
    faltando = [item for item in payload.ids if item not in encontrados]
    if faltando:
        raise HTTPException(status_code=404, detail=f"{plural(len(faltando), 'Documento', 'Documentos')} não {plural(len(faltando), 'encontrado', 'encontrados')}: {faltando}")

    arquivos = _arquivos_exclusivos(db, documentos)
    tipos = ", ".join(sorted({doc.tipo.value for doc in documentos}))
    auditoria.registrar(
        db,
        usuario,
        "documentos_excluir_lote",
        detalhe=f"{contagem(len(documentos), 'documento', 'documentos')} · tipos: {tipos or 'n/a'}",
    )
    for documento in documentos:
        db.delete(documento)
    db.commit()
    removidos = _remover_arquivos(arquivos)
    return ResultadoExclusaoDocumentos(excluidos=len(documentos), ids=payload.ids, arquivos_removidos=removidos)


@router.get("/lote/{documento_id}/recibo")
def recibo_documento(
    documento_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """De qual execução veio o documento (auditoria: 'quem baixou esta nota, quando')."""
    documento = _documento_do_escritorio(db, documento_id, escritorio_id)
    execucao = (
        db.query(ExecucaoImportacao)
        .filter(
            ExecucaoImportacao.empresa_id == documento.empresa_id,
            ExecucaoImportacao.tipo == documento.tipo,
            ExecucaoImportacao.ultimo_nsu.isnot(None),
        )
        .order_by(ExecucaoImportacao.id.desc())
        .first()
    )
    return {
        "documento_id": documento.id,
        "chave_acesso": documento.chave_acesso,
        "nsu": documento.nsu,
        "leiaute": documento.leiaute,
        "execucao_id": execucao.id if execucao else None,
        "importado_em": documento.importado_em,
    }


@router.get("/detalhe/{documento_id}", response_model=DocumentoDetalhe)
def detalhe_documento(
    documento_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Ficha completa de um documento para o painel de detalhes."""
    documento = _documento_do_escritorio(db, documento_id, escritorio_id)
    # Cadastro que diz "completo" com XML de resumo no disco: corrige antes de
    # mostrar a ficha (senão a tela afirma "XML completo" para um resNFe).
    if xml_integridade.reconciliar(db, documento):
        db.commit()
    # Abrir a ficha NÃO consulta a SEFAZ. Antes, abrir um resumo chamava
    # `completar_xml_documento_imediato` aqui dentro: a leitura ficava presa no
    # tempo da SEFAZ (15,2 s medidos com o ambiente fora) e cada abertura
    # gastava uma consulta por chave da cota de 20/h do CNPJ — sem o operador
    # pedir nada. A busca do XML completo continua no botão "Buscar XML
    # completo" (POST /{id}/completar-xml) e no download, que são explícitos.
    empresa = db.get(Empresa, documento.empresa_id)
    xml_disponivel = bool(documento.xml_path and os.path.isfile(documento.xml_path))
    tamanho = None
    if xml_disponivel:
        try:
            tamanho = os.path.getsize(documento.xml_path)
        except OSError:
            tamanho = None
    execucao = (
        db.query(ExecucaoImportacao)
        .filter(
            ExecucaoImportacao.empresa_id == documento.empresa_id,
            ExecucaoImportacao.tipo == documento.tipo,
            ExecucaoImportacao.ultimo_nsu.isnot(None),
        )
        .order_by(ExecucaoImportacao.id.desc())
        .first()
    )
    fontes = (
        db.query(DocumentoFiscalFonte)
        .filter(DocumentoFiscalFonte.documento_id == documento.id)
        .order_by(DocumentoFiscalFonte.registrado_em.asc(), DocumentoFiscalFonte.id.asc())
        .all()
    )
    return DocumentoDetalhe(
        **DocumentoFiscalResposta.model_validate(documento).model_dump(),
        empresa_razao_social=empresa.razao_social if empresa else "",
        empresa_cnpj=empresa.cnpj_cpf if empresa else "",
        empresa_uf=empresa.uf if empresa else "",
        importado_em=documento.importado_em,
        xml_disponivel=xml_disponivel,
        xml_bytes=tamanho,
        execucao_id=execucao.id if execucao else None,
        fontes=[DocumentoFonteResposta.model_validate(fonte) for fonte in fontes],
    )


def _documento_do_escritorio(db: Session, documento_id: int, escritorio_id: int) -> DocumentoFiscal:
    documento = (
        db.query(DocumentoFiscal)
        .join(Empresa)
        .filter(DocumentoFiscal.id == documento_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if documento is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return documento



def _arquivos_exclusivos(db: Session, documentos: list[DocumentoFiscal]) -> list[str]:
    """Arquivos XML que podem ser apagados sem deixar outro documento órfão."""
    ids = {doc.id for doc in documentos}
    caminhos: list[str] = []
    for documento in documentos:
        caminho = (documento.xml_path or "").strip()
        if not caminho or caminho in caminhos:
            continue
        compartilhado = (
            db.query(DocumentoFiscal.id)
            .filter(DocumentoFiscal.xml_path == caminho, DocumentoFiscal.id.notin_(ids))
            .first()
        )
        if not compartilhado:
            caminhos.append(caminho)
    return caminhos


def _remover_arquivos(caminhos: list[str]) -> int:
    removidos = 0
    for caminho in caminhos:
        try:
            if caminho and os.path.isfile(caminho):
                os.unlink(caminho)
                removidos += 1
        except OSError:
            # O banco já registrou a intenção; falha no disco não deve ressuscitar nota.
            continue
    return removidos
