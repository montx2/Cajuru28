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
  planilha de relação, que é exatamente o pacote que se manda por e-mail.

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
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_escrita, requer_papel, usuario_atual
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
from app.services import auditoria
from app.schemas import (
    DocumentoDetalhe,
    DocumentoFonteResposta,
    DocumentoFiscalResposta,
    DocumentosExcluirLote,
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
        raise HTTPException(status_code=403, detail=f"Empresa(s) fora deste escritório: {sorted(invalidos)}")
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
    return EstimativaExportacao(
        documentos=total,
        limite=settings.limite_documentos_por_exportacao,
        empresas=len(ids or []),
        periodo=periodo.rotulo(),
        estimado_bytes=_estimar_bytes(db, ids, total),
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
        detalhe=f"{total} documento(s) · {periodo.rotulo()}" + (f" · tipo {tipo.value}" if tipo else ""),
    )
    db.commit()
    if total == 0:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum documento no filtro escolhido ({periodo.rotulo()}).",
        )

    caminho, _linhas = _montar_csv_arquivo(consulta)
    nome = "NotasFlow_relacao_" + re.sub(r"[^0-9A-Za-z_.-]+", "_", periodo.rotulo()) + ".csv"
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
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(usuario_atual),
):
    """
    ZIP com **todos** os XMLs do filtro — a resposta para "baixar todos os XMLs
    encontrados", que antes só existia nota a nota.

    Estrutura: `NotasFlow/<empresa>/<tipo>/<chave>.xml`, mais o `relacao.csv`
    (separador `;` + BOM, abre direto no Excel pt-BR). O arquivo é montado em
    streaming no disco temporário e apagado no fim — 25 mil XMLs não cabem na
    memória do container, e um navegador não precisa esperar o ZIP inteiro
    estar pronto para o download começar.
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
    auditoria.registrar(
        db, usuario, "exportacao_zip",
        detalhe=f"{total} documento(s) · {periodo.rotulo()}" + (f" · tipo {tipo.value}" if tipo else ""),
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

    caminho = _montar_zip(
        consulta.order_by(Empresa.razao_social, DocumentoFiscal.data_emissao.desc()).yield_per(200),
        periodo,
        incluir_relatorio=incluir_relatorio,
    )

    nome = "NotasFlow_" + re.sub(r"[^0-9A-Za-z_.-]+", "_", periodo.rotulo()) + ".zip"
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


def _linha_relatorio(documento: DocumentoFiscal, empresa: Empresa, arquivo_zip: str) -> list[str]:
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
        "sim" if documento.leiaute == "completo" else ("metadados-sem-xml" if documento.leiaute == "metadados" else "so-resumo"),
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
            escritor.writerow(_linha_relatorio(documento, empresa, ""))
            linhas += 1
    return caminho, linhas


def _montar_zip(consulta, periodo, *, incluir_relatorio: bool) -> str:
    """
    Escreve o ZIP num arquivo temporário e devolve o caminho. O chamador serve
    via FileResponse e apaga no `BackgroundTask`.
    """
    fd, caminho = tempfile.mkstemp(prefix="notasflow-export-", suffix=".zip")
    os.close(fd)

    relatorio = io.StringIO()
    escritor = csv.writer(relatorio, delimiter=";", lineterminator="\r\n")
    escritor.writerow(_cabecalho_relatorio())

    usados: set[str] = set()
    with zipfile.ZipFile(caminho, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as pacote:
        for documento, empresa in consulta.yield_per(200):
            nome_arquivo = f"{documento.chave_acesso}.xml"
            pasta = f"NotasFlow/{_slug(empresa.razao_social)}/{documento.tipo.value}"
            endereco = f"{pasta}/{nome_arquivo}"
            if endereco in usados:  # chave repetida entre empresas diferentes já tem pasta própria
                endereco = f"{pasta}/{documento.id}_{nome_arquivo}"

            conteudo = b""
            if documento.xml_path and os.path.isfile(documento.xml_path):
                try:
                    with open(documento.xml_path, "rb") as arquivo:
                        conteudo = arquivo.read()
                except OSError:
                    conteudo = b""

            if conteudo:
                pacote.writestr(endereco, conteudo)
                usados.add(endereco)
                arquivo_relatorio = endereco
            else:
                # A Morfeu pública entrega NFS-e como metadados, sem contrato
                # de download de XML. Em vez de omitir a nota do pacote (ou
                # fingir que JSON é XML), entregamos sua representação
                # normalizada e deixamos isso explícito no relatório.
                arquivo_relatorio = ""
                if documento.leiaute == "metadados":
                    endereco_metadados = f"{pasta}/metadados/{documento.id}_{documento.chave_acesso}.json"
                    pacote.writestr(
                        endereco_metadados,
                        json.dumps(
                            {
                                "aviso": "A fonte de origem não disponibilizou XML original para esta NFS-e.",
                                "empresa": {"id": empresa.id, "razao_social": empresa.razao_social, "cnpj_cpf": empresa.cnpj_cpf},
                                "documento": {
                                    "id": documento.id,
                                    "tipo": documento.tipo.value,
                                    "chave_acesso": documento.chave_acesso,
                                    "numero": documento.numero,
                                    "serie": documento.serie,
                                    "data_emissao": documento.data_emissao.isoformat() if documento.data_emissao else None,
                                    "competencia": documento.competencia.isoformat() if documento.competencia else None,
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

            escritor.writerow(_linha_relatorio(documento, empresa, arquivo_relatorio))

        if incluir_relatorio:
            # BOM: sem ele o Excel pt-BR abre "empresa;razao" numa coluna só.
            pacote.writestr("NotasFlow/relacao.csv", "\ufeff" + relatorio.getvalue())
            pacote.writestr(
                "NotasFlow/LEIA-ME.txt",
                _leia_me(periodo, len(usados)),
            )
    return caminho

def _leia_me(periodo, quantidade: int) -> str:
    return (
        "NotasFlow — pacote de XMLs fiscais\n"
        "====================================\n"
        f"Período (competência): {periodo.rotulo()}\n"
        f"Documentos no pacote: {quantidade}\n"
        f"Gerado em: {datetime.now(timezone.utc):%d/%m/%Y %H:%M} UTC\n\n"
        "Estrutura: NotasFlow/<empresa>/<tipo>/<chave>.xml\n"
        "relacao.csv abre direto no Excel (separador ';').\n\n"
        "Notas com 'so-resumo' na coluna xml_completo: a SEFAZ distribui o\n"
        "resumo até que a nota seja manifestada. Use o botão 'completar XML'\n"
        "no painel — a busca pela chave é limitada a 20 consultas/h por CNPJ.\n\n"
        "Notas com 'metadados-sem-xml' chegaram de uma fonte que não forneceu o\n"
        "XML original. O pacote contém um JSON normalizado em /metadados,\n"
        "sem inventar um XML fiscal inexistente.\n"
    )


def _apagar(caminho: str) -> None:
    try:
        os.unlink(caminho)
    except OSError:
        pass


@router.get("/{documento_id}/xml")
def baixar_xml(
    documento_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Download do XML original importado — o que o contador realmente precisa."""
    documento = _documento_do_escritorio(db, documento_id, escritorio_id)

    if not documento.xml_path or not os.path.isfile(documento.xml_path):
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


@router.post("/completar-xmls")
def completar_xmls(
    empresa_id: int | None = None,
    limite: int = Query(default=20, le=20, ge=1),
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
        detalhe=f"limite {limite}/h",
    )
    db.commit()
    completar_xmls_pendentes.delay(empresa_id=empresa_id, limite=limite)
    return {
        "disparado": True,
        "aviso": (
            "O limite oficial é de 20 consultas por chave por hora por CNPJ; o resto "
            "fica para a próxima rodada automática."
        ),
    }


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
        raise HTTPException(status_code=404, detail=f"Documento(s) não encontrado(s): {faltando}")

    arquivos = _arquivos_exclusivos(db, documentos)
    tipos = ", ".join(sorted({doc.tipo.value for doc in documentos}))
    auditoria.registrar(
        db,
        usuario,
        "documentos_excluir_lote",
        detalhe=f"{len(documentos)} documento(s) · tipos: {tipos or 'n/a'}",
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
