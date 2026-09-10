"""
API de importações: disparar, acompanhar e inspecionar as janelas de consumo.

Três princípios de projeto:

- o `POST` responde 202 e vai embora. Nada de requisição longa esperando SEFAZ:
  o processamento é fila, e o painel acompanha por polling;
- cooldown **nunca** é surpresa: a resposta diz até quando e por quê;
- `forcar=true` existe (é o escape hatch de homologação), mas é registrado na
  execução para o histórico explicar um 656 logo depois.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    Certificado,
    DocumentoFiscal,
    Empresa,
    ExecucaoImportacao,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.schemas import (
    EstadoSincronizacaoResposta,
    ExecucaoImportacaoResposta,
    ImportacaoSelecionadas,
    ImportacaoSolicitar,
    ItemImportacaoLote,
    ItemImportacaoSelecionada,
    ResultadoImportacaoSelecionada,
    ResumoSincronizacao,
)
from app.services import fila, sincronizacao
from app.services.periodo import Periodo, PeriodoInvalido, interpretar_periodo

router = APIRouter(prefix="/importacoes", tags=["importações"])

# Mantido por compatibilidade: a janela agora é calculada pelo estado de
# sincronização (uma linha por empresa+tipo), não por varredura do histórico.
COOLDOWN_SEM_NOVIDADE = sincronizacao.cooldown_oficial()


def _periodo(
    competencia: str | None = None,
    data_inicio=None,
    data_fim=None,
) -> Periodo | None:
    try:
        periodo = interpretar_periodo(competencia, data_inicio, data_fim)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return periodo if periodo.definido else None


@router.post("", response_model=ExecucaoImportacaoResposta, status_code=202)
def solicitar_importacao(
    dados: ImportacaoSolicitar,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Enfileira a importação de UMA empresa e retorna imediatamente — o
    processamento roda no worker. Para as 30 empresas de uma vez, use
    POST /importacoes/lote.

    `competencia` (ex.: "08/2026") **não** filtra o que é baixado: a
    distribuição oficial só anda por NSU, então baixar tudo é o que garante
    que nenhuma nota se perca. O período é registrado na execução (para contar
    o que caiu naquele mês) e pré-selecionado no download dos XMLs.
    """
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == dados.empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    resultado = fila.enfileirar(
        db,
        empresa,
        dados.tipo,
        forcar=dados.forcar,
        periodo=_periodo(dados.competencia, dados.data_inicio, dados.data_fim),
        origem="manual",
    )

    if resultado.status in ("sem_certificado", "sem_uf"):
        raise HTTPException(status_code=409, detail=resultado.mensagem)
    if resultado.status == "em_cooldown":
        raise HTTPException(
            status_code=429,
            detail=(
                resultado.mensagem
                + " (o envio de nova consulta antes disso zera o cronômetro do "
                "bloqueio — por isso o sistema espera; use forcar=true só com consciência)"
            ),
        )

    execucao = db.get(ExecucaoImportacao, resultado.execucao_id)
    resposta = ExecucaoImportacaoResposta.model_validate(execucao)
    resposta.empresa_razao_social = empresa.razao_social
    return resposta


