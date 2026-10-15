"""Credencial e importação NFS-e Jettax isoladas por escritório."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, SecretStr, field_validator
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_papel, requer_escrita
from app.core.config import settings
from app.core.vault import cifrar_segredo, decifrar_segredo
from app.db.session import get_db
from app.models import Empresa, JettaxCredencial, JettaxExecucao, Usuario
from app.services import auditoria, fila
from app.services.jettax import JettaxErro, ClienteJettax
from app.services.periodo import PeriodoInvalido, interpretar_periodo_obrigatorio

router = APIRouter(prefix="/integracoes/jettax", tags=["integrações · Jettax"])
_ADMIN = Depends(requer_papel("admin"))


class CredencialEntrada(BaseModel):
    token: SecretStr


class ImportacaoEntrada(BaseModel):
    empresa_ids: list[int] = Field(min_length=1, max_length=30)
    competencia: str

    @field_validator("competencia")
    @classmethod
    def competencia_valida(cls, valor):
        try:
            periodo = interpretar_periodo_obrigatorio(competencia=valor)
            return periodo.inicio.strftime("%m-%Y")
        except (PeriodoInvalido, ValueError):
            raise ValueError("Informe uma competência válida, como 10/2026.") from None


def _credencial(db: Session, escritorio_id: int) -> JettaxCredencial:
    item = db.query(JettaxCredencial).filter_by(escritorio_id=escritorio_id).first()
    if item is None:
        raise HTTPException(409, "Configure primeiro o token da API Jettax.")
    return item


def _cliente(item):
    try:
        token = decifrar_segredo(item.token_cifrado)
    except Exception:
        raise HTTPException(409, "Token Jettax inacessível. Verifique a chave do cofre ou salve o token novamente.") from None
    return ClienteJettax(item.base_url, token, timeout=settings.jettax_timeout_segundos)


@router.get("")
def status_jettax(db: Session = Depends(get_db), escritorio_id: int = Depends(escritorio_id_atual)):
    item = db.query(JettaxCredencial).filter_by(escritorio_id=escritorio_id).first()
    return {"configurado": item is not None, "base_url": item.base_url if item else settings.jettax_base_url,
            "ultima_sincronizacao_em": item.ultima_sincronizacao_em if item else None}


@router.put("/credencial")
def salvar_credencial(dados: CredencialEntrada, db: Session = Depends(get_db),
                      escritorio_id: int = Depends(escritorio_id_atual), usuario: Usuario = _ADMIN):
    token = dados.token.get_secret_value().strip()
    try:
        ClienteJettax(settings.jettax_base_url, token, timeout=settings.jettax_timeout_segundos).testar()
    except JettaxErro as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    try:
        cifrado = cifrar_segredo(token)
    except Exception:
        raise HTTPException(409, "Não foi possível proteger o token. Verifique a configuração do cofre Fernet.") from None
    item = db.query(JettaxCredencial).filter_by(escritorio_id=escritorio_id).first()
    if item is None:
        item = JettaxCredencial(escritorio_id=escritorio_id, token_cifrado=cifrado, base_url=settings.jettax_base_url)
        db.add(item)
    item.token_cifrado = cifrado
    item.base_url = settings.jettax_base_url
    auditoria.registrar(db, usuario, "jettax_credencial_atualizada", entidade="integracao", detalhe="Token Jettax atualizado no cofre")
    db.commit()
    return {"configurado": True}


@router.delete("/credencial", status_code=204)
def remover_credencial(db: Session = Depends(get_db), escritorio_id: int = Depends(escritorio_id_atual), usuario: Usuario = _ADMIN):
    db.query(JettaxCredencial).filter_by(escritorio_id=escritorio_id).delete()
    auditoria.registrar(db, usuario, "jettax_credencial_removida", entidade="integracao", detalhe="Token Jettax removido")
    db.commit()
    return Response(status_code=204)


@router.post("/testar")
def testar(db: Session = Depends(get_db), escritorio_id: int = Depends(escritorio_id_atual), _usuario: Usuario = _ADMIN):
    try:
        _cliente(_credencial(db, escritorio_id)).testar()
    except JettaxErro as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return {"ok": True, "mensagem": "Conexão autenticada com o Jettax verificada."}


def _resposta(item, nome):
    return {"id": item.id, "empresa_id": item.empresa_id, "empresa_nome": nome,
            "competencia": item.competencia, "status": item.status, "resultado": item.resultado,
            "mensagem": item.mensagem, "criado_em": item.criado_em, "finalizado_em": item.finalizado_em}


@router.post("/importar", status_code=202)
def solicitar_importacao(dados: ImportacaoEntrada, db: Session = Depends(get_db),
                         escritorio_id: int = Depends(escritorio_id_atual), usuario: Usuario = Depends(requer_escrita)):
    _credencial(db, escritorio_id)
    ids = sorted(set(dados.empresa_ids))
    empresas = db.query(Empresa).filter(Empresa.id.in_(ids), Empresa.escritorio_id == escritorio_id,
                                       Empresa.ativa.is_(True)).order_by(Empresa.id).with_for_update().all()
    if len(empresas) != len(ids):
        raise HTTPException(404, "Uma das empresas não existe ou está inativa neste escritório.")
    if not fila.fila_respondendo():
        raise HTTPException(503, "A fila não respondeu. Verifique Redis e worker e tente novamente.")
    # Trava das empresas serializa cliques concorrentes sem criar execuções duplicadas.
    novas, todas = [], []
    limite_antigo = datetime.now(timezone.utc) - timedelta(seconds=settings.limite_tempo_task_segundos + 600)
    for empresa in empresas:
        anteriores = db.query(JettaxExecucao).filter_by(escritorio_id=escritorio_id, empresa_id=empresa.id,
                                                      competencia=dados.competencia).filter(
            JettaxExecucao.status.in_(("pendente", "em_andamento"))).all()
        atual = None
        for anterior in anteriores:
            referencia = anterior.iniciado_em or anterior.criado_em
            if referencia is not None:
                referencia = referencia.astimezone(timezone.utc) if referencia.tzinfo else referencia.replace(tzinfo=timezone.utc)
            if referencia and referencia < limite_antigo:
                anterior.status = "erro"
                anterior.mensagem = "Execução antiga sem conclusão. Novo pedido criado para recuperar sem duplicar notas."
                anterior.finalizado_em = datetime.now(timezone.utc)
            else:
                atual = anterior
        if atual is None:
            atual = JettaxExecucao(escritorio_id=escritorio_id, empresa_id=empresa.id, competencia=dados.competencia,
                                   status="pendente", resultado={})
            db.add(atual)
            novas.append(atual)
        todas.append((atual, empresa.razao_social))
    auditoria.registrar(db, usuario, "jettax_importacao_solicitada", entidade="integracao",
                        detalhe=f"NFS-e: {len(novas)} empresas enfileiradas, competência {dados.competencia}")
    db.commit()
    from app.worker.jettax import importar_jettax_nfse
    for item in novas:
        try:
            importar_jettax_nfse.apply_async(kwargs={"execucao_id": item.id, "escritorio_id": escritorio_id}, retry=False)
        except Exception:
            item.status = "erro"
            item.mensagem = "Não foi possível enviar esta empresa ao worker. Verifique a fila e execute novamente."
            item.finalizado_em = datetime.now(timezone.utc)
            db.commit()
    return [_resposta(item, nome) for item, nome in todas]


@router.get("/execucoes")
def listar_execucoes(db: Session = Depends(get_db), escritorio_id: int = Depends(escritorio_id_atual)):
    itens = db.query(JettaxExecucao, Empresa.razao_social).join(Empresa, Empresa.id == JettaxExecucao.empresa_id).filter(
        JettaxExecucao.escritorio_id == escritorio_id, Empresa.escritorio_id == escritorio_id,
    ).order_by(JettaxExecucao.id.desc()).limit(50).all()
    return [_resposta(item, nome) for item, nome in itens]
