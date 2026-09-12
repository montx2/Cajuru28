"""Superfície protegida da integração Jettax 360 / Morfeu."""

from __future__ import annotations

import base64
import hmac
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_escrita, requer_papel
from app.core.config import settings
from app.core.vault import SegredoIndecifravelError, decifrar_segredo
from app.db.session import get_db
from app.models import (
    Certificado,
    Empresa,
    Escritorio,
    JettaxConfiguracaoEmpresa,
    JettaxExecucao,
    JettaxSaudeConector,
    JettaxWebhookEvento,
    TipoDocumentoFiscal,
    Usuario,
)
from app.schemas import (
    JettaxConfiguracaoAtualizar,
    JettaxConfiguracaoResposta,
    JettaxExecucaoResposta,
    JettaxImportarNFe,
    JettaxImportarNFSe,
    JettaxRegistroEmpresa,
    JettaxStatusResposta,
    JettaxTesteConexaoResposta,
    JettaxWebhookEntrada,
    JettaxWebhookEventoResposta,
)
from app.services import auditoria
from app.services.certificados import ler_pfx_protegido
from app.services.jettax import ClienteJettax, JettaxErro, carga_cliente, cursor_para

router = APIRouter(prefix="/integracoes/jettax", tags=["integrações · Jettax"])

_ADMIN = Depends(requer_papel("admin"))
_ESCRITA = Depends(requer_escrita)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _empresa_do_escritorio(db: Session, empresa_id: int, escritorio_id: int) -> Empresa:
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return empresa


def _configuracao(db: Session, empresa_id: int, *, criar: bool = False) -> JettaxConfiguracaoEmpresa | None:
    configuracao = db.query(JettaxConfiguracaoEmpresa).filter_by(empresa_id=empresa_id).first()
    if configuracao is None and criar:
        configuracao = JettaxConfiguracaoEmpresa(empresa_id=empresa_id)
        db.add(configuracao)
        db.flush()
    return configuracao


def _resposta_configuracao(configuracao: JettaxConfiguracaoEmpresa | None, empresa_id: int) -> JettaxConfiguracaoResposta:
    if configuracao is None:
        return JettaxConfiguracaoResposta(empresa_id=empresa_id)
    return JettaxConfiguracaoResposta.model_validate(configuracao)


def _erro_http(exc: JettaxErro) -> HTTPException:
    codigo = 503 if exc.categoria in {"nao_configurada", "indisponivel"} else 422
    if exc.categoria == "autenticacao":
        codigo = 502
    return HTTPException(status_code=codigo, detail=str(exc))


def _marcar_falha_registro(db: Session, configuracao: JettaxConfiguracaoEmpresa, mensagem: str) -> None:
    configuracao.status = "erro"
    configuracao.ultimo_erro = mensagem[:500]
    configuracao.falhas_seguidas = (configuracao.falhas_seguidas or 0) + 1


def _certificado_para_jettax(db: Session, empresa_id: int) -> tuple[str, str]:
    certificado = (
        db.query(Certificado)
        .filter(Certificado.empresa_id == empresa_id, Certificado.ativo.is_(True))
        .order_by(Certificado.id.desc())
        .first()
    )
    if certificado is None:
        raise HTTPException(status_code=422, detail="Nenhum certificado A1 ativo para enviar à Jettax.")
    if not certificado.arquivo_path or not os.path.isfile(certificado.arquivo_path):
        raise HTTPException(status_code=422, detail="Arquivo do certificado A1 não está disponível no volume seguro.")
    try:
        senha = decifrar_segredo(certificado.senha_cifrada)
    except (SegredoIndecifravelError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail="Não foi possível abrir o certificado A1 no cofre do servidor.") from exc
    try:
        conteudo = ler_pfx_protegido(certificado.arquivo_path)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Não foi possível abrir o certificado A1 no volume seguro.") from exc
    if not conteudo:
        raise HTTPException(status_code=422, detail="O arquivo do certificado A1 está vazio.")
    # Retorno existe somente na memória desta chamada. Não logue nem adicione
    # estes valores a modelos/auditoria/respostas.
    return base64.b64encode(conteudo).decode("ascii"), senha


def _corpo_cliente(db: Session, empresa: Empresa, configuracao: JettaxConfiguracaoEmpresa, enviar_certificado: bool) -> dict:
    if not enviar_certificado:
        return carga_cliente(empresa, configuracao)
    certificado_base64, senha = _certificado_para_jettax(db, empresa.id)
    return carga_cliente(
        empresa,
        configuracao,
        certificado_base64=certificado_base64,
        senha_certificado=senha,
    )