@router.post("/lote", response_model=list[ItemImportacaoLote])
def solicitar_importacao_em_lote(
    tipo: TipoDocumentoFiscal,
    competencia: str | None = Query(default=None, description="MM/AAAA, ex.: 08/2026"),
    forcar: bool = False,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Dispara a importação de TODAS as empresas ativas do escritório de uma vez —
    o equivalente ao 'sincronizar --todas' do Importarnotas original.
    Cada empresa vira uma task independente na fila: uma travar ou falhar
    não afeta as outras. Empresas sem certificado, sem UF ou dentro da janela
    de consumo são reportadas, não enfileiradas.
    """
    periodo = _periodo(competencia)

    empresas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .all()
    )

    resultados: list[ItemImportacaoLote] = []
    for empresa in empresas:
        tem_certificado = (
            db.query(Certificado)
            .filter(Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True))
            .first()
        )
        if tem_certificado is None:
            resultados.append(
                ItemImportacaoLote(
                    empresa_id=empresa.id,
                    razao_social=empresa.razao_social,
                    status="sem_certificado",
                )
            )
            continue

        resultado = fila.enfileirar(
            db, empresa, tipo, forcar=forcar, periodo=periodo, origem="lote"
        )
        status = resultado.status
        if status == "em_andamento":
            status = "ja_em_andamento"
        resultados.append(
            ItemImportacaoLote(
                empresa_id=empresa.id,
                razao_social=empresa.razao_social,
                status=status,
                execucao_id=resultado.execucao_id,
                disponivel_em=resultado.disponivel_em,
                mensagem=resultado.mensagem,
            )
        )

    return resultados


def _naive_para_aware(valor: datetime | None) -> datetime | None:
    """SQLite devolve datetime sem fuso; o resto do código trabalha com UTC."""
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Importar SÓ as empresas marcadas na tela
# ---------------------------------------------------------------------------


def _empresas_selecionadas(
    db: Session, escritorio_id: int, empresa_ids: list[int]
) -> tuple[list[Empresa], list[int]]:
    """
    Separa o que é deste escritório do que não é.

    Ids de outro escritório não viram erro fatal: são simplesmente ignorados,
    como no resto do sistema. Devolver 403 aqui daria a quem tentasse uma
    resposta útil ("esse id existe"), o que não é o comportamento desejado num
    sistema multiempresa.
    """
    empresas = (
        db.query(Empresa)
        .filter(Empresa.id.in_(empresa_ids), Empresa.escritorio_id == escritorio_id)
        .all()
    )
    encontrados = {empresa.id for empresa in empresas}
    fora = [identificador for identificador in empresa_ids if identificador not in encontrados]
    ordem = {identificador: indice for indice, identificador in enumerate(empresa_ids)}
    empresas.sort(key=lambda empresa: ordem.get(empresa.id, 0))
    return empresas, fora


def _tipos_do_pedido(tipos: list[TipoDocumentoFiscal] | None) -> list[TipoDocumentoFiscal]:
    if not tipos:
        return list(TipoDocumentoFiscal)
    vistos: list[TipoDocumentoFiscal] = []
    for tipo in tipos:
        if tipo not in vistos:
            vistos.append(tipo)
    return vistos


def _prever(
    db: Session, empresa: Empresa, tipo: TipoDocumentoFiscal, *, forcar: bool
) -> tuple[str, str, datetime | None]:
    """
    O que aconteceria se enfileirasse agora — **sem enfileirar**.

    Fonte única das quatro respostas possíveis (sem certificado, sem UF, na
    janela da SEFAZ, pode rodar). A prévia e o disparo real usam esta função,
    então a tela nunca promete uma coisa e faz outra.
    """
    status, mensagem = fila.verificar_empresa(db, empresa, tipo)
    if status != "ok":
        return status, mensagem, None
    if fila.em_andamento(db, empresa.id, tipo) is not None:
        return "ja_em_andamento", "Já existe uma varredura em andamento para esta empresa e tipo.", None

    libertacao = sincronizacao.liberacao_para(db, empresa.id, tipo)
    if not libertacao.pode and not forcar:
        return (
            "em_cooldown",
            (
                ("Bloqueado pela SEFAZ (consumo indevido). " if libertacao.bloqueado else "")
                + f"Nova tentativa automática em {libertacao.quando:%d/%m/%Y %H:%M}."
                + (f" ({libertacao.motivo})" if libertacao.motivo else "")
            ),
            libertacao.quando,
        )
    return "ok", "", None


@router.post("/selecionadas/previa", response_model=ResultadoImportacaoSelecionada)
def previa_importacao_selecionadas(
    dados: ImportacaoSelecionadas,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Responde "o que vai acontecer se eu clicar" para as empresas marcadas.

    Serve para o operador ver **antes de disparar** quem está na janela de 1
    hora da SEFAZ e quem está sem certificado — em vez de descobrir depois, no
    meio de uma lista de resultados. Não cria execução, não consulta a SEFAZ,
    não muda nada: é só leitura de estado local.
    """
    empresas, _ = _empresas_selecionadas(db, escritorio_id, dados.empresa_ids)
    tipos = _tipos_do_pedido(dados.tipos)

    itens: list[ItemImportacaoSelecionada] = []
    for empresa in empresas:
        for tipo in tipos:
            status, mensagem, quando = _prever(db, empresa, tipo, forcar=dados.forcar)
            itens.append(
                ItemImportacaoSelecionada(
                    empresa_id=empresa.id,
                    razao_social=empresa.razao_social,
                    tipo=tipo,
                    status=status,
                    disponivel_em=quando,
                    mensagem=mensagem,
                    enfileirada=False,
                )
            )

    enfileiraveis = sum(1 for item in itens if item.status == "ok")
    return ResultadoImportacaoSelecionada(
        total=len(itens),
        enfileiradas=0,
        aguardando=enfileiraveis,
        ignoradas=len(itens) - enfileiraveis,
        itens=itens,
    )


@router.post("/selecionadas", response_model=ResultadoImportacaoSelecionada, status_code=202)
def importar_selecionadas(
    dados: ImportacaoSelecionadas,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Enfileira a importação **apenas das empresas marcadas**.

    É a operação que o uso real pede: "quero as notas destas 3 empresas de
    agosto", não "varra os 30 CNPJs do escritório". Cada CNPJ consultado gasta
    a janela de 1 hora da SEFAZ; varrer quem não foi pedido atrasa quem foi.

    Uma empresa que não pode entrar agora **não impede as outras**: o resultado
    volta item a item, com o motivo de cada uma — mesmo formato da prévia, para
    a tela poder só trocar "vai rodar" por "está rodando".
    """
    periodo = _periodo(dados.competencia, dados.data_inicio, dados.data_fim)
    empresas, _ = _empresas_selecionadas(db, escritorio_id, dados.empresa_ids)
    tipos = _tipos_do_pedido(dados.tipos)

    itens: list[ItemImportacaoSelecionada] = []
    for empresa in empresas:
        for tipo in tipos:
            resultado = fila.enfileirar(
                db,
                empresa,
                tipo,
                forcar=dados.forcar,
                periodo=periodo,
                origem="selecao",
            )
            status = "ja_em_andamento" if resultado.status == "em_andamento" else resultado.status
            itens.append(
                ItemImportacaoSelecionada(
                    empresa_id=empresa.id,
                    razao_social=empresa.razao_social,
                    tipo=tipo,
                    status=status,
                    execucao_id=resultado.execucao_id,
                    disponivel_em=resultado.disponivel_em,
                    mensagem=resultado.mensagem,
                    enfileirada=resultado.enfileirada,
                )
            )

    enfileiradas = sum(1 for item in itens if item.enfileirada)
    aguardando = sum(1 for item in itens if item.status == "em_cooldown")
    return ResultadoImportacaoSelecionada(
        total=len(itens),
        enfileiradas=enfileiradas,
        aguardando=aguardando,
        ignoradas=len(itens) - enfileiradas - aguardando,
        itens=itens,
    )


def estados_do_escritorio(
    db: Session,
    *,
    escritorio_id: int,
    empresa_id: int | None = None,
) -> list[EstadoSincronizacaoResposta]:
    """
    Onde cada empresa+tipo está: cursor, maxNSU do ambiente, janelas de espera.

    É a tela que responde "preciso clicar em alguma coisa?" — se `em_dia` é
    true e nada está bloqueado, não. `pendencia` é o número de NSUs que ainda
    faltam varrer quando a SEFAZ tem mais documento que o nosso cursor.
    """
    filtro = [Empresa.escritorio_id == escritorio_id]
    if empresa_id is not None:
        filtro.append(Empresa.id == empresa_id)
    empresas = db.query(Empresa).filter(*filtro).all()
    agora = datetime.now(timezone.utc)
    saida: list[EstadoSincronizacaoResposta] = []

    for empresa in empresas:
        for tipo in TipoDocumentoFiscal:
            estado = sincronizacao.obter_estado(db, empresa.id, tipo, criar=False)
            em_andamento = (
                db.query(ExecucaoImportacao)
                .filter(
                    ExecucaoImportacao.empresa_id == empresa.id,
                    ExecucaoImportacao.tipo == tipo,
                    ExecucaoImportacao.status == StatusExecucao.EM_ANDAMENTO,
                )
                .first()
            ) is not None

            if estado is None:
                saida.append(
                    EstadoSincronizacaoResposta(
                        empresa_id=empresa.id,
                        razao_social=empresa.razao_social,
                        tipo=tipo.value,
                        ultimo_nsu="0",
                        em_andamento=em_andamento,
                        sincronizar_automaticamente=empresa.sincronizar_automaticamente,
                        cota_pontual_disponivel=settings.limite_consultas_pontuais_por_hora,
                    )
                )
                continue

            bloqueado_ate = estado.bloqueado_ate
            if bloqueado_ate and bloqueado_ate.tzinfo is None:
                bloqueado_ate = bloqueado_ate.replace(tzinfo=timezone.utc)
            proxima = estado.proxima_consulta_em
            if proxima and proxima.tzinfo is None:
                proxima = proxima.replace(tzinfo=timezone.utc)

            ultima_varredura = _naive_para_aware(
                estado.ultima_consulta_em or estado.atualizado_em
            )
            dias_sem_varrer = (
                (agora - ultima_varredura).days if ultima_varredura is not None else None
            )
            em_dia = sincronizacao.esta_em_dia(estado)
            # A distribuição guarda poucos meses para trás. Se o cursor está
            # parado há mais que isso E ainda falta documento, a janela de
            # recuperação está se fechando — é o único caso em que esperar é
            # pior que agir.
            risco = bool(
                dias_sem_varrer is not None
                and dias_sem_varrer >= settings.dias_disponiveis_na_distribuicao
                and not em_dia
            )

            saida.append(
                EstadoSincronizacaoResposta(
                    empresa_id=empresa.id,
                    razao_social=empresa.razao_social,
                    tipo=tipo.value,
                    dias_sem_varrer=dias_sem_varrer,
                    risco_documento_fora_da_distribuicao=risco,
                    ultimo_nsu=estado.ultimo_nsu,
                    max_nsu=estado.max_nsu,
                    pendencia=sincronizacao.pendencia_de_documentos(estado),
                    em_dia=em_dia,
                    bloqueado_ate=bloqueado_ate if bloqueado_ate and bloqueado_ate > agora else None,
                    motivo_bloqueio=estado.motivo_bloqueio,
                    bloqueios_seguidos=estado.bloqueios_seguidos or 0,
                    proxima_consulta_em=proxima if proxima and proxima > agora else None,
                    ultima_consulta_em=estado.ultima_consulta_em,
                    em_andamento=em_andamento,
                    travado=sincronizacao.esta_travado(estado, agora=agora),
                    sincronizar_automaticamente=empresa.sincronizar_automaticamente,
                    cota_pontual_disponivel=sincronizacao.cota_pontual_disponivel(db, estado),
                )
            )
    return saida



@router.get("/estado", response_model=list[EstadoSincronizacaoResposta])
def listar_estado_sincronizacao(
    empresa_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Onde cada empresa+tipo está: cursor, maxNSU do ambiente, janelas de espera.

    É a tela que responde "preciso clicar em alguma coisa?" — se `em_dia` é
    true e nada está bloqueado, não. `pendencia` é o número de NSUs que ainda
    faltam varrer quando a SEFAZ tem mais documento que o nosso cursor.
    """
    return estados_do_escritorio(db, escritorio_id=escritorio_id, empresa_id=empresa_id)


@router.get("/resumo", response_model=ResumoSincronizacao)
def resumo_sincronizacao(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Contadores agregados do painel: quantas empresas em dia / esperando / travadas."""
    estados = estados_do_escritorio(db, escritorio_id=escritorio_id)
    em_dia = sum(1 for e in estados if e.em_dia)
    bloqueadas = {e.empresa_id for e in estados if e.bloqueado_ate}
    aguardando = {e.empresa_id for e in estados if e.proxima_consulta_em and not e.bloqueado_ate}
    andamentos = {e.empresa_id for e in estados if e.em_andamento}
    com_pendencia = {e.empresa_id for e in estados if e.pendencia > 0}
    documentos_no_banco = (
        db.query(func.count(DocumentoFiscal.id))
        .join(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id)
        .scalar()
        or 0
    )
    return ResumoSincronizacao(
        empresas=len({e.empresa_id for e in estados}),
        combinacoes=len(estados),
        em_dia=em_dia,
        com_pendencia=len(com_pendencia),
        em_andamento=len(andamentos),
        aguardando_janela=len(aguardando - bloqueadas),
        bloqueadas_sefaz=len(bloqueadas),
        documentos_no_banco=documentos_no_banco,
        sincronismo_automatico=settings.sincronismo_automatico,
        intervalo_minutos=settings.sincronismo_intervalo_minutos,
        tick_a_partir_de=datetime.now(timezone.utc) + timedelta(
            minutes=settings.sincronismo_intervalo_minutos
        ),
    )


@router.get("", response_model=list[ExecucaoImportacaoResposta])
def listar_execucoes(
    empresa_id: int | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Histórico de execuções — usado pela tela de Importações no painel."""
    consulta = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id)
    )
    if empresa_id is not None:
        consulta = consulta.filter(ExecucaoImportacao.empresa_id == empresa_id)

    execucoes = consulta.order_by(ExecucaoImportacao.id.desc()).limit(limit).all()

    respostas = []
    for execucao in execucoes:
        resposta = ExecucaoImportacaoResposta.model_validate(execucao)
        resposta.empresa_razao_social = execucao.empresa.razao_social
        respostas.append(resposta)
    return respostas


@router.get("/{execucao_id}", response_model=ExecucaoImportacaoResposta)
def consultar_execucao(
    execucao_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    execucao = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(ExecucaoImportacao.id == execucao_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if execucao is None:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    resposta = ExecucaoImportacaoResposta.model_validate(execucao)
    resposta.empresa_razao_social = execucao.empresa.razao_social
    return resposta
