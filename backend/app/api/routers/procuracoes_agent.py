"""
Protocolo do **Cajuru Agent** — a única porta pela qual uma estação fala com
o servidor.

Modelo de confiança, em uma frase: *o servidor confia no que a estação
comprova, nunca no que ela afirma*.

- Toda requisição (fora a abertura de sessão) é assinada com HMAC-SHA256
  sobre método, caminho, timestamp, nonce e hash do corpo. Segredo não
  trafega; captura de tráfego não permite repetição.
- A sessão é curta e revogável; revogar a estação invalida tudo na hora.
- O servidor **nunca** envia senha, PFX ou chave privada para o Agent, e o
  Agent **nunca** envia material de certificado para o servidor. O que
  circula é metadado: thumbprint, titular, validade, referência local opaca.
- Marcar uma fase como concluída exige confirmação real do portal
  (protocolo ou texto observado). Não existe "cliquei, logo assinei".
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.rate_limit import consumir
from app.db.session import get_db
from app.models import Empresa
from app.procuracoes import esquemas as esq
from app.procuracoes import portal
from app.procuracoes.estados import (
    ESTADO_DA_ETAPA,
    CodigoErro,
    EtapaFluxo,
    FaseJob,
    StatusJob,
    TipoCertificado,
    certificado_exigido,
    fase_do_status,
)
from app.procuracoes.modelos import Agente, JobProcuracao, SessaoNavegador
from app.procuracoes.servicos import agentes as srv_agentes
from app.procuracoes.servicos import assinador as srv_assinador
from app.procuracoes.servicos import certificados as srv_certificados
from app.procuracoes.servicos import configuracao as srv_config
from app.procuracoes.servicos import eventos as srv_eventos
from app.procuracoes.servicos import evidencias as srv_evidencias
from app.procuracoes.servicos import fila as srv_fila

log = logging.getLogger("cajuru.procuracoes.agent")

router = APIRouter(prefix="/procuracoes/agente", tags=["procurações RFB · agent"])

CABECALHO_CHAVE = "X-Cajuru-Chave"
CABECALHO_LEASE = "X-Cajuru-Lease"
LIMITE_CORPO = 12 * 1024 * 1024


def _erro_auth(exc: srv_agentes.AgenteAuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


async def agente_autenticado(
    request: Request, db: Session = Depends(get_db)
) -> Agente:
    """Dependência de autenticação HMAC. Falha fechada, sempre."""
    corpo = await request.body()
    if len(corpo) > LIMITE_CORPO:
        raise HTTPException(status_code=413, detail="Corpo da requisição acima do limite.")

    cabecalhos = request.headers
    bruto = cabecalhos.get(srv_agentes.CABECALHO_AGENTE, "")
    identificador = bruto.split(".", 1)[0] if bruto else ""
    chave = cabecalhos.get(CABECALHO_CHAVE, "")
    if not identificador or not chave:
        raise HTTPException(status_code=401, detail="Credencial de estação ausente.")

    try:
        agente = srv_agentes.autenticar_com_chave(
            db,
            identificador=identificador,
            chave_sessao=chave,
            timestamp=cabecalhos.get(srv_agentes.CABECALHO_TIMESTAMP, ""),
            nonce=cabecalhos.get(srv_agentes.CABECALHO_NONCE, ""),
            assinatura=cabecalhos.get(srv_agentes.CABECALHO_ASSINATURA, ""),
            metodo=request.method,
            caminho=request.url.path,
            corpo=corpo,
            endereco=(request.client.host if request.client else ""),
        )
    except srv_agentes.AgenteAuthError as exc:
        db.commit()  # preserva o nonce consumido, se já foi gravado
        raise _erro_auth(exc)
    db.commit()
    return agente


def _corpo_json(corpo: bytes) -> dict:
    if not corpo:
        return {}
    try:
        dados = json.loads(corpo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Corpo JSON inválido.") from exc
    if not isinstance(dados, dict):
        raise HTTPException(status_code=422, detail="Corpo JSON deve ser um objeto.")
    return dados


def _job_do_agente(db: Session, agente: Agente, job_id: int, lease_token: str) -> JobProcuracao:
    """Só o dono do lease mexe no job. É o lock distribuído em ação."""
    job = (
        db.query(JobProcuracao)
        .filter(
            JobProcuracao.id == job_id,
            JobProcuracao.escritorio_id == agente.escritorio_id,
        )
        .first()
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    if job.agente_id != agente.id or not job.lease_token:
        raise HTTPException(status_code=409, detail="Este job não pertence a esta estação.")
    if job.lease_token != lease_token:
        raise HTTPException(status_code=409, detail="Lease inválido ou já substituído.")
    lease = job.lease_ate
    if lease is not None and (lease if lease.tzinfo else lease.replace(tzinfo=timezone.utc)) < datetime.now(
        timezone.utc
    ):
        raise HTTPException(status_code=409, detail="Lease expirado; reivindique novamente.")
    return job


# ---------------------------------------------------------------------------
# Sessão
# ---------------------------------------------------------------------------


@router.post("/sessao", response_model=esq.SessaoAgentSaida)
def abrir_sessao(
    entrada: esq.SessaoAgentEntrada,
    request: Request,
    db: Session = Depends(get_db),
):
    """Troca o segredo de matrícula por uma chave de sessão curta.

    Único ponto em que o segredo da estação trafega — por isso tem limite de
    tentativas por origem e resposta genérica em qualquer falha.
    """
    consumir(request, escopo="procuracao-agente-sessao", limite=10, janela_segundos=60)
    try:
        identificador = srv_agentes.normalizar_identificador(entrada.identificador)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Credencial de estação inválida.") from exc

    agente = db.query(Agente).filter(Agente.identificador == identificador).first()
    if agente is None:
        raise HTTPException(status_code=401, detail="Credencial de estação inválida.")

    try:
        aberta = srv_agentes.abrir_sessao(
            db,
            agente,
            entrada.segredo,
            endereco=(request.client.host if request.client else ""),
        )
    except srv_agentes.AgenteAuthError as exc:
        db.commit()
        raise _erro_auth(exc)

    agente.hostname = entrada.hostname[:255] or agente.hostname
    agente.usuario_windows = entrada.usuario_windows[:255] or agente.usuario_windows
    agente.sistema_operacional = entrada.sistema_operacional[:120] or agente.sistema_operacional
    agente.versao_agente = entrada.versao_agente[:30] or agente.versao_agente
    config = srv_config.obter_configuracao(db, agente.escritorio_id)
    db.commit()

    log.info(
        "procuracao_agente_sessao_aberta",
        extra={"agente": agente.identificador, "escritorio": agente.escritorio_id},
    )
    return esq.SessaoAgentSaida(
        jti=aberta.jti,
        chave_sessao=aberta.chave,
        expira_em=aberta.expira_em,
        intervalo_heartbeat_segundos=max(30, config.heartbeat_tolerancia_segundos // 2),
        intervalo_busca_segundos=max(5, min(60, config.intervalo_entre_jobs_segundos)),
        versao_minima_assinador=config.assinador_versao_minima,
    )


@router.delete("/sessao", status_code=204)
def encerrar_sessao(
    agente: Agente = Depends(agente_autenticado), db: Session = Depends(get_db)
):
    srv_agentes.encerrar_sessoes(db, agente)
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Saúde e inventário
# ---------------------------------------------------------------------------


@router.post("/heartbeat", response_model=esq.HeartbeatSaida)
async def heartbeat(
    request: Request,
    agente: Agente = Depends(agente_autenticado),
    db: Session = Depends(get_db),
):
    entrada = esq.HeartbeatEntrada.model_validate(_corpo_json(await request.body()))
    config = srv_config.obter_configuracao(db, agente.escritorio_id)
    avaliacao = srv_assinador.avaliar(
        entrada.assinador.model_dump(),
        versao_minima=config.assinador_versao_minima,
        exigido=config.assinador_exigido,
    )
    srv_agentes.registrar_heartbeat(
        db,
        agente,
        versao_agente=entrada.versao_agente,
        versao_navegador=entrada.versao_navegador,
        versao_assinador=avaliacao.versao,
        assinador_ok=avaliacao.apto,
        assinador_detalhe=avaliacao.detalhe,
        assinador_pendencias=avaliacao.pendencias,
    )

    if not avaliacao.apto:
        srv_eventos.notificar(
            db,
            agente.escritorio_id,
            chave=f"assinador:{agente.id}",
            tipo="assinador_indisponivel",
            nivel="erro",
            titulo=f"Assinador SERPRO indisponível na estação {agente.nome}",
            detalhe=avaliacao.detalhe,
        )

    disponiveis = 0
    if avaliacao.apto:
        from sqlalchemy import func

        disponiveis = (
            db.query(func.count(JobProcuracao.id))
            .filter(
                JobProcuracao.escritorio_id == agente.escritorio_id,
                JobProcuracao.status.in_(srv_fila.ESTADOS_REIVINDICAVEIS),
                JobProcuracao.agente_id.is_(None),
            )
            .scalar()
            or 0
        )
    db.commit()
    return esq.HeartbeatSaida(
        assinador_apto=avaliacao.apto,
        assinador_detalhe=avaliacao.detalhe,
        jobs_disponiveis=int(disponiveis),
        intervalo_busca_segundos=max(5, min(60, config.intervalo_entre_jobs_segundos)),
        versao_minima_assinador=config.assinador_versao_minima,
        pausado=not config.processamento_automatico,
    )


@router.post("/inventario", response_model=esq.InventarioSaida)
async def inventario(
    request: Request,
    agente: Agente = Depends(agente_autenticado),
    db: Session = Depends(get_db),
):
    """Recebe o catálogo de certificados visíveis na estação — só metadados."""
    entrada = esq.InventarioEntrada.model_validate(_corpo_json(await request.body()))
    resultado = srv_certificados.sincronizar_inventario(
        db, agente, [item.model_dump() for item in entrada.certificados]
    )
    db.commit()
    return esq.InventarioSaida(
        recebidos=len(entrada.certificados),
        novos=resultado["criados"],
        atualizados=resultado["atualizados"],
        indisponiveis=resultado["indisponiveis"],
        invalidos=resultado["invalidos"],
    )


# ---------------------------------------------------------------------------
# Trabalho
# ---------------------------------------------------------------------------


@router.post("/reivindicar", response_model=esq.ReivindicarSaida)
async def reivindicar(
    request: Request,
    agente: Agente = Depends(agente_autenticado),
    db: Session = Depends(get_db),
):
    """Pede trabalho. Devolve no máximo o que a política permite.

    Dois portões antes de qualquer entrega:

    1. **Assinador** (critério D) — sem diagnóstico aprovado, nada sai daqui e
       o operador recebe a lista do que falta instalar.
    2. **Certificado** (critérios C e G) — depois de ganhar o lock, o job só
       vira ordem de trabalho se existir **exatamente um** A1 vigente daquele
       CNPJ na estação. Vencido, ausente ou ambíguo: o job é marcado com o
       código do erro, volta a ficar visível na tela e **não** é entregue.

    A ordem dos portões importa: o lock é tomado primeiro para que dois Agents
    não avaliem o mesmo cliente em paralelo; a recusa acontece com o job já
    travado, e o próprio serviço libera o lease ao registrar a falha.
    """
    entrada = esq.ReivindicarEntrada.model_validate(_corpo_json(await request.body()))
    config = srv_config.obter_configuracao(db, agente.escritorio_id)

    if config.assinador_exigido and not agente.assinador_ok:
        pendencias = [p for p in (agente.assinador_pendencias or "").split(",") if p]
        db.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "codigo": CodigoErro.ASSINADOR_NAO_INSTALADO.value,
                "mensagem": (
                    "Assinador SERPRO não está apto nesta estação. "
                    "Nenhum job é entregue até o diagnóstico passar."
                ),
                "detalhe": agente.assinador_detalhe or "Diagnóstico ainda não recebido.",
                "pendencias": pendencias or ["diagnostico_ausente"],
                "consertos": srv_assinador.roteiro_de_instalacao(pendencias),
            },
        )

    if not config.processamento_automatico:
        db.commit()
        return esq.ReivindicarSaida(
            ordens=[],
            intervalo_busca_segundos=max(15, min(300, config.intervalo_entre_jobs_segundos)),
        )

    teto = min(
        int(entrada.capacidade),
        max(1, int(config.max_jobs_por_agente) - int(agente.jobs_em_andamento or 0)),
    )
    ordens: list[esq.OrdemDeTrabalho] = []
    # Teto de recusas por chamada: se a estação está sem nenhum certificado
    # útil, não faz sentido varrer a fila inteira a cada poll.
    recusas_restantes = 5

    while len(ordens) < teto and recusas_restantes > 0:
        documentos = srv_certificados.documentos_disponiveis(db, agente)
        if not documentos:
            # Estação sem nenhum A1 vigente: a fila é triada para que os jobs
            # travados mostrem o motivo em vez de esperarem em silêncio.
            srv_fila.triar_por_certificado(db, agente.escritorio_id)
            break
        job = srv_fila.reivindicar(db, agente, config, documentos_disponiveis=documentos)
        if job is None:
            break

        selecao = _certificado_do_job(db, agente, job)
        if not selecao.ok:
            recusas_restantes -= 1
            srv_fila.registrar_falha(
                db,
                job,
                selecao.codigo_erro or CodigoErro.CERTIFICADO_INDISPONIVEL,
                selecao.mensagem,
                detalhe={
                    "estacao": agente.nome,
                    "candidatos": [
                        {
                            "thumbprint": candidato.thumbprint,
                            "titular": candidato.titular_nome,
                            "valido_ate": candidato.valido_ate.isoformat()
                            if candidato.valido_ate
                            else "",
                        }
                        for candidato in selecao.candidatos
                    ],
                },
            )
            srv_eventos.notificar(
                db,
                agente.escritorio_id,
                chave=f"certificado_job:{job.id}",
                tipo="certificado_bloqueado",
                nivel="alerta",
                titulo=f"Certificado impede o job #{job.id}",
                detalhe=selecao.mensagem,
                empresa_id=job.empresa_id,
                job_id=job.id,
            )
            db.commit()
            continue

        ordens.append(_montar_ordem(db, agente, job, config, selecao))

    db.commit()
    return esq.ReivindicarSaida(
        ordens=ordens,
        intervalo_busca_segundos=max(5, min(60, config.intervalo_entre_jobs_segundos)),
    )


def _certificado_do_job(db: Session, agente: Agente, job: JobProcuracao):
    """Resolve o A1 exigido pela fase atual do job, na própria estação."""
    status = StatusJob(job.status)
    tipo = certificado_exigido(status)
    if tipo.value == "contabilidade":
        documento_alvo = job.outorgado_documento
    else:
        empresa = db.get(Empresa, job.empresa_id)
        documento_alvo = empresa.cnpj_cpf if empresa else ""
    # O thumbprint gravado no job pertence à fase de outorga (certificado do
    # cliente). Na fase de aceite a identidade é outra: reutilizá-lo faria a
    # busca procurar o A1 da contabilidade sob o thumbprint do cliente.
    preferido = ""
    if tipo is TipoCertificado.CLIENTE:
        preferido = job.certificado_thumbprint or ""
    return srv_certificados.selecionar_para_documento(
        db,
        agente.escritorio_id,
        documento_alvo,
        agente_id=agente.id,
        tipo=tipo,
        thumbprint_preferido=preferido,
    )


def _montar_ordem(
    db: Session, agente: Agente, job: JobProcuracao, config, selecao
) -> esq.OrdemDeTrabalho:
    """A ordem de trabalho: dados suficientes para agir, zero segredo.

    O certificado viaja como `thumbprint` + referência local opaca. A chave
    privada e a senha nunca saem da estação — o backend sequer as conhece.
    """
    empresa = db.get(Empresa, job.empresa_id)
    status = StatusJob(job.status)
    fase = fase_do_status(status)
    certificado = selecao.certificado

    # O certificado efetivamente escolhido fica gravado no job: é o que
    # permite auditar depois "qual A1 assinou o quê".
    job.certificado_thumbprint = certificado.thumbprint
    job.certificado_inventario_id = certificado.id

    try:
        servicos = json.loads(job.servicos_json or "[]")
    except ValueError:
        servicos = []

    passo = portal.passo(job.etapa_atual)
    return esq.OrdemDeTrabalho(
        job_id=job.id,
        lease_token=job.lease_token,
        lease_ate=job.lease_ate,
        fase=fase.value,
        etapa=job.etapa_atual,
        modo=job.modo,
        status=job.status,
        empresa_documento=empresa.cnpj_cpf if empresa else "",
        empresa_nome=empresa.razao_social if empresa else "",
        outorgado_documento=job.outorgado_documento,
        outorgado_nome=job.outorgado_nome,
        vigencia_ate=job.vigencia_ate,
        escopo_servicos=job.escopo_servicos,
        servicos=servicos if isinstance(servicos, list) else [],
        certificado_thumbprint=certificado.thumbprint,
        certificado_referencia=certificado.referencia_local,
        certificado_documento=certificado.documento,
        certificado_titular=certificado.titular_nome,
        certificado_tipo=certificado.tipo,
        url_portal=(passo.url if passo and passo.url else portal.PORTAL_SERVICOS),
        roteiro=portal.roteiro_serializado(fase),
        timeout_etapa_segundos=config.timeout_etapa_segundos,
        intervalo_heartbeat_segundos=max(30, config.heartbeat_tolerancia_segundos // 2),
    )


@router.post("/jobs/{job_id}/lease", response_model=esq.HeartbeatSaida)
async def renovar_lease(
    job_id: int,
    request: Request,
    agente: Agente = Depends(agente_autenticado),
    db: Session = Depends(get_db),
):
    dados = _corpo_json(await request.body())
    job = _job_do_agente(db, agente, job_id, str(dados.get("lease_token") or ""))
    config = srv_config.obter_configuracao(db, agente.escritorio_id)
    srv_fila.renovar_lease(db, job, agente, config)
    db.commit()
    return esq.HeartbeatSaida(
        assinador_apto=agente.assinador_ok,
        assinador_detalhe=agente.assinador_detalhe,
        intervalo_busca_segundos=max(5, min(60, config.intervalo_entre_jobs_segundos)),
    )


@router.post("/jobs/{job_id}/progresso", response_model=esq.JobResumoSaida)
async def progresso(
    job_id: int,
    request: Request,
    agente: Agente = Depends(agente_autenticado),
    db: Session = Depends(get_db),
):
    """Avanço de etapa.

    O Agent relata **onde está no roteiro**; quem decide o estado do job é o
    domínio, via `ESTADO_DA_ETAPA`. Deixar a estação escolher o status seria
    dar a ela poder de pular fases — exatamente o que a máquina de estados
    existe para impedir. Se a etapa informada implicar uma transição inválida,
    a resposta é 409 e nada muda.
    """
    entrada = esq.ProgressoEntrada.model_validate(_corpo_json(await request.body()))
    job = _job_do_agente(db, agente, job_id, entrada.lease_token)

    try:
        etapa = EtapaFluxo(entrada.etapa)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Etapa '{entrada.etapa}' desconhecida.")

    destino = ESTADO_DA_ETAPA.get(etapa)
    # Marcos que exigem confirmação real do portal não são alcançáveis por
    # "progresso": passam obrigatoriamente por /resultado, com protocolo ou
    # texto de confirmação. Aqui eles só movem a etapa.
    if destino in (StatusJob.ASSINADO, StatusJob.CONCLUIDO):
        destino = None

    if destino is not None and destino.value != job.status:
        try:
            srv_fila.avancar_para(
                db,
                job,
                destino,
                mensagem=entrada.mensagem,
                etapa=etapa,
                ator=f"agente:{agente.id}",
                agente_id=agente.id,
                detalhe=entrada.detalhe,
            )
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc))
    else:
        job.etapa_atual = etapa.value
        srv_eventos.registrar_evento(
            db,
            job,
            "progresso",
            mensagem=entrada.mensagem,
            etapa=etapa.value,
            ator=f"agente:{agente.id}",
            agente_id=agente.id,
            detalhe=entrada.detalhe,
        )
    db.commit()
    db.refresh(job)
    return esq.JobResumoSaida.model_validate(job)


@router.post("/jobs/{job_id}/evidencia", response_model=esq.EvidenciaSaida, status_code=201)
async def enviar_evidencia(
    job_id: int,
    request: Request,
    etapa: str = Query("", max_length=40),
    url_observada: str = Query("", max_length=500),
    agente: Agente = Depends(agente_autenticado),
    db: Session = Depends(get_db),
):
    """Captura de tela ou texto da página. Corpo binário puro, já assinado.

    O corpo é o arquivo em si (sem base64: uma captura de 3 MB viraria 4 MB e
    dobraria o uso de memória do worker). Por isso o lease vai no cabeçalho
    `X-Cajuru-Lease`, e **não** na query string — query string entra em log de
    proxy, cabeçalho não. A assinatura HMAC cobre o corpo binário inteiro.
    """
    lease_token = request.headers.get(CABECALHO_LEASE, "")
    if not 8 <= len(lease_token) <= 64:
        raise HTTPException(status_code=422, detail="Cabeçalho X-Cajuru-Lease ausente.")
    job = _job_do_agente(db, agente, job_id, lease_token)
    conteudo = await request.body()
    try:
        gravada = srv_evidencias.gravar(
            db,
            job,
            conteudo=conteudo,
            tipo_declarado=request.headers.get("content-type", ""),
            etapa=etapa or job.etapa_atual,
            url_observada=url_observada,
        )
    except srv_evidencias.EvidenciaError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    db.commit()
    return esq.EvidenciaSaida.model_validate(gravada.registro)


@router.post("/jobs/{job_id}/portal-alterado", response_model=esq.JobResumoSaida)
async def portal_alterado(
    job_id: int,
    request: Request,
    agente: Agente = Depends(agente_autenticado),
    db: Session = Depends(get_db),
):
    """O Agent não reconheceu a tela. Para tudo e pede manutenção.

    Nenhuma tentativa alternativa, nenhum "clicar no que parecer certo".
    """
    dados = _corpo_json(await request.body())
    job = _job_do_agente(db, agente, job_id, str(dados.get("lease_token") or ""))
    ausentes = dados.get("ancoras_ausentes") or []
    detalhe = {
        "etapa": job.etapa_atual,
        "ancoras_ausentes": [str(item)[:80] for item in ausentes][:20],
        "url": str(dados.get("url") or "")[:500],
    }
    srv_fila.registrar_falha(
        db,
        job,
        CodigoErro.PORTAL_ALTERADO,
        str(dados.get("mensagem") or "")[:1000]
        or "A tela do portal não corresponde ao roteiro conhecido.",
        agente_id=agente.id,
        detalhe=detalhe,
    )
    srv_eventos.notificar(
        db,
        agente.escritorio_id,
        chave=f"portal_alterado:{job.etapa_atual}",
        tipo="portal_alterado",
        nivel="erro",
        titulo="O Portal da RFB mudou — adaptador precisa de manutenção",
        detalhe=json.dumps(detalhe, ensure_ascii=False)[:2000],
        job_id=job.id,
    )
    db.commit()
    db.refresh(job)
    return esq.JobResumoSaida.model_validate(job)


@router.post("/jobs/{job_id}/sessao-navegador", status_code=201)
async def abrir_sessao_navegador(
    job_id: int,
    request: Request,
    agente: Agente = Depends(agente_autenticado),
    db: Session = Depends(get_db),
):
    """Registra a janela do navegador aberta para o job — rastro de quem viu o quê."""
    dados = _corpo_json(await request.body())
    job = _job_do_agente(db, agente, job_id, str(dados.get("lease_token") or ""))
    url = str(dados.get("url") or portal.PORTAL_SERVICOS)
    if not portal.url_permitida(url):
        raise HTTPException(
            status_code=422,
            detail="URL fora dos domínios oficiais permitidos para este módulo.",
        )
    sessao = SessaoNavegador(
        job_id=job.id,
        agente_id=agente.id,
        navegador=str(dados.get("navegador") or "")[:40],
        versao=str(dados.get("versao") or "")[:40],
        perfil=str(dados.get("perfil") or "")[:120],
        url_inicial=url[:500],
        identidade=certificado_exigido(StatusJob(job.status)).value,
    )
    db.add(sessao)
    db.flush()
    srv_eventos.registrar_evento(
        db,
        job,
        "navegador_aberto",
        mensagem=f"Navegador aberto em {url}",
        ator=f"agente:{agente.id}",
        agente_id=agente.id,
        detalhe={"sessao_navegador": sessao.id},
    )
    db.commit()
    return {"sessao_id": sessao.id}


@router.post("/jobs/{job_id}/resultado", response_model=esq.JobResumoSaida)
async def resultado(
    job_id: int,
    request: Request,
    agente: Agente = Depends(agente_autenticado),
    db: Session = Depends(get_db),
):
    """Fecha uma fase do job — **só** com confirmação real do portal."""
    entrada = esq.ResultadoEntrada.model_validate(_corpo_json(await request.body()))
    job = _job_do_agente(db, agente, job_id, entrada.lease_token)

    if entrada.resultado == "outorga_registrada":
        if fase_do_status(StatusJob(job.status)) is not FaseJob.OUTORGA:
            raise HTTPException(status_code=409, detail="Este job não está na fase de outorga.")
        srv_eventos.registrar_evento(
            db,
            job,
            "confirmacao_portal",
            mensagem=entrada.confirmacao_portal[:1000],
            ator=f"agente:{agente.id}",
            agente_id=agente.id,
            detalhe={"protocolo": entrada.protocolo or None},
        )
        if entrada.vigencia_ate:
            job.vigencia_ate = entrada.vigencia_ate
        srv_fila.registrar_outorga(
            db, job, protocolo=entrada.protocolo, agente_id=agente.id
        )
        srv_fila.liberar_lease(db, job)

    elif entrada.resultado == "aceite_registrado":
        if fase_do_status(StatusJob(job.status)) is not FaseJob.ACEITE:
            raise HTTPException(status_code=409, detail="Este job não está na fase de aceite.")
        srv_eventos.registrar_evento(
            db,
            job,
            "confirmacao_portal",
            mensagem=entrada.confirmacao_portal[:1000],
            ator=f"agente:{agente.id}",
            agente_id=agente.id,
        )
        srv_fila.registrar_aceite(db, job, agente_id=agente.id)
        srv_fila.liberar_lease(db, job)

    elif entrada.resultado == "intervencao":
        srv_fila.pedir_intervencao(
            db,
            job,
            entrada.mensagem or "A estação pediu intervenção humana.",
            codigo=entrada.codigo_erro or CodigoErro.PORTAL_DESAFIO_ADICIONAL,
            agente_id=agente.id,
        )

    else:  # falha
        srv_fila.registrar_falha(
            db,
            job,
            entrada.codigo_erro,
            entrada.mensagem,
            agente_id=agente.id,
            detalhe={"situacao_observada": entrada.situacao_observada or None},
        )
        srv_fila.liberar_lease(db, job)

    db.commit()
    db.refresh(job)
    return esq.JobResumoSaida.model_validate(job)
