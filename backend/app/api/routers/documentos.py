"""
Consulta e download dos documentos importados.

Dois detalhes que parecem pequenos e são decisivos para quem usa isto todo
dia no escritório:

- **filtro por competência** (`08/2026`): como a distribuição oficial não
  aceita data, o banco guarda a competência de tudo que chegou e o recorte é
  feito aqui. Trocar de mês passa a custar zero requisições à SEFAZ;
- **download em massa** (`/exportar`): um ZIP com os XMLs por empresa + uma
  planilha de relação, que é exatamente o pacote que se manda por e-mail.
"""

import csv
import io
import os
import re
import tempfile
import zipfile
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_escrita, usuario_atual
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    DirecaoDocumento,
    DocumentoFiscal,
    Empresa,
    ExecucaoImportacao,
    StatusDocumentoFiscal,
    TipoDocumentoFiscal,
    Usuario,
)
from app.services import auditoria
from app.schemas import (
    DocumentoDetalhe,
    DocumentoFiscalResposta,
    EmpresaResumoDocumentos,
    EstimativaExportacao,
    ResumoDocumentos,
)
from app.services.periodo import PeriodoInvalido, interpretar_periodo

router = APIRouter(prefix="/documentos", tags=["documentos fiscais"])


def _empresa_do_escritorio(db: Session, empresa_id: int, escritorio_id: int) -> Empresa:
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return empresa


def _competencia_efetiva():
    """
    Expressão de filtragem: a competência declarada no XML e, na falta dela, a
    data de emissão. `date()` tem o mesmo comportamento em PostgreSQL e SQLite,
    então o filtro não muda de resultado conforme o banco.
    """
    return func.coalesce(
        DocumentoFiscal.competencia,
        func.date(DocumentoFiscal.data_emissao),
    )


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
        consulta = consulta.filter(DocumentoFiscal.leiaute == leiaute)
    if apenas_nao_canceladas:
        consulta = consulta.filter(DocumentoFiscal.status != StatusDocumentoFiscal.CANCELADA)

    if busca and busca.strip():
        padrao = f"%{busca.strip()}%"
        condicoes = [
            DocumentoFiscal.chave_acesso.like(padrao),
            DocumentoFiscal.emitente_nome.ilike(padrao),
            DocumentoFiscal.emitente_documento.like(padrao),
        ]
        digitos = re.sub(r"\D", "", busca)
        if digitos:
            # "3401" em busca por número: o contador digita assim o tempo todo.
            condicoes.append(DocumentoFiscal.numero == (digitos.lstrip("0") or "0"))
            condicoes.append(DocumentoFiscal.numero == digitos)
        consulta = consulta.filter(or_(*condicoes))

    if inicio or fim:
        competencia = _competencia_efetiva()
        if inicio:
            consulta = consulta.filter(competencia >= inicio)
        if fim:
            consulta = consulta.filter(competencia <= fim)
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


