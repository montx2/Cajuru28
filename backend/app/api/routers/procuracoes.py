"""
API de operação do módulo Procurações RFB (consumida pela interface web).

Fronteiras desta camada, sem exceção:

- **Nada de regra de negócio aqui.** O router valida entrada, chama o
  serviço, traduz erro de domínio em HTTP e audita. Toda a lógica está em
  `app.procuracoes.servicos`.
- **Tenant nunca vem do cliente.** `escritorio_id_atual` deriva do JWT.
- **Mutação exige papel.** Leitura para todos os autenticados; ação operacional
  exige escrita; configuração e credencial exigem `admin`.
- **Resposta nunca carrega segredo.** Credencial de integração sai como
  "configurado: true", jamais com o valor.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_escrita, requer_papel, usuario_atual
from app.core.vault import cifrar_segredo
from app.db.session import get_db
from app.models import Empresa, Usuario
from app.procuracoes import esquemas as esq
from app.procuracoes import portal
from app.procuracoes.estados import (
    ESTADOS_TERMINAIS,
    FUNDAMENTO_IN_2320,
    CodigoErro,
    ModoOperacao,
    StatusAutorizacao,
    StatusJob,
    avaliar_modo,
)
from app.procuracoes.integracoes.base import FonteError
from app.procuracoes.integracoes.planilha import FonteColagem, criar_fonte_texto
from app.procuracoes.integracoes.registro import (
    FONTES_REMOTAS,
    ROTULOS,
    construir,
    credencial as obter_credencial,
)
from app.procuracoes.modelos import (
    Agente,
    CredencialIntegracao,
    JobEvento,
    JobEvidencia,
    JobProcuracao,
    ModeloAutorizacao,
    ModeloAutorizacaoServico,
    NotificacaoProcuracao,
)
from app.procuracoes.servicos import agentes as srv_agentes
from app.procuracoes.servicos import assinador as srv_assinador
from app.procuracoes.servicos import configuracao as srv_config
from app.procuracoes.servicos import eventos as srv_eventos
from app.procuracoes.servicos import evidencias as srv_evidencias
from app.procuracoes.servicos import fila as srv_fila
from app.procuracoes.servicos import painel as srv_painel
from app.procuracoes.servicos import sincronizacao as srv_sinc
from app.services import auditoria

log = logging.getLogger("cajuru.procuracoes.api")

router = APIRouter(prefix="/procuracoes", tags=["procurações RFB"])

_ESCRITA = Depends(requer_escrita)
_ADMIN = Depends(requer_papel("admin"))


def _erro_fila(exc: srv_fila.FilaError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"codigo": exc.codigo.value, "mensagem": str(exc)},
    )


def _erro_fonte(exc: FonteError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"codigo": exc.codigo, "mensagem": str(exc)}
    )


def _job(db: Session, escritorio_id: int, job_id: int) -> JobProcuracao:
    job = (
        db.query(JobProcuracao)
        .filter(JobProcuracao.id == job_id, JobProcuracao.escritorio_id == escritorio_id)
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    return job


# ---------------------------------------------------------------------------
# Painel
# ---------------------------------------------------------------------------


@router.get("/resumo", response_model=esq.ResumoSaida)
def resumo(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    return esq.ResumoSaida.model_validate(srv_painel.resumo(db, escritorio_id))


@router.get("", response_model=esq.ListaSaida)
def listar(
    situacao: str = Query("", max_length=40),
    busca: str = Query("", max_length=120),
    com_job: str = Query("", pattern="^(sim|nao)?$"),
    pagina: int = Query(1, ge=1, le=10000),
    tamanho: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    linhas, total = srv_painel.listar(
        db,
        escritorio_id,
        situacao=situacao,
        busca=busca,
        com_job=com_job,
        pagina=pagina,
        tamanho=tamanho,
    )
    return esq.ListaSaida(
        itens=[esq.LinhaSaida.model_validate(linha) for linha in linhas],
        total=total,
        pagina=pagina,
        tamanho=tamanho,
    )


@router.get("/situacoes", response_model=list[esq.SituacaoOpcao])
def situacoes():
    return esq.situacoes_disponiveis()


@router.get("/roteiro")
def roteiro(fase: str = Query("", pattern="^(outorga|aceite)?$")):
    """O roteiro assistido oficial. A tela e o Agent leem a mesma fonte."""
    return {
        "passos": portal.roteiro_serializado(fase or None),
        "fundamento": FUNDAMENTO_IN_2320,
        "urls_oficiais": {
            "portal_servicos": portal.PORTAL_SERVICOS,
            "ecac": portal.ECAC,
        },
    }


@router.get("/empresas/{empresa_id}", response_model=esq.DetalheSaida)
def detalhar(
    empresa_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    detalhe = srv_painel.detalhar(db, escritorio_id, empresa_id)
    if detalhe is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")
    return esq.DetalheSaida(
        empresa=esq.LinhaSaida.model_validate(detalhe.linha),
        permissoes=[esq.PermissaoSaida.model_validate(item) for item in detalhe.permissoes],
        jobs=[esq.JobResumoSaida.model_validate(item) for item in detalhe.jobs],
        eventos=srv_eventos.para_saida(db, detalhe.eventos),
        certificados=[esq.CertificadoSaida.model_validate(item) for item in detalhe.certificados],
    )


# ---------------------------------------------------------------------------
# Fila
# ---------------------------------------------------------------------------


@router.post("/jobs", response_model=esq.JobResumoSaida, status_code=201)
def criar_job(
    entrada: esq.CriarJobEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == entrada.empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada.")

    try:
        resultado = srv_fila.criar_job(
            db,
            escritorio_id,
            empresa,
            usuario=usuario,
            origem="manual",
            forcar_nova_outorga=entrada.forcar,
            prioridade=entrada.prioridade,
            modelo_id=entrada.modelo_id,
        )
    except srv_fila.FilaError as exc:
        raise _erro_fila(exc)

    if not resultado.criado or resultado.job is None:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": resultado.codigo.value if resultado.codigo else "NAO_CRIADO",
                "mensagem": resultado.motivo,
                "job_id": resultado.job.id if resultado.job else None,
            },
        )

    auditoria.registrar(
        db,
        usuario,
        "procuracao.job.criado",
        entidade="procuracao_job",
        entidade_id=resultado.job.id,
        detalhe=f"Empresa {empresa.cnpj_cpf}",
        escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(resultado.job)
    return esq.JobResumoSaida.model_validate(resultado.job)


@router.post("/processar-pendencias", response_model=esq.ProcessarPendenciasSaida)
def processar_pendencias(
    entrada: esq.ProcessarPendenciasEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    """O botão "Processar pendências" — enfileira tudo que falta, de uma vez."""
    try:
        relatorio = srv_fila.enfileirar_pendencias(
            db,
            escritorio_id,
            usuario=usuario,
            empresa_ids=entrada.empresa_ids or None,
            origem="manual",
            limite=entrada.limite,
        )
    except srv_fila.FilaError as exc:
        raise _erro_fila(exc)

    motivos: dict[str, int] = {}
    for item in relatorio.get("ignoradas", []):
        chave = item.get("codigo") or "OUTRO"
        motivos[chave] = motivos.get(chave, 0) + 1

    # Logo após montar a fila, explica o que já nasce travado por certificado:
    # ver "na fila" e nada acontecer é a pior experiência possível.
    triagem = srv_fila.triar_por_certificado(db, escritorio_id)
    relatorio["bloqueados_por_certificado"] = triagem["bloqueados"]
    auditoria.registrar(
        db,
        usuario,
        "procuracao.pendencias.processadas",
        entidade="procuracao_job",
        entidade_id=None,
        detalhe=f"{relatorio['criados']} job(s) criado(s) de {relatorio['avaliadas']} avaliada(s)",
        escritorio_id=escritorio_id,
    )
    db.commit()
    return esq.ProcessarPendenciasSaida(
        avaliadas=relatorio["avaliadas"],
        criados=relatorio["criados"],
        ja_na_fila=relatorio["ja_na_fila"],
        ignoradas=relatorio["total_ignoradas"],
        motivos=motivos,
        job_ids=relatorio["job_ids"],
    )


@router.get("/jobs", response_model=list[esq.JobResumoSaida])
def listar_jobs(
    status: str = Query("", max_length=40),
    ativos: bool = Query(False),
    limite: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    consulta = db.query(JobProcuracao).filter(JobProcuracao.escritorio_id == escritorio_id)
    if status:
        consulta = consulta.filter(JobProcuracao.status == status)
    elif ativos:
        consulta = consulta.filter(JobProcuracao.status.in_(srv_fila.ESTADOS_ATIVOS))
    jobs = consulta.order_by(JobProcuracao.prioridade, JobProcuracao.id.desc()).limit(limite).all()
    return [esq.JobResumoSaida.model_validate(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=esq.JobDetalheSaida)
def detalhar_job(
    job_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    job = _job(db, escritorio_id, job_id)
    empresa = db.get(Empresa, job.empresa_id)
    eventos = (
        db.query(JobEvento)
        .filter(JobEvento.job_id == job.id)
        .order_by(JobEvento.quando.desc(), JobEvento.id.desc())
        .limit(200)
        .all()
    )
    evidencias = (
        db.query(JobEvidencia)
        .filter(JobEvidencia.job_id == job.id)
        .order_by(JobEvidencia.id.desc())
        .limit(100)
        .all()
    )
    try:
        servicos = json.loads(job.servicos_json or "[]")
    except ValueError:
        servicos = []

    detalhe = esq.JobDetalheSaida.model_validate(job)
    detalhe.empresa_id = job.empresa_id
    detalhe.empresa_nome = empresa.razao_social if empresa else ""
    detalhe.empresa_documento = empresa.cnpj_cpf if empresa else ""
    detalhe.servicos = servicos if isinstance(servicos, list) else []
    detalhe.eventos = srv_eventos.para_saida(db, eventos)
    detalhe.evidencias = [esq.EvidenciaSaida.model_validate(item) for item in evidencias]
    detalhe.roteiro = portal.roteiro_serializado(job.fase)
    return detalhe


@router.post("/jobs/{job_id}/retomar", response_model=esq.JobResumoSaida)
def retomar_job(
    job_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    job = _job(db, escritorio_id, job_id)
    try:
        srv_fila.retomar(db, job, usuario)
    except srv_fila.FilaError as exc:
        raise _erro_fila(exc)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.job.retomado",
        entidade="procuracao_job",
        entidade_id=job.id,
        detalhe=f"Etapa {job.etapa_atual}", escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(job)
    return esq.JobResumoSaida.model_validate(job)


@router.post("/jobs/{job_id}/cancelar", response_model=esq.JobResumoSaida)
def cancelar_job(
    job_id: int,
    entrada: esq.AcaoJobEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    job = _job(db, escritorio_id, job_id)
    try:
        srv_fila.cancelar(db, job, usuario, entrada.motivo)
    except srv_fila.FilaError as exc:
        raise _erro_fila(exc)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.job.cancelado",
        entidade="procuracao_job",
        entidade_id=job.id,
        detalhe=entrada.motivo or "sem motivo informado", escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(job)
    return esq.JobResumoSaida.model_validate(job)


@router.post("/jobs/{job_id}/reprocessar", response_model=esq.JobResumoSaida, status_code=201)
def reprocessar_job(
    job_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    job = _job(db, escritorio_id, job_id)
    try:
        resultado = srv_fila.reprocessar(db, job, usuario)
    except srv_fila.FilaError as exc:
        raise _erro_fila(exc)
    if not resultado.criado or resultado.job is None:
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": resultado.codigo.value if resultado.codigo else "NAO_CRIADO",
                "mensagem": resultado.motivo,
            },
        )
    auditoria.registrar(
        db,
        usuario,
        "procuracao.job.reprocessado",
        entidade="procuracao_job",
        entidade_id=resultado.job.id,
        detalhe=f"Origem: job #{job.id}", escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(resultado.job)
    return esq.JobResumoSaida.model_validate(resultado.job)


@router.post("/jobs/{job_id}/intervencao", response_model=esq.JobResumoSaida)
def marcar_intervencao(
    job_id: int,
    entrada: esq.AcaoJobEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    """A pessoa assume o processo — esteja ele numa estação ou na fila.

    O código padrão é `INTERVENCAO_SOLICITADA`, com texto honesto: nada de
    desafio do portal aconteceu, foi decisão de quem assumiu. Se o motivo for
    outro (ex.: certificado ambíguo), o chamador informa o código do catálogo.
    """
    job = _job(db, escritorio_id, job_id)
    srv_fila.pedir_intervencao(
        db,
        job,
        entrada.motivo or "Assumido manualmente pelo operador.",
        codigo=entrada.codigo_erro or CodigoErro.INTERVENCAO_SOLICITADA,
        usuario_id=usuario.id,
    )
    auditoria.registrar(
        db,
        usuario,
        "procuracao.job.intervencao",
        entidade="procuracao_job",
        entidade_id=job.id,
        detalhe=entrada.motivo, escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(job)
    return esq.JobResumoSaida.model_validate(job)


@router.post("/jobs/{job_id}/registrar-outorga", response_model=esq.JobResumoSaida)
def registrar_outorga(
    job_id: int,
    entrada: esq.ConfirmacaoManualEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    """Fecha a fase 1 a partir da confirmação que o operador viu na tela.

    Caminho do escritório sem estação: a outorga é feita à mão no portal
    oficial e registrada aqui, com protocolo ou texto de confirmação. Sem
    confirmação a API recusa — nenhum marco é gravado "de boa fé".
    """
    job = _job(db, escritorio_id, job_id)
    if StatusJob(job.status) in ESTADOS_TERMINAIS:
        raise HTTPException(
            status_code=409,
            detail=f"Job já encerrado em '{job.status}'. Use Reprocessar para criar outro.",
        )
    srv_eventos.registrar_evento(
        db,
        job,
        "confirmacao_operador",
        mensagem=entrada.confirmacao_portal or "Confirmação registrada pelo operador.",
        ator=f"operador:{usuario.id}",
        usuario_id=usuario.id,
        detalhe={"protocolo": entrada.protocolo or None},
    )
    srv_fila.registrar_outorga(
        db, job, protocolo=entrada.protocolo, usuario_id=usuario.id
    )
    auditoria.registrar(
        db,
        usuario,
        "procuracao.outorga.registrada",
        entidade="procuracao_job",
        entidade_id=job.id,
        detalhe=f"Protocolo {entrada.protocolo or '(não informado)'}", escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(job)
    return esq.JobResumoSaida.model_validate(job)


@router.post("/jobs/{job_id}/registrar-aceite", response_model=esq.JobResumoSaida)
def registrar_aceite(
    job_id: int,
    entrada: esq.ConfirmacaoManualEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    """Fecha a fase 2 — a autorização passa a ATIVA."""
    job = _job(db, escritorio_id, job_id)
    if StatusJob(job.status) in ESTADOS_TERMINAIS:
        raise HTTPException(
            status_code=409,
            detail=f"Job já encerrado em '{job.status}'. Use Reprocessar para criar outro.",
        )
    srv_eventos.registrar_evento(
        db,
        job,
        "confirmacao_operador",
        mensagem=entrada.confirmacao_portal or "Aceite confirmado pelo operador.",
        ator=f"operador:{usuario.id}",
        usuario_id=usuario.id,
        detalhe={"protocolo": entrada.protocolo or None},
    )
    srv_fila.registrar_aceite(db, job, usuario_id=usuario.id)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.aceite.registrado",
        entidade="procuracao_job",
        entidade_id=job.id,
        detalhe="Autorização ativa", escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(job)
    return esq.JobResumoSaida.model_validate(job)


@router.get("/jobs/{job_id}/evidencias/{evidencia_id}")
def baixar_evidencia(
    job_id: int,
    evidencia_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(usuario_atual),
):
    job = _job(db, escritorio_id, job_id)
    registro = (
        db.query(JobEvidencia)
        .filter(JobEvidencia.id == evidencia_id, JobEvidencia.job_id == job.id)
        .first()
    )
    if registro is None:
        raise HTTPException(status_code=404, detail="Evidência não encontrada.")
    try:
        conteudo = srv_evidencias.ler(registro)
    except srv_evidencias.EvidenciaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    auditoria.registrar(
        db,
        usuario,
        "procuracao.evidencia.lida",
        entidade="procuracao_evidencia",
        entidade_id=registro.id,
        detalhe=f"Job #{job.id}", escritorio_id=escritorio_id,
    )
    db.commit()
    return Response(
        content=conteudo,
        media_type=registro.tipo or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="evidencia-{registro.id}"'},
    )


# ---------------------------------------------------------------------------
# Configuração e modelos
# ---------------------------------------------------------------------------


@router.get("/configuracao", response_model=esq.ConfiguracaoSaida)
def obter_configuracao(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    config = srv_config.obter_configuracao(db, escritorio_id)
    db.commit()
    avaliacao = avaliar_modo(
        srv_config.modo_padrao(config),
        autorizacao_formal_rfb=config.autorizacao_formal_rfb,
    )
    saida = esq.ConfiguracaoSaida.model_validate(config)
    saida.modo_efetivo = avaliacao.modo_efetivo.value
    saida.fundamento_politica = avaliacao.fundamento
    return saida


@router.put("/configuracao", response_model=esq.ConfiguracaoSaida)
def salvar_configuracao(
    entrada: esq.ConfiguracaoEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    config = srv_config.obter_configuracao(db, escritorio_id)
    for campo, valor in entrada.model_dump().items():
        setattr(config, campo, valor)
    config.atualizado_em = datetime.now(timezone.utc)
    db.flush()
    auditoria.registrar(
        db,
        usuario,
        "procuracao.configuracao.salva",
        entidade="procuracao_configuracao",
        entidade_id=config.id,
        detalhe=f"Modo {config.modo_padrao}", escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(config)
    avaliacao = avaliar_modo(
        srv_config.modo_padrao(config),
        autorizacao_formal_rfb=config.autorizacao_formal_rfb,
    )
    saida = esq.ConfiguracaoSaida.model_validate(config)
    saida.modo_efetivo = avaliacao.modo_efetivo.value
    saida.fundamento_politica = avaliacao.fundamento
    return saida


@router.get("/modelos", response_model=list[esq.ModeloSaida])
def listar_modelos(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    srv_config.obter_modelo_padrao(db, escritorio_id)
    db.commit()
    modelos = (
        db.query(ModeloAutorizacao)
        .filter(ModeloAutorizacao.escritorio_id == escritorio_id)
        .order_by(ModeloAutorizacao.padrao.desc(), ModeloAutorizacao.nome)
        .all()
    )
    return [esq.ModeloSaida.model_validate(modelo) for modelo in modelos]


@router.post("/modelos", response_model=esq.ModeloSaida, status_code=201)
def criar_modelo(
    entrada: esq.ModeloEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    modelo = ModeloAutorizacao(
        escritorio_id=escritorio_id,
        nome=entrada.nome,
        descricao=entrada.descricao,
        vigencia_meses=entrada.vigencia_meses,
        escopo_servicos=entrada.escopo_servicos,
        ativo=entrada.ativo,
    )
    db.add(modelo)
    db.flush()
    _gravar_servicos(db, modelo, entrada)
    if entrada.padrao:
        srv_config.definir_modelo_padrao(db, escritorio_id, modelo.id)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.modelo.criado",
        entidade="procuracao_modelo",
        entidade_id=modelo.id,
        detalhe=modelo.nome, escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(modelo)
    return esq.ModeloSaida.model_validate(modelo)


@router.put("/modelos/{modelo_id}", response_model=esq.ModeloSaida)
def atualizar_modelo(
    modelo_id: int,
    entrada: esq.ModeloEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    modelo = (
        db.query(ModeloAutorizacao)
        .filter(
            ModeloAutorizacao.id == modelo_id,
            ModeloAutorizacao.escritorio_id == escritorio_id,
        )
        .first()
    )
    if modelo is None:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")
    modelo.nome = entrada.nome
    modelo.descricao = entrada.descricao
    modelo.vigencia_meses = entrada.vigencia_meses
    modelo.escopo_servicos = entrada.escopo_servicos
    modelo.ativo = entrada.ativo
    modelo.atualizado_em = datetime.now(timezone.utc)
    _gravar_servicos(db, modelo, entrada)
    if entrada.padrao:
        srv_config.definir_modelo_padrao(db, escritorio_id, modelo.id)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.modelo.atualizado",
        entidade="procuracao_modelo",
        entidade_id=modelo.id,
        detalhe=modelo.nome, escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(modelo)
    return esq.ModeloSaida.model_validate(modelo)


@router.delete("/modelos/{modelo_id}", status_code=204)
def remover_modelo(
    modelo_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    modelo = (
        db.query(ModeloAutorizacao)
        .filter(
            ModeloAutorizacao.id == modelo_id,
            ModeloAutorizacao.escritorio_id == escritorio_id,
        )
        .first()
    )
    if modelo is None:
        raise HTTPException(status_code=404, detail="Modelo não encontrado.")
    if modelo.padrao:
        raise HTTPException(
            status_code=409,
            detail="Defina outro modelo como padrão antes de remover este.",
        )
    db.delete(modelo)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.modelo.removido",
        entidade="procuracao_modelo",
        entidade_id=modelo_id,
        detalhe=modelo.nome, escritorio_id=escritorio_id,
    )
    db.commit()
    return Response(status_code=204)


def _gravar_servicos(db: Session, modelo: ModeloAutorizacao, entrada: esq.ModeloEntrada) -> None:
    db.query(ModeloAutorizacaoServico).filter(
        ModeloAutorizacaoServico.modelo_id == modelo.id
    ).delete(synchronize_session=False)
    if entrada.escopo_servicos == "LISTA":
        for ordem, servico in enumerate(entrada.servicos):
            db.add(
                ModeloAutorizacaoServico(
                    modelo_id=modelo.id,
                    codigo=servico.codigo,
                    rotulo=servico.rotulo or servico.codigo,
                    ordem=servico.ordem or ordem,
                )
            )
    db.flush()


# ---------------------------------------------------------------------------
# Integrações
# ---------------------------------------------------------------------------


@router.get("/integracoes", response_model=list[esq.CredencialSaida])
def listar_integracoes(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    saida: list[esq.CredencialSaida] = []
    for fonte in FONTES_REMOTAS:
        registro = obter_credencial(db, escritorio_id, fonte)
        if registro is None:
            saida.append(
                esq.CredencialSaida(fonte=fonte, rotulo=ROTULOS.get(fonte, fonte))
            )
            continue
        try:
            opcoes = json.loads(registro.opcoes_json or "{}")
        except ValueError:
            opcoes = {}
        saida.append(
            esq.CredencialSaida(
                fonte=fonte,
                rotulo=ROTULOS.get(fonte, fonte),
                base_url=registro.base_url,
                identificador=registro.identificador,
                configurado=bool(registro.segredo_cifrado),
                ativo=registro.ativo,
                opcoes=opcoes if isinstance(opcoes, dict) else {},
                ultima_utilizacao_em=registro.ultima_utilizacao_em,
                ultimo_erro=registro.ultimo_erro,
                atualizado_em=registro.atualizado_em,
            )
        )
    return saida


@router.put("/integracoes", response_model=esq.CredencialSaida)
def salvar_integracao(
    entrada: esq.CredencialEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    registro = obter_credencial(db, escritorio_id, entrada.fonte)
    if registro is None:
        registro = CredencialIntegracao(escritorio_id=escritorio_id, fonte=entrada.fonte)
        db.add(registro)
    registro.base_url = entrada.base_url
    registro.identificador = entrada.identificador
    registro.segredo_cifrado = cifrar_segredo(entrada.segredo)
    registro.opcoes_json = json.dumps(entrada.opcoes, ensure_ascii=False)
    registro.ativo = entrada.ativo
    registro.ultimo_erro = ""
    registro.atualizado_em = datetime.now(timezone.utc)
    db.flush()
    auditoria.registrar(
        db,
        usuario,
        "procuracao.integracao.configurada",
        entidade="procuracao_integracao",
        entidade_id=registro.id,
        detalhe=entrada.fonte, escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(registro)
    return esq.CredencialSaida(
        fonte=registro.fonte,
        rotulo=ROTULOS.get(registro.fonte, registro.fonte),
        base_url=registro.base_url,
        identificador=registro.identificador,
        configurado=True,
        ativo=registro.ativo,
        opcoes=entrada.opcoes,
        atualizado_em=registro.atualizado_em,
    )


def _fonte_remota_valida(fonte: str) -> None:
    """Só existe credencial para integração remota — e hoje é uma só."""
    if fonte not in FONTES_REMOTAS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{fonte}' não é uma integração remota deste produto. "
                f"Disponíveis: {', '.join(FONTES_REMOTAS)}. "
                "Listas do painel do Jettax entram por 'Importar lista', sem credencial."
            ),
        )


@router.delete("/integracoes/{fonte}", status_code=204)
def remover_integracao(
    fonte: str,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    _fonte_remota_valida(fonte)
    registro = obter_credencial(db, escritorio_id, fonte)
    if registro is None:
        raise HTTPException(status_code=404, detail="Integração não configurada.")
    db.delete(registro)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.integracao.removida",
        entidade="procuracao_integracao",
        entidade_id=registro.id,
        detalhe=fonte, escritorio_id=escritorio_id,
    )
    db.commit()
    return Response(status_code=204)


@router.post("/integracoes/{fonte}/testar", response_model=esq.TesteIntegracaoSaida)
def testar_integracao(
    fonte: str,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    _fonte_remota_valida(fonte)
    try:
        cliente = construir(db, escritorio_id, fonte)
        mensagem = cliente.testar()
    except FonteError as exc:
        registro = obter_credencial(db, escritorio_id, fonte)
        if registro is not None:
            registro.ultimo_erro = str(exc)[:500]
            db.commit()
        raise _erro_fonte(exc)
    registro = obter_credencial(db, escritorio_id, fonte)
    if registro is not None:
        registro.ultimo_erro = ""
        registro.ultima_utilizacao_em = datetime.now(timezone.utc)
    db.commit()
    return esq.TesteIntegracaoSaida(fonte=fonte, ok=True, mensagem=mensagem)


@router.post("/sincronizar", response_model=esq.SincronizacaoSaida)
def sincronizar(
    entrada: esq.SincronizarEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    """Botão "Sincronizar" — leitura da fonte externa e reconciliação."""
    documentos: list[str] | None = None
    if entrada.empresa_ids:
        documentos = [
            empresa.cnpj_cpf
            for empresa in db.query(Empresa)
            .filter(
                Empresa.escritorio_id == escritorio_id,
                Empresa.id.in_(entrada.empresa_ids),
            )
            .all()
        ]
    elif entrada.fonte == "integra_contador":
        documentos = [
            empresa.cnpj_cpf
            for empresa in db.query(Empresa)
            .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
            .all()
        ]

    try:
        cliente = construir(db, escritorio_id, entrada.fonte)
        resultado = srv_sinc.sincronizar(
            db, escritorio_id, entrada.fonte, cliente, origem="manual", documentos=documentos
        )
    except FonteError as exc:
        db.commit()  # preserva o IntegracaoJob com status "falhou"
        raise _erro_fonte(exc)

    registro = obter_credencial(db, escritorio_id, entrada.fonte)
    if registro is not None:
        registro.ultima_utilizacao_em = datetime.now(timezone.utc)
        registro.ultimo_erro = ""
    auditoria.registrar(
        db,
        usuario,
        "procuracao.sincronizacao",
        entidade="procuracao_integracao",
        entidade_id=None,
        detalhe=f"{entrada.fonte}: {resultado.resumo}", escritorio_id=escritorio_id,
    )
    db.commit()
    return esq.SincronizacaoSaida(
        fonte=resultado.fonte,
        recebidos=resultado.recebidos,
        criados=resultado.criados,
        atualizados=resultado.atualizados,
        inalterados=resultado.inalterados,
        ignorados=resultado.ignorados,
        invalidos=resultado.invalidos,
        mensagem=resultado.mensagem,
        erros=resultado.erros[:100],
    )


def _situacao_declarada(valor: str) -> StatusAutorizacao | None:
    """Converte a aba declarada pelo operador em situação do domínio."""
    texto = (valor or "").strip()
    if not texto:
        return None
    if texto == "sem_procuracao":
        # Aba "Sem procuração" do painel: a própria aba declara que o cliente
        # não autorizou — não é situação indeterminada.
        return StatusAutorizacao.SEM_AUTORIZACAO
    try:
        return StatusAutorizacao(texto)
    except ValueError:
        return None


def _resposta_importacao(
    resultado: srv_sinc.ResultadoSincronizacao, aviso: str = ""
) -> esq.SincronizacaoSaida:
    mensagem = resultado.mensagem
    if aviso:
        mensagem = f"{mensagem} ({aviso})"
    return esq.SincronizacaoSaida(
        fonte=resultado.fonte,
        recebidos=resultado.recebidos,
        criados=resultado.criados,
        atualizados=resultado.atualizados,
        inalterados=resultado.inalterados,
        ignorados=resultado.ignorados,
        invalidos=resultado.invalidos,
        mensagem=mensagem,
        erros=resultado.erros[:100],
    )


@router.post("/importar-planilha", response_model=esq.SincronizacaoSaida)
async def importar_planilha(
    arquivo: UploadFile = File(...),
    fonte_declarada: str = Form("planilha"),
    situacao_padrao: str = Form(""),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    """Caminho que funciona sem nenhuma credencial externa: arquivo exportado.

    `fonte_declarada` existe porque o **mesmo arquivo** vale coisas diferentes
    na reconciliação: exportado do painel do Jettax ele é dado do Jettax
    (precedência `jettax360`); montado à mão é planilha. Quem sabe a origem é
    o operador, então ele declara — nada aqui é adivinhado pela extensão.
    """
    nome_fonte = (fonte_declarada or "").strip()
    if nome_fonte not in esq.FONTES_MANUAIS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Fonte declarada '{nome_fonte}' inválida. Use uma de: "
                f"{', '.join(esq.FONTES_MANUAIS)} — quem sabe a origem do "
                "arquivo é o operador."
            ),
        )
    situacao = _situacao_declarada(situacao_padrao)
    if (situacao_padrao or "").strip() and situacao is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Situação declarada '{situacao_padrao}' inválida. Use: "
                "ativa, expirada ou sem_procuracao (aba 'Sem procuração')."
            ),
        )
    conteudo = await arquivo.read()
    try:
        fonte = criar_fonte_texto(
            conteudo,
            nome_arquivo=arquivo.filename or "planilha.csv",
            origem=ROTULOS.get(nome_fonte, nome_fonte),
            situacao_padrao=situacao,
        )
        resultado = srv_sinc.sincronizar(
            db, escritorio_id, nome_fonte, fonte, origem="upload"
        )
    except FonteError as exc:
        db.commit()
        raise _erro_fonte(exc)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.importacao.planilha",
        entidade="procuracao_integracao",
        entidade_id=None,
        detalhe=f"{nome_fonte}: {resultado.resumo}", escritorio_id=escritorio_id,
    )
    db.commit()
    aviso = fonte.aviso_de_leitura() if isinstance(fonte, FonteColagem) else ""
    return _resposta_importacao(resultado, aviso)


@router.post("/importar-lista", response_model=esq.SincronizacaoSaida)
def importar_lista(
    entrada: esq.ImportarListaEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    """Importa a lista **copiada da tela** do fornecedor.

    Existe porque o painel do Jettax 360 não publica API de procurações: a
    lista sai da tela, paginada (`?page=`) e dividida em abas (`&tab=`). Colar
    página por página é seguro — a chave é o CNPJ/CPF normalizado, então
    repetir a mesma página não duplica nada.
    """
    try:
        fonte = FonteColagem(
            entrada.texto,
            origem=ROTULOS.get(entrada.fonte, entrada.fonte),
            situacao_padrao=_situacao_declarada(entrada.situacao_padrao),
        )
        resultado = srv_sinc.sincronizar(
            db, escritorio_id, entrada.fonte, fonte, origem="colagem"
        )
    except FonteError as exc:
        db.commit()
        raise _erro_fonte(exc)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.importacao.lista",
        entidade="procuracao_integracao",
        entidade_id=None,
        detalhe=f"{entrada.fonte}: {resultado.resumo}", escritorio_id=escritorio_id,
    )
    db.commit()
    return _resposta_importacao(resultado, fonte.aviso_de_leitura())


# ---------------------------------------------------------------------------
# Agents (administração)
# ---------------------------------------------------------------------------


@router.get("/agentes", response_model=list[esq.AgenteSaida])
def listar_agentes(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    config = srv_config.obter_configuracao(db, escritorio_id)
    db.commit()
    from sqlalchemy import func

    from app.procuracoes.modelos import CertificadoInventario

    contagem = dict(
        db.query(CertificadoInventario.agente_id, func.count(CertificadoInventario.id))
        .filter(CertificadoInventario.escritorio_id == escritorio_id)
        .group_by(CertificadoInventario.agente_id)
        .all()
    )
    saida = []
    for agente in (
        db.query(Agente)
        .filter(Agente.escritorio_id == escritorio_id)
        .order_by(Agente.nome)
        .all()
    ):
        item = esq.AgenteSaida.model_validate(agente)
        item.situacao = srv_agentes.situacao(agente, config.heartbeat_tolerancia_segundos)
        item.certificados = int(contagem.get(agente.id, 0))
        saida.append(item)
    return saida


@router.post("/agentes", response_model=esq.AgenteCredencialSaida, status_code=201)
def matricular_agente(
    entrada: esq.AgenteEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    """Gera a credencial da estação. O segredo aparece uma única vez."""
    try:
        credencial = srv_agentes.registrar_agente(
            db, escritorio_id, nome=entrada.nome, identificador=entrada.identificador
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    auditoria.registrar(
        db,
        usuario,
        "procuracao.agente.matriculado",
        entidade="procuracao_agente",
        entidade_id=credencial.agente.id,
        detalhe=entrada.nome, escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(credencial.agente)
    saida = esq.AgenteSaida.model_validate(credencial.agente)
    saida.situacao = "offline"
    return esq.AgenteCredencialSaida(agente=saida, segredo=credencial.segredo)


@router.post("/agentes/{agente_id}/revogar", response_model=esq.AgenteSaida)
def revogar_agente(
    agente_id: int,
    entrada: esq.AcaoJobEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    agente = (
        db.query(Agente)
        .filter(Agente.id == agente_id, Agente.escritorio_id == escritorio_id)
        .first()
    )
    if agente is None:
        raise HTTPException(status_code=404, detail="Estação não encontrada.")
    srv_agentes.revogar(db, agente, entrada.motivo)
    auditoria.registrar(
        db,
        usuario,
        "procuracao.agente.revogado",
        entidade="procuracao_agente",
        entidade_id=agente.id,
        detalhe=entrada.motivo, escritorio_id=escritorio_id,
    )
    db.commit()
    db.refresh(agente)
    saida = esq.AgenteSaida.model_validate(agente)
    saida.situacao = "revogado"
    return saida


@router.get("/agentes/requisitos")
def requisitos_agente():
    """Checklist oficial do Assinador — o mesmo texto na tela e na doc."""
    return {
        "assinador": srv_assinador.roteiro_de_instalacao(),
        "url_local": srv_assinador.URL_LOCAL,
        "manual": srv_assinador.URL_MANUAL_OFICIAL,
        "verificacao_oficial": srv_assinador.URL_VERIFICACAO_OFICIAL,
    }


# ---------------------------------------------------------------------------
# Notificações
# ---------------------------------------------------------------------------


@router.get("/notificacoes", response_model=list[esq.NotificacaoSaida])
def listar_notificacoes(
    abertas: bool = Query(True),
    limite: int = Query(100, ge=1, le=300),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    consulta = db.query(NotificacaoProcuracao).filter(
        NotificacaoProcuracao.escritorio_id == escritorio_id
    )
    if abertas:
        consulta = consulta.filter(NotificacaoProcuracao.reconhecida_em.is_(None))
    itens = consulta.order_by(NotificacaoProcuracao.criado_em.desc()).limit(limite).all()
    return [esq.NotificacaoSaida.model_validate(item) for item in itens]


@router.post("/notificacoes/{notificacao_id}/reconhecer", status_code=204)
def reconhecer_notificacao(
    notificacao_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    if not srv_eventos.reconhecer(db, escritorio_id, notificacao_id, usuario):
        raise HTTPException(status_code=404, detail="Notificação não encontrada.")
    db.commit()
    return Response(status_code=204)