@router.get("", response_model=JettaxStatusResposta)
def status_jettax(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Estado seguro do conector; o token nunca faz parte desta resposta."""
    saude = db.query(JettaxSaudeConector).filter_by(escritorio_id=escritorio_id).first()
    base = urlparse(settings.jettax_api_base_url)
    base_segura = f"{base.scheme}://{base.netloc}" if base.scheme and base.netloc else ""
    base_query = db.query(JettaxConfiguracaoEmpresa).join(Empresa).filter(Empresa.escritorio_id == escritorio_id)
    return JettaxStatusResposta(
        configurado=bool((settings.jettax_api_token or "").strip()),
        base_url=base_segura,
        webhook_configurado=bool((settings.jettax_webhook_secret or "").strip()),
        saude=saude.status if saude else "desconhecido",
        verificado_em=saude.verificado_em if saude else None,
        mensagem=saude.mensagem if saude else None,
        empresas_registradas=base_query.filter(JettaxConfiguracaoEmpresa.status.in_(["registrada", "atualizada"])).count(),
        empresas_ativas=base_query.filter(JettaxConfiguracaoEmpresa.ativa.is_(True)).count(),
    )


@router.post("/testar", response_model=JettaxTesteConexaoResposta)
def testar_conexao_jettax(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    """Teste autenticado, de leitura, no endpoint público de cidades Morfeu."""
    saude = db.query(JettaxSaudeConector).filter_by(escritorio_id=escritorio_id).first()
    if saude is None:
        saude = JettaxSaudeConector(escritorio_id=escritorio_id)
        db.add(saude)
    agora = _agora()
    try:
        ClienteJettax().verificar_conexao()
    except JettaxErro as exc:
        saude.status = "erro"
        saude.verificado_em = agora
        saude.mensagem = str(exc)[:500]
        auditoria.registrar(db, usuario, "jettax_teste_falhou", entidade="integracao", detalhe="Teste autenticado do conector falhou")
        db.commit()
        raise _erro_http(exc)
    saude.status = "ok"
    saude.verificado_em = agora
    saude.mensagem = "Conexão autenticada verificada."
    auditoria.registrar(db, usuario, "jettax_testado", entidade="integracao", detalhe="Teste autenticado de leitura concluído")
    db.commit()
    return JettaxTesteConexaoResposta(status="ok", verificado_em=agora, mensagem=saude.mensagem)


@router.get("/empresas/{empresa_id}", response_model=JettaxConfiguracaoResposta)
def obter_configuracao_empresa(
    empresa_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    _empresa_do_escritorio(db, empresa_id, escritorio_id)
    return _resposta_configuracao(_configuracao(db, empresa_id), empresa_id)


@router.put("/empresas/{empresa_id}", response_model=JettaxConfiguracaoResposta)
def atualizar_configuracao_empresa(
    empresa_id: int,
    dados: JettaxConfiguracaoAtualizar,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    """Atualiza apenas preferências locais; não cria/altera cliente remoto."""
    _empresa_do_escritorio(db, empresa_id, escritorio_id)
    configuracao = _configuracao(db, empresa_id, criar=True)
    mudancas = dados.model_dump(exclude_unset=True)
    for campo, valor in mudancas.items():
        setattr(configuracao, campo, valor)
    auditoria.registrar(
        db, usuario, "jettax_configuracao_atualizada", entidade="empresa", entidade_id=empresa_id,
        detalhe="Preferências locais: " + (", ".join(sorted(mudancas)) if mudancas else "sem alterações"),
    )
    db.commit()
    db.refresh(configuracao)
    return configuracao


@router.post("/empresas/{empresa_id}/registrar", response_model=JettaxConfiguracaoResposta)
def registrar_cliente_jettax(
    empresa_id: int,
    dados: JettaxRegistroEmpresa,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    """Cria explicitamente o cliente Jettax; nunca faz DELETE remoto."""
    empresa = _empresa_do_escritorio(db, empresa_id, escritorio_id)
    configuracao = _configuracao(db, empresa_id, criar=True)
    try:
        ClienteJettax().criar_cliente(_corpo_cliente(db, empresa, configuracao, dados.enviar_certificado))
    except JettaxErro as exc:
        _marcar_falha_registro(db, configuracao, str(exc))
        auditoria.registrar(db, usuario, "jettax_cliente_criacao_falhou", entidade="empresa", entidade_id=empresa_id, detalhe="Cadastro remoto rejeitado ou indisponível")
        db.commit()
        raise _erro_http(exc)
    configuracao.status = "registrada"
    configuracao.ultimo_registro_em = _agora()
    configuracao.ultimo_erro = None
    configuracao.falhas_seguidas = 0
    auditoria.registrar(
        db, usuario, "jettax_cliente_criado", entidade="empresa", entidade_id=empresa_id,
        detalhe="Cliente criado na Jettax" + (" com certificado A1" if dados.enviar_certificado else " sem transferir certificado"),
    )
    db.commit()
    db.refresh(configuracao)
    return configuracao


@router.put("/empresas/{empresa_id}/registrar", response_model=JettaxConfiguracaoResposta)
def atualizar_cliente_jettax(
    empresa_id: int,
    dados: JettaxRegistroEmpresa,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ADMIN,
):
    """Atualiza explicitamente o cliente remoto pelo contrato PUT documentado."""
    empresa = _empresa_do_escritorio(db, empresa_id, escritorio_id)
    configuracao = _configuracao(db, empresa_id, criar=True)
    try:
        ClienteJettax().atualizar_cliente(
            empresa.cnpj_cpf, _corpo_cliente(db, empresa, configuracao, dados.enviar_certificado)
        )
    except JettaxErro as exc:
        _marcar_falha_registro(db, configuracao, str(exc))
        auditoria.registrar(db, usuario, "jettax_cliente_atualizacao_falhou", entidade="empresa", entidade_id=empresa_id, detalhe="Atualização remota rejeitada ou indisponível")
        db.commit()
        raise _erro_http(exc)
    configuracao.status = "atualizada"
    configuracao.ultimo_registro_em = _agora()
    configuracao.ultimo_erro = None
    configuracao.falhas_seguidas = 0
    auditoria.registrar(
        db, usuario, "jettax_cliente_atualizado", entidade="empresa", entidade_id=empresa_id,
        detalhe="Cliente atualizado na Jettax" + (" com certificado A1" if dados.enviar_certificado else " sem transferir certificado"),
    )
    db.commit()
    db.refresh(configuracao)
    return configuracao


def _recuperar_trava_expirada(db: Session, configuracao: JettaxConfiguracaoEmpresa) -> None:
    """Evita lock zumbi após queda do worker (timeout Celery + margem)."""
    if not configuracao.travado_em:
        return
    inicio = configuracao.travado_em
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=timezone.utc)
    limite = timedelta(seconds=max(60, int(settings.limite_tempo_task_segundos) + 60))
    if inicio > _agora() - limite:
        return
    pendentes = db.query(JettaxExecucao).filter(
        JettaxExecucao.empresa_id == configuracao.empresa_id,
        JettaxExecucao.status == "em_andamento",
    ).all()
    for pendente in pendentes:
        pendente.status = "erro"
        pendente.mensagem_erro = "Execução interrompida por timeout do worker; trava liberada para nova tentativa."
        pendente.finalizado_em = _agora()
    configuracao.travado_em = None
    configuracao.ultimo_erro = "Execução anterior interrompida por timeout; nova tentativa liberada."


def _enfileirar_importacao(
    db: Session,
    empresa: Empresa,
    *,
    tipo,
    fluxo: str,
    filtros: dict,
    avancar_cursor: bool,
    usuario: Usuario,
) -> JettaxExecucao:
    # No PostgreSQL o lock da linha serializa dois cliques concorrentes antes
    # de ambos criarem execuções. SQLite (usado nos testes) aceita a chamada e
    # mantém o comportamento de processo único.
    configuracao = (
        db.query(JettaxConfiguracaoEmpresa)
        .filter(JettaxConfiguracaoEmpresa.empresa_id == empresa.id)
        .with_for_update()
        .first()
    )
    if configuracao is None or configuracao.status not in {"registrada", "atualizada"}:
        raise HTTPException(status_code=409, detail="Registre ou atualize esta empresa na Jettax antes de importar.")
    if not configuracao.ativa:
        raise HTTPException(status_code=409, detail="Ative a integração Jettax desta empresa antes de importar.")
    _recuperar_trava_expirada(db, configuracao)
    em_andamento = db.query(JettaxExecucao).filter(
        JettaxExecucao.empresa_id == empresa.id, JettaxExecucao.status == "em_andamento"
    ).first()
    if em_andamento is not None or configuracao.travado_em is not None:
        raise HTTPException(status_code=409, detail="Já existe uma importação Jettax em andamento para esta empresa.")
    cursor = cursor_para(configuracao, tipo, fluxo)
    execucao = JettaxExecucao(
        empresa_id=empresa.id,
        tipo=tipo,
        fluxo=fluxo,
        avancar_cursor=avancar_cursor,
        cursor_antes=cursor,
        origem="manual",
    )
    db.add(execucao)
    configuracao.travado_em = _agora()
    auditoria.registrar(
        db, usuario, "jettax_importacao_disparada", entidade="empresa", entidade_id=empresa.id,
        detalhe=f"{tipo.value}/{fluxo}; " + ("incremental" if avancar_cursor else "consulta pontual sem avançar cursor"),
    )
    db.commit()
    db.refresh(execucao)
    try:
        from app.worker.tasks import importar_documentos_jettax

        importar_documentos_jettax.delay(execucao_id=execucao.id, filtros=filtros)
    except Exception:  # noqa: BLE001 -- resposta segura; broker não deixa lock zumbi
        execucao.status = "erro"
        execucao.mensagem_erro = "Não foi possível enfileirar a importação Jettax."
        execucao.finalizado_em = _agora()
        configuracao.travado_em = None
        configuracao.ultimo_erro = execucao.mensagem_erro
        db.commit()
        raise HTTPException(status_code=503, detail=execucao.mensagem_erro)
    return execucao


@router.post("/empresas/{empresa_id}/importar/nfse", response_model=JettaxExecucaoResposta, status_code=status.HTTP_202_ACCEPTED)
def importar_nfse_jettax(
    empresa_id: int,
    dados: JettaxImportarNFSe,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    empresa = _empresa_do_escritorio(db, empresa_id, escritorio_id)
    return _enfileirar_importacao(
        db, empresa, tipo=TipoDocumentoFiscal.NFSE,
        fluxo="nfse", filtros=dados.model_dump(mode="json", exclude_none=True),
        avancar_cursor=not dados.tem_filtros, usuario=usuario,
    )


@router.post("/empresas/{empresa_id}/importar/nfe", response_model=JettaxExecucaoResposta, status_code=status.HTTP_202_ACCEPTED)
def importar_nfe_jettax(
    empresa_id: int,
    dados: JettaxImportarNFe,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = _ESCRITA,
):
    empresa = _empresa_do_escritorio(db, empresa_id, escritorio_id)
    return _enfileirar_importacao(
        db, empresa, tipo=TipoDocumentoFiscal.NFE,
        fluxo=dados.direcao, filtros=dados.model_dump(mode="json", exclude_none=True),
        avancar_cursor=not dados.tem_filtros, usuario=usuario,
    )


@router.get("/empresas/{empresa_id}/execucoes", response_model=list[JettaxExecucaoResposta])
def listar_execucoes_jettax(
    empresa_id: int,
    limite: int = 100,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    _empresa_do_escritorio(db, empresa_id, escritorio_id)
    return (
        db.query(JettaxExecucao)
        .filter(JettaxExecucao.empresa_id == empresa_id)
        .order_by(JettaxExecucao.id.desc())
        .limit(min(max(limite, 1), 500))
        .all()
    )


def _mensagem_webhook_segura(mensagem: str | None) -> str | None:
    """Mensagens são úteis, mas não persistimos possível segredo ecoado por terceiro."""
    texto = (mensagem or "").strip()
    if not texto:
        return None
    minusculo = texto.lower()
    if any(marcador in minusculo for marcador in ("senha", "password", "token", "certificate", "certificado")):
        return "Mensagem remota redigida por conter referência a credencial."
    return texto[:1000]


@router.post("/webhooks/{segredo}", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
def receber_webhook_jettax(segredo: str, dados: JettaxWebhookEntrada, db: Session = Depends(get_db)) -> Response:
    """Recebe o contrato de webhook publicado; retries são idempotentes.

    A documentação pública não descreve assinatura. A rota, por isso, exige um
    segmento secreto de ambiente que deve fazer parte da URL cadastrada junto à
    Jettax. Sem esse segredo configurado, responde 404 e não coleta eventos.
    """
    esperado = (settings.jettax_webhook_secret or "").strip()
    if not esperado or not hmac.compare_digest(segredo, esperado):
        raise HTTPException(status_code=404, detail="Não encontrado")
    execucao = db.query(JettaxExecucao).join(Empresa).filter(JettaxExecucao.ticket == dados.ticket).first()
    escritorio_id = execucao.empresa.escritorio_id if execucao and execucao.empresa else None
    if escritorio_id is None:
        # A instalação atual é de um escritório. Em instalação multi-tenant,
        # evento sem ticket correlacionável fica sem dono em vez de vazar entre
        # tenants; uma futura operação que cria ticket faz a correlação acima.
        escritorios = db.query(Escritorio.id).limit(2).all()
        if len(escritorios) == 1:
            escritorio_id = escritorios[0][0]
    evento = JettaxWebhookEvento(
        escritorio_id=escritorio_id,
        tipo=dados.type[:60],
        ticket=dados.ticket[:120],
        status=dados.status,
        mensagem=_mensagem_webhook_segura(dados.message),
    )
    try:
        db.add(evento)
        db.commit()
    except IntegrityError:
        db.rollback()  # mesma entrega reintentada: 2xx instrui Jettax a parar
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/webhooks/eventos", response_model=list[JettaxWebhookEventoResposta])
def listar_eventos_webhook_jettax(
    limite: int = 100,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    return (
        db.query(JettaxWebhookEvento)
        .filter(JettaxWebhookEvento.escritorio_id == escritorio_id)
        .order_by(JettaxWebhookEvento.id.desc())
        .limit(min(max(limite, 1), 500))
        .all()
    )
