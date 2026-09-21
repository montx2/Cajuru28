"""
API de importações: disparar, acompanhar e inspecionar as janelas de consumo.

Quatro princípios de projeto:

- **período obrigatório**: toda importação declara o intervalo que interessa
  (01/08/2026 a 31/08/2026, ou a competência 08/2026). A distribuição oficial
  continua andando por NSU — não dá para pedir "só agosto" à SEFAZ —, mas o
  que chega fora do intervalo é **descartado** na gravação, e não entulha o
  acervo. Sem período, nada é enfileirado;
- o `POST` responde 202 e vai embora. Nada de requisição longa esperando SEFAZ:
  o processamento é fila, e o painel acompanha por polling;
- cooldown **nunca** é surpresa: a resposta diz até quando e por quê;
- `forcar=true` existe (é o escape hatch de homologação), mas é registrado na
  execução para o histórico explicar um 656 logo depois.
"""

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_escrita
from app.core.config import settings
from app.core.tempo import hoje_operacional
from app.db.session import get_db
from app.models import (
    Certificado,
    DocumentoFiscal,
    Empresa,
    ExecucaoImportacao,
    StatusDocumentoFiscal,
    StatusExecucao,
    TipoDocumentoFiscal,
    Usuario,
)
from app.services import auditoria
from app.schemas import (
    ConferenciaCompetenciaResposta,
    EstadoSincronizacaoResposta,
    ExecucaoImportacaoResposta,
    ImportacaoSelecionadas,
    ImportacaoSolicitar,
    ItemConferenciaCompetencia,
    ItemImportacaoLote,
    ItemImportacaoSelecionada,
    ResultadoImportacaoSelecionada,
    ResumoSincronizacao,
)
from app.services import fila, sincronizacao
from app.services.periodo import (
    Periodo,
    PeriodoInvalido,
    interpretar_periodo,
    interpretar_periodo_obrigatorio,
)
from app.services.referencia import data_referencia_sql

router = APIRouter(prefix="/importacoes", tags=["importações"])

# Mantido por compatibilidade: a janela agora é calculada pelo estado de
# sincronização (uma linha por empresa+tipo), não por varredura do histórico.
COOLDOWN_SEM_NOVIDADE = sincronizacao.cooldown_oficial()


def _periodo(
    competencia: str | None = None,
    data_inicio=None,
    data_fim=None,
) -> Periodo | None:
    """Período opcional (consulta/leitura). Devolve None quando não veio."""
    try:
        periodo = interpretar_periodo(competencia, data_inicio, data_fim)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return periodo if periodo.definido else None