@router.get("/resumo", response_model=ResumoDocumentos)
def resumo_documentos(
    empresa_id: int | None = None,
    competencia: str | None = None,
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Total de notas, separando canceladas — com o mesmo filtro de competência do
    resto da tela (antes o resumo contava tudo e discordava da lista).
    """
    try:
        periodo = interpretar_periodo(competencia, data_inicio, data_fim)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if empresa_id is not None:
        _empresa_do_escritorio(db, empresa_id, escritorio_id)

    base = db.query(DocumentoFiscal).join(Empresa).filter(Empresa.escritorio_id == escritorio_id)
    if empresa_id is not None:
        base = base.filter(DocumentoFiscal.empresa_id == empresa_id)
    base = _filtrar(base, inicio=periodo.inicio, fim=periodo.fim)

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
    leiaute: str | None = Query(default=None, description="completo | resumo"),
    competencia: str | None = Query(default=None, description="MM/AAAA, ex.: 08/2026"),
    data_inicio: date | None = Query(default=None),
    data_fim: date | None = Query(default=None),
    busca: str | None = Query(default=None, description="chave, número ou emitente"),
    limit: int = Query(default=500, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    try:
        periodo = interpretar_periodo(competencia, data_inicio, data_fim)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ids = _parse_empresas(empresa_ids)
    if empresa_id is not None:
        _empresa_do_escritorio(db, empresa_id, escritorio_id)
        ids = [empresa_id]

    if ids is None:
        ids = [linha[0] for linha in db.query(Empresa.id).filter(Empresa.escritorio_id == escritorio_id).all()]
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
    )
    return consulta.order_by(DocumentoFiscal.data_emissao.desc(), DocumentoFiscal.id.desc()).offset(offset).limit(limit).all()


@router.get("/por-empresa", response_model=list[EmpresaResumoDocumentos])
def resumo_por_empresa(
    competencia: str | None = None,
    tipo: TipoDocumentoFiscal | None = None,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Quantas notas cada empresa tem no período — é o que a tela mostra antes do
    download, para ninguém exportar um pacote vazio nem perder uma empresa.
    """
    try:
        periodo = interpretar_periodo(competencia, None, None)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    empresas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id)
        .order_by(Empresa.razao_social)
        .all()
    )

    agregado = (
        db.query(
            DocumentoFiscal.empresa_id,
            func.count(DocumentoFiscal.id),
            func.sum(case((DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA, 1), else_=0)),
            func.sum(case((DocumentoFiscal.leiaute == "resumo", 1), else_=0)),
            func.coalesce(
                func.sum(
                    case(
                        (DocumentoFiscal.status != StatusDocumentoFiscal.CANCELADA, DocumentoFiscal.valor_total),
                        else_=0.0,
                    )
                ),
                0.0,
            ),
        )
        .group_by(DocumentoFiscal.empresa_id)
        .all()
    )
    por_empresa = {
        empresa_id: (total or 0, canceladas or 0, resumos or 0, float(soma or 0))
        for empresa_id, total, canceladas, resumos, soma in agregado
    }

    # A contagem acima é "tudo"; o recorte por período precisa ser por empresa.
    if periodo.definido:
        por_empresa = {}
        for empresa in empresas:
            contagem = _filtrar(
                db.query(
                    func.count(DocumentoFiscal.id),
                    func.sum(case((DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA, 1), else_=0)),
                    func.sum(case((DocumentoFiscal.leiaute == "resumo", 1), else_=0)),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    DocumentoFiscal.status != StatusDocumentoFiscal.CANCELADA,
                                    DocumentoFiscal.valor_total,
                                ),
                                else_=0.0,
                            )
                        ),
                        0.0,
                    ),
                ).filter(DocumentoFiscal.empresa_id == empresa.id),
                tipo=tipo,
                inicio=periodo.inicio,
                fim=periodo.fim,
            ).one()
            por_empresa[empresa.id] = (
                contagem[0] or 0,
                contagem[1] or 0,
                contagem[2] or 0,
                float(contagem[3] or 0),
            )
    elif tipo is not None:
        por_empresa = {}
        for empresa in empresas:
            contagem = _filtrar(
                db.query(func.count(DocumentoFiscal.id)).filter(
                    DocumentoFiscal.empresa_id == empresa.id
                ),
                tipo=tipo,
            ).scalar()
            por_empresa[empresa.id] = (contagem or 0, 0, 0, 0.0)

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
    empresa_ids: str | None = None,
    tipo: TipoDocumentoFiscal | None = None,
    direcao: DirecaoDocumento | None = None,
    status: StatusDocumentoFiscal | None = None,
    competencia: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    incluir_canceladas: bool = True,
    documento_ids: str | None = Query(default=None, description="seleção da tela: 12,34,56"),
    busca: str | None = Query(default=None, description="mesma busca da tela (chave/número/emitente)"),
    leiaute: str | None = Query(default=None, description="completo | resumo"),
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
    )
    total = consulta.count()
    return EstimativaExportacao(
        documentos=total,
        limite=settings.limite_documentos_por_exportacao,
        empresas=len(ids or []),
        periodo=periodo.rotulo(),
        estimado_bytes=_estimar_bytes(db, ids, total),
    )


@router.get("/exportar")
def exportar_xmls(
    empresa_ids: str | None = None,
    tipo: TipoDocumentoFiscal | None = None,
    direcao: DirecaoDocumento | None = None,
    status: StatusDocumentoFiscal | None = None,
    competencia: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    incluir_canceladas: bool = True,
    documento_ids: str | None = Query(default=None, description="seleção da tela: 12,34,56"),
    busca: str | None = Query(default=None, description="mesma busca da tela (chave/número/emitente)"),
    leiaute: str | None = Query(default=None, description="completo | resumo"),
    incluir_relatorio: bool = Query(default=True, description="CSV com a relação, pronto para o Excel"),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(usuario_atual),
):
    """
    ZIP com **todos** os XMLs do filtro — a resposta para "baixar todos os XMLs
    encontrados", que antes só existia nota a nota.

    Estrutura: `NotasFlow/<empresa>/<tipo>/<tomada-ou-prestada>/<chave>.xml`,
    mais o `relacao.csv` (separador `;` + BOM, abre direto no Excel pt-BR).
    O arquivo é montado em
    streaming no disco temporário e apagado no fim — 25 mil XMLs não cabem na
    memória do container, e um navegador não precisa esperar o ZIP inteiro
    estar pronto para o download começar.
    """
    ids, periodo, apenas_nao_canceladas, selecionados = _params_export(
        db,
        escritorio_id=escritorio_id,
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
    empresa_ids: str | None,
    competencia: str | None,
    data_inicio: date | None,
    data_fim: date | None,
    incluir_canceladas: bool,
    documento_ids: str | None = None,
):
    try:
        periodo = interpretar_periodo(competencia, data_inicio, data_fim)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ids = _parse_empresas(empresa_ids)
    empresas_do_escritorio = [
        linha[0] for linha in db.query(Empresa.id).filter(Empresa.escritorio_id == escritorio_id).all()
    ]
    if ids is None:
        ids = empresas_do_escritorio
    else:
        invalidos = set(ids) - set(empresas_do_escritorio)
        if invalidos:
            raise HTTPException(
                status_code=403,
                detail=f"Empresa(s) fora deste escritório: {sorted(invalidos)}",
            )
    selecionados = _parse_ids(documento_ids, nome="documento_id")
    return ids, periodo, (not incluir_canceladas), selecionados


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