def _periodo_da_importacao(
    competencia: str | None = None,
    data_inicio=None,
    data_fim=None,
) -> Periodo:
    """
    Período **obrigatório** de uma importação.

    É o filtro que decide o que será gravado: tudo que a distribuição entregar
    fora deste intervalo é descartado pelo worker. Por isso ele não pode ser
    deduzido nem assumido — sem intervalo explícito, a importação é recusada
    com 422 e a tela explica o que digitar.
    """
    try:
        return interpretar_periodo_obrigatorio(
            competencia, data_inicio, data_fim, onde="da importação"
        )
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=ExecucaoImportacaoResposta, status_code=202)
def solicitar_importacao(
    dados: ImportacaoSolicitar,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """
    Enfileira a importação de UMA empresa e retorna imediatamente — o
    processamento roda no worker. Para as 30 empresas de uma vez, use
    POST /importacoes/lote.

    O período é **obrigatório**: `data_inicio`/`data_fim` (01/08/2026 a
    31/08/2026) ou `competencia` (08/2026). A varredura na origem continua
    sendo por NSU — a SEFAZ/ADN não aceita filtro de data —, mas só as notas
    emitidas dentro do intervalo são gravadas; o resto é descartado e contado
    no aviso da execução.
    """
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == dados.empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    periodo = _periodo_da_importacao(
        dados.competencia, dados.data_inicio, dados.data_fim
    )
    resultado = fila.enfileirar(
        db,
        empresa,
        dados.tipo,
        forcar=dados.forcar,
        periodo=periodo,
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
    auditoria.registrar(
        db, usuario, "importacao_disparada",
        entidade="execucao", entidade_id=resultado.execucao_id,
        detalhe=f"{empresa.razao_social} · {dados.tipo.value}" + (" (forçada)" if dados.forcar else ""),
    )
    db.commit()
    resposta = ExecucaoImportacaoResposta.model_validate(execucao)
    resposta.empresa_razao_social = empresa.razao_social
    return resposta


@router.post("/lote", response_model=list[ItemImportacaoLote])
def solicitar_importacao_em_lote(
    tipo: TipoDocumentoFiscal,
    competencia: str | None = Query(
        default=None,
        description="Mês inteiro: MM/AAAA, ex.: 08/2026. Obrigatório quando "
        "data_inicio/data_fim não forem informadas.",
    ),
    data_inicio: str | None = Query(
        default=None, description="Data inicial — 01/08/2026 ou 2026-08-01"
    ),
    data_fim: str | None = Query(
        default=None, description="Data final — 31/08/2026 ou 2026-08-31"
    ),
    forcar: bool = False,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """
    Dispara a importação de TODAS as empresas ativas do escritório de uma vez —
    o equivalente ao 'sincronizar --todas' do Importarnotas original.
    Cada empresa vira uma task independente na fila: uma travar ou falhar
    não afeta as outras. Empresas sem certificado, sem UF ou dentro da janela
    de consumo são reportadas, não enfileiradas.

    O período é obrigatório e vale para todas as empresas do lote: só entram no
    acervo as notas emitidas dentro dele.
    """
    periodo = _periodo_da_importacao(competencia, data_inicio, data_fim)

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

    enfileiradas = sum(1 for r in resultados if r.execucao_id)
    auditoria.registrar(
        db, usuario, "importacao_lote",
        detalhe=f"{tipo.value}: {enfileiradas}/{len(resultados)} enfileiradas",
    )
    db.commit()
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
    usuario: Usuario = Depends(requer_escrita),
):
    """
    Enfileira a importação **apenas das empresas marcadas**.

    É a operação que o uso real pede: "quero as notas destas 3 empresas de
    agosto", não "varra os 30 CNPJs do escritório". Cada CNPJ consultado gasta
    a janela de 1 hora da SEFAZ; varrer quem não foi pedido atrasa quem foi.

    Uma empresa que não pode entrar agora **não impede as outras**: o resultado
    volta item a item, com o motivo de cada uma — mesmo formato da prévia, para
    a tela poder só trocar "vai rodar" por "está rodando".

    O período é obrigatório: é ele que define quais notas serão guardadas.
    """
    periodo = _periodo_da_importacao(
        dados.competencia, dados.data_inicio, dados.data_fim
    )
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
    auditoria.registrar(
        db, usuario, "importacao_selecao",
        detalhe=f"{len(dados.empresa_ids)} empresa(s): {enfileiradas} enfileiradas, {aguardando} na janela",
    )
    db.commit()
    return ResultadoImportacaoSelecionada(
        total=len(itens),
        enfileiradas=enfileiradas,
        aguardando=aguardando,
        ignoradas=len(itens) - enfileiradas - aguardando,
        itens=itens,
    )


def _tempo_para_liberar(
    bloqueado_ate: datetime | None,
    proxima: datetime | None,
    *,
    agora: datetime,
) -> tuple[datetime | None, int, str]:
    """
    Traduz os dois relógios de espera (bloqueio 656 × janela de 1h) em uma
    resposta pronta para a tela: (quando_libera, segundos_restantes, rótulo).

    A SEFAZ/ADN **não** devolve "faltam X minutos" — o prazo é regra do
    protocolo (1h). Então este valor é o que o próprio sistema agendou; para o
    ADN, quando o servidor manda o header `Retry-After`, esse tempo exato já
    entra em `bloqueado_ate`. Se houver dois relógios ativos, vale o mais tarde:
    consultar antes de qualquer um deles vencer reinicia o bloqueio oficial.
    """
    candidatos = [q for q in (bloqueado_ate, proxima) if q and q > agora]
    if not candidatos:
        return None, 0, "liberado"
    quando = max(candidatos)
    segundos = max(0, int((quando - agora).total_seconds()))
    if segundos <= 0:
        return None, 0, "liberado"
    if segundos < 60:
        rotulo = f"libera em {segundos} s"
    elif segundos < 3600:
        rotulo = f"libera em {segundos // 60} min"
    else:
        horas, resto = divmod(segundos, 3600)
        minutos = resto // 60
        rotulo = f"libera em {horas} h {minutos:02d} min" if minutos else f"libera em {horas} h"
    return quando, segundos, rotulo


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

            liberacao_em, segundos_para_liberar, liberacao_rotulo = _tempo_para_liberar(
                bloqueado_ate, proxima, agora=agora
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
                    nunca_consultado=sincronizacao.nunca_consultado(estado),
                    bloqueado_ate=bloqueado_ate if bloqueado_ate and bloqueado_ate > agora else None,
                    motivo_bloqueio=estado.motivo_bloqueio if bloqueado_ate and bloqueado_ate > agora else None,
                    bloqueios_seguidos=estado.bloqueios_seguidos or 0,
                    proxima_consulta_em=proxima if proxima and proxima > agora else None,
                    ultima_consulta_em=estado.ultima_consulta_em,
                    liberacao_em=liberacao_em,
                    segundos_para_liberar=segundos_para_liberar,
                    liberacao_rotulo=liberacao_rotulo,
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


def _parse_ids_csv(valor: str | None, *, nome: str) -> list[int] | None:
    if not valor or not valor.strip():
        return None
    ids: list[int] = []
    for pedaco in valor.split(","):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        try:
            ids.append(int(pedaco))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{nome} inválido: {pedaco!r}") from exc
    return ids or None


def _parse_tipos_csv(valor: str | None) -> list[TipoDocumentoFiscal]:
    if not valor or not valor.strip():
        return list(TipoDocumentoFiscal)
    tipos: list[TipoDocumentoFiscal] = []
    for pedaco in valor.split(","):
        pedaco = pedaco.strip().lower()
        if not pedaco:
            continue
        try:
            tipo = TipoDocumentoFiscal(pedaco)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Tipo inválido: {pedaco!r}") from exc
        if tipo not in tipos:
            tipos.append(tipo)
    return tipos or list(TipoDocumentoFiscal)


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _fim_da_competencia_utc(fim: date) -> datetime:
    return datetime.combine(fim + timedelta(days=1), time.min, tzinfo=timezone.utc)


def _contagens_por_empresa_tipo(
    db: Session,
    *,
    empresa_ids: list[int],
    tipos: list[TipoDocumentoFiscal],
    inicio: date,
    fim: date,
) -> dict[tuple[int, TipoDocumentoFiscal], tuple[int, int, int]]:
    comp = data_referencia_sql()
    linhas = (
        db.query(
            DocumentoFiscal.empresa_id,
            DocumentoFiscal.tipo,
            func.count(DocumentoFiscal.id),
            func.sum(case((DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA, 1), else_=0)),
            func.sum(case((DocumentoFiscal.leiaute != "completo", 1), else_=0)),
        )
        .filter(
            DocumentoFiscal.empresa_id.in_(empresa_ids or [-1]),
            DocumentoFiscal.tipo.in_(tipos),
            comp >= inicio,
            comp <= fim,
        )
        .group_by(DocumentoFiscal.empresa_id, DocumentoFiscal.tipo)
        .all()
    )
    resultado: dict[tuple[int, TipoDocumentoFiscal], tuple[int, int, int]] = {}
    for empresa_id, tipo, total, canceladas, resumos in linhas:
        tipo_enum = tipo if isinstance(tipo, TipoDocumentoFiscal) else TipoDocumentoFiscal(str(tipo))
        resultado[(empresa_id, tipo_enum)] = (total or 0, canceladas or 0, resumos or 0)
    return resultado


def _ultima_execucao(db: Session, empresa_id: int, tipo: TipoDocumentoFiscal) -> ExecucaoImportacao | None:
    return (
        db.query(ExecucaoImportacao)
        .filter(ExecucaoImportacao.empresa_id == empresa_id, ExecucaoImportacao.tipo == tipo)
        .order_by(ExecucaoImportacao.id.desc())
        .first()
    )


def _status_conferencia(
    db: Session,
    empresa: Empresa,
    tipo: TipoDocumentoFiscal,
    *,
    competencia_fechada: bool,
    precisa_ter_consulta_apos: datetime,
    agora: datetime,
) -> tuple[str, str, str | None, str | None, int, datetime | None, datetime | None, datetime | None]:
    """
    Classifica se uma empresa+tipo pode entrar no fechamento do mês.

    Retorna status, mensagem, ultimo_nsu, max_nsu, pendencia,
    ultima_consulta_em, proxima_consulta_em e bloqueado_ate.
    """
    certificado = (
        db.query(Certificado)
        .filter(Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True))
        .first()
    )
    status_preflight, mensagem_preflight = fila.verificar_empresa(db, empresa, tipo)
    if status_preflight == "sem_certificado":
        return ("sem_certificado", mensagem_preflight, None, None, 0, None, None, None)

    validade = _naive_para_aware(certificado.validade if certificado is not None else None)
    if validade is not None and validade < agora:
        return (
            "certificado_vencido",
            "Certificado A1 vencido — renove antes de confiar no fechamento.",
            None,
            None,
            0,
            None,
            None,
            None,
        )

    if status_preflight == "sem_uf":
        return ("sem_uf", mensagem_preflight, None, None, 0, None, None, None)

    andamento = fila.em_andamento(db, empresa.id, tipo)
    estado = sincronizacao.obter_estado(db, empresa.id, tipo, criar=False)
    ultimo_nsu = estado.ultimo_nsu if estado is not None else None
    max_nsu = estado.max_nsu if estado is not None else None
    pendencia = sincronizacao.pendencia_de_documentos(estado) if estado is not None else 0
    ultima_consulta = _naive_para_aware(
        (estado.ultima_consulta_em or estado.atualizado_em) if estado is not None else None
    )
    proxima = _naive_para_aware(estado.proxima_consulta_em if estado is not None else None)
    bloqueado = _naive_para_aware(estado.bloqueado_ate if estado is not None else None)
    proxima_visivel = proxima if proxima and proxima > agora else None
    bloqueado_visivel = bloqueado if bloqueado and bloqueado > agora else None

    if andamento is not None:
        return (
            "rodando",
            "Existe varredura em andamento. Aguarde terminar para fechar a competência.",
            ultimo_nsu,
            max_nsu,
            pendencia,
            ultima_consulta,
            proxima_visivel,
            bloqueado_visivel,
        )

    ultima = _ultima_execucao(db, empresa.id, tipo)
    erro_ativo = bool(ultima and ultima.status == StatusExecucao.ERRO)

    if estado is None:
        status = "erro" if erro_ativo else "precisa_conferir"
        mensagem = (
            ultima.mensagem_erro
            if erro_ativo and ultima and ultima.mensagem_erro
            else "Ainda não há cursor/maxNSU desta empresa e tipo. Rode uma varredura."
        )
        return (status, mensagem, None, None, 0, None, None, None)

    em_dia = sincronizacao.esta_em_dia(estado)
    risco = bool(
        estado.ultima_consulta_em
        and (agora - _naive_para_aware(estado.ultima_consulta_em)).days
        >= settings.dias_disponiveis_na_distribuicao
        and not em_dia
    )
    if risco:
        return (
            "risco",
            "Cursor atrasado há muitos dias: a janela oficial de distribuição pode estar fechando.",
            ultimo_nsu,
            max_nsu,
            pendencia,
            ultima_consulta,
            proxima_visivel,
            bloqueado_visivel,
        )

    if erro_ativo and not em_dia:
        return (
            "erro",
            (ultima.mensagem_erro or "A última varredura falhou.")[:500] if ultima else "A última varredura falhou.",
            ultimo_nsu,
            max_nsu,
            pendencia,
            ultima_consulta,
            proxima_visivel,
            bloqueado_visivel,
        )

    if pendencia > 0:
        if bloqueado_visivel or proxima_visivel:
            return (
                "aguardando",
                "Há NSUs pendentes, mas o ambiente pediu espera. O sistema retoma sozinho.",
                ultimo_nsu,
                max_nsu,
                pendencia,
                ultima_consulta,
                proxima_visivel,
                bloqueado_visivel,
            )
        return (
            "pendente",
            "A SEFAZ/ADN informou que há NSUs novos. Rode a importação antes de fechar.",
            ultimo_nsu,
            max_nsu,
            pendencia,
            ultima_consulta,
            proxima_visivel,
            bloqueado_visivel,
        )

    if not em_dia:
        return (
            "precisa_conferir",
            "Ainda não existe maxNSU confirmado para provar que a fila oficial acabou.",
            ultimo_nsu,
            max_nsu,
            pendencia,
            ultima_consulta,
            proxima_visivel,
            bloqueado_visivel,
        )

    if competencia_fechada and (
        ultima_consulta is None or ultima_consulta < precisa_ter_consulta_apos
    ):
        return (
            "precisa_conferir",
            "A última consulta foi antes do fechamento do mês. Rode uma varredura final.",
            ultimo_nsu,
            max_nsu,
            pendencia,
            ultima_consulta,
            proxima_visivel,
            bloqueado_visivel,
        )

    if not competencia_fechada:
        return (
            "parcial",
            "Competência ainda aberta: até agora está em dia, mas novas notas ainda podem surgir.",
            ultimo_nsu,
            max_nsu,
            pendencia,
            ultima_consulta,
            proxima_visivel,
            bloqueado_visivel,
        )

    return (
        "ok",
        "Cursor chegou ao maxNSU oficial depois do fechamento do mês.",
        ultimo_nsu,
        max_nsu,
        pendencia,
        ultima_consulta,
        proxima_visivel,
        bloqueado_visivel,
    )


@router.get("/conferencia", response_model=ConferenciaCompetenciaResposta)
def conferir_competencia(
    competencia: str | None = Query(default=None, description="MM/AAAA, ex.: 08/2026"),
    empresa_ids: str | None = Query(default=None, description="1,2,3 — vazio = ativas"),
    tipos: str | None = Query(default=None, description="nfse,nfe,cte — vazio = todos"),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Prova operacional para fechar uma competência sem deixar nota passar.

    A distribuição oficial não oferece uma "contagem esperada por mês" para
    comparar. Então a prova correta é: todo CNPJ/tipo precisa ter sido varrido
    até `ultNSU == maxNSU` e a última consulta precisa ser posterior ao fim da
    competência. Se algo não cumprir isso, a resposta aponta exatamente onde
    rodar de novo ou o que corrigir.
    """
    hoje = hoje_operacional()
    periodo = _periodo(competencia or f"{hoje.month:02d}/{hoje.year:04d}")
    assert periodo is not None and periodo.inicio is not None and periodo.fim is not None
    tipos_lista = _parse_tipos_csv(tipos)
    ids = _parse_ids_csv(empresa_ids, nome="empresa_id")

    consulta_empresas = db.query(Empresa).filter(Empresa.escritorio_id == escritorio_id)
    if ids is None:
        consulta_empresas = consulta_empresas.filter(Empresa.ativa.is_(True))
    else:
        consulta_empresas = consulta_empresas.filter(Empresa.id.in_(ids))
    empresas = consulta_empresas.order_by(Empresa.razao_social).all()

    encontrados = {empresa.id for empresa in empresas}
    if ids is not None:
        fora = [identificador for identificador in ids if identificador not in encontrados]
        if fora:
            raise HTTPException(status_code=403, detail=f"Empresa(s) fora deste escritório: {fora}")

    contagens = _contagens_por_empresa_tipo(
        db,
        empresa_ids=[empresa.id for empresa in empresas],
        tipos=tipos_lista,
        inicio=periodo.inicio,
        fim=periodo.fim,
    )
    agora = _agora_utc()
    competencia_fechada = periodo.fim < hoje
    precisa_apos = _fim_da_competencia_utc(periodo.fim)

    itens: list[ItemConferenciaCompetencia] = []
    for empresa in empresas:
        for tipo in tipos_lista:
            total, canceladas, resumos = contagens.get((empresa.id, tipo), (0, 0, 0))
            (
                status_item,
                mensagem,
                ultimo_nsu,
                max_nsu,
                pendencia,
                ultima_consulta,
                proxima,
                bloqueado,
            ) = _status_conferencia(
                db,
                empresa,
                tipo,
                competencia_fechada=competencia_fechada,
                precisa_ter_consulta_apos=precisa_apos,
                agora=agora,
            )
            itens.append(
                ItemConferenciaCompetencia(
                    empresa_id=empresa.id,
                    razao_social=empresa.razao_social,
                    tipo=tipo,
                    status=status_item,
                    documentos=total,
                    canceladas=canceladas,
                    sem_xml_completo=resumos,
                    ultimo_nsu=ultimo_nsu,
                    max_nsu=max_nsu,
                    pendencia=pendencia,
                    ultima_consulta_em=ultima_consulta,
                    proxima_consulta_em=proxima,
                    bloqueado_ate=bloqueado,
                    mensagem=mensagem,
                )
            )

    criticos_status = {"sem_certificado", "certificado_vencido", "sem_uf", "erro", "risco"}
    itens_criticos = sum(1 for item in itens if item.status in criticos_status)
    itens_ok = sum(1 for item in itens if item.status == "ok")
    itens_parciais = sum(1 for item in itens if item.status == "parcial")
    itens_pendentes = len(itens) - itens_ok - itens_criticos
    pendencias_reais = len(itens) - itens_ok - itens_criticos - itens_parciais

    if not itens:
        status_geral = "critico"
        mensagem = "Nenhuma empresa ativa encontrada para conferir."
    elif itens_criticos:
        status_geral = "critico"
        mensagem = "Há bloqueios de cadastro/erro antes de confiar no fechamento."
    elif pendencias_reais:
        status_geral = "pendente"
        mensagem = "Ainda existe varredura pendente ou mês sem consulta final."
    elif not competencia_fechada:
        status_geral = "parcial"
        mensagem = "Competência em andamento: tudo está em dia até agora, mas o mês ainda não fechou."
    else:
        status_geral = "completa"
        mensagem = "Competência conferida: todos os CNPJs/tipos chegaram ao maxNSU oficial."

    return ConferenciaCompetenciaResposta(
        competencia=periodo.rotulo(),
        inicio=periodo.inicio,
        fim=periodo.fim,
        status=status_geral,
        ok=status_geral == "completa",
        mensagem=mensagem,
        documentos=sum(item.documentos for item in itens),
        canceladas=sum(item.canceladas for item in itens),
        sem_xml_completo=sum(item.sem_xml_completo for item in itens),
        empresas=len(empresas),
        itens_total=len(itens),
        itens_ok=itens_ok,
        itens_pendentes=itens_pendentes,
        itens_criticos=itens_criticos,
        itens=itens,
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