def _montar_zip(consulta, periodo, *, incluir_relatorio: bool) -> str:
    """
    Escreve o ZIP num arquivo temporário e devolve o caminho. O chamador serve
    via FileResponse e apaga no `BackgroundTask`.
    """
    fd, caminho = tempfile.mkstemp(prefix="notasflow-export-", suffix=".zip")
    os.close(fd)

    relatorio = io.StringIO()
    escritor = csv.writer(relatorio, delimiter=";", lineterminator="\r\n")
    escritor.writerow(
        [
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
            "valor_total",
            "situacao",
            "xml_completo",
            "arquivo",
        ]
    )

    usados: set[str] = set()
    with zipfile.ZipFile(caminho, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as pacote:
        for documento, empresa in consulta.yield_per(200):
            nome_arquivo = f"{documento.chave_acesso}.xml"
            # A hierarquia deixa o pacote pronto para o contador separar sem
            # abrir arquivo por arquivo: tipo fiscal e, dentro dele, tomada
            # versus prestada.
            pasta = (
                f"NotasFlow/{_slug(empresa.razao_social)}/{documento.tipo.value}/"
                f"{documento.direcao.value}"
            )
            endereco = f"{pasta}/{nome_arquivo}"
            if endereco in usados:  # chave repetida entre empresas diferentes já tem pasta própria
                endereco = f"{pasta}/{documento.id}_{nome_arquivo}"
            usados.add(endereco)

            conteudo = b""
            if documento.xml_path and os.path.isfile(documento.xml_path):
                try:
                    with open(documento.xml_path, "rb") as arquivo:
                        conteudo = arquivo.read()
                except OSError:
                    conteudo = b""
            if not conteudo:
                # Sem arquivo não dá para inventar XML; o CSV continua listando
                # a nota, com a coluna "xml_completo" marcando o buraco.
                continue

            pacote.writestr(endereco, conteudo)
            escritor.writerow(
                [
                    empresa.razao_social,
                    empresa.cnpj_cpf,
                    documento.tipo.value,
                    documento.direcao.value,
                    documento.competencia.strftime("%m/%Y") if documento.competencia else "",
                    documento.data_emissao.strftime("%d/%m/%Y") if documento.data_emissao else "",
                    documento.numero or "",
                    documento.serie or "",
                    documento.chave_acesso,
                    documento.emitente_documento or "",
                    documento.emitente_nome or "",
                    f"{documento.valor_total:.2f}".replace(".", ","),
                    (
                        "CANCELADA"
                        if documento.status == StatusDocumentoFiscal.CANCELADA
                        else "NORMAL"
                    ),
                    "sim" if documento.leiaute != "resumo" else "so-resumo",
                    endereco,
                ]
            )

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
        "Estrutura: NotasFlow/<empresa>/<tipo>/<tomada-ou-prestada>/<chave>.xml\n"
        "relacao.csv abre direto no Excel (separador ';').\n\n"
        "Notas com 'so-resumo' na coluna xml_completo: a SEFAZ distribui o\n"
        "resumo até que a nota seja manifestada. Use o botão 'completar XML'\n"
        "no painel — a busca pela chave é limitada a 20 consultas/h por CNPJ,\n"
        "então o próprio sistema dosifica.\n"
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
    return DocumentoDetalhe(
        **DocumentoFiscalResposta.model_validate(documento).model_dump(),
        empresa_razao_social=empresa.razao_social if empresa else "",
        empresa_cnpj=empresa.cnpj_cpf if empresa else "",
        empresa_uf=empresa.uf if empresa else "",
        importado_em=documento.importado_em,
        xml_disponivel=xml_disponivel,
        xml_bytes=tamanho,
        execucao_id=execucao.id if execucao else None,
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
