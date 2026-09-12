"""Configuração e sincronização de empresas com o Sistema Acessórias."""
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_papel
from app.core.documentos import normalizar_documento
from app.core.vault import cifrar_segredo, decifrar_segredo
from app.db.session import get_db
from app.models import AcessoriasCredencial, Empresa, Usuario
from app.services import auditoria
from app.services.acessorias import AcessoriasErro, ClienteAcessorias

router = APIRouter(prefix="/integracoes/acessorias", tags=["integrações · Acessórias"])
_ADMIN = Depends(requer_papel("admin"))


class CredencialEntrada(BaseModel):
    token: str
    base_url: str = "https://api.acessorias.com"

    @field_validator("token")
    @classmethod
    def token_valido(cls, valor: str) -> str:
        valor = valor.strip()
        if not valor or len(valor) > 4096:
            raise ValueError("Informe um token válido")
        return valor


class SincronizacaoEntrada(BaseModel):
    atualizar_existentes: bool = True
    somente_ativas: bool = True


def _credencial(db: Session, escritorio_id: int) -> AcessoriasCredencial:
    item = db.query(AcessoriasCredencial).filter_by(escritorio_id=escritorio_id).first()
    if item is None:
        raise HTTPException(status_code=409, detail="Configure primeiro o token da API Acessórias.")
    return item


def _cliente(item: AcessoriasCredencial) -> ClienteAcessorias:
    return ClienteAcessorias(item.base_url, decifrar_segredo(item.token_cifrado))


def _erro(exc: AcessoriasErro) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("")
def status_acessorias(db: Session = Depends(get_db), escritorio_id: int = Depends(escritorio_id_atual)):
    item = db.query(AcessoriasCredencial).filter_by(escritorio_id=escritorio_id).first()
    return {"configurado": item is not None, "base_url": item.base_url if item else "https://api.acessorias.com", "ultima_sincronizacao_em": item.ultima_sincronizacao_em if item else None}


@router.put("/credencial")
def salvar_credencial(dados: CredencialEntrada, db: Session = Depends(get_db), escritorio_id: int = Depends(escritorio_id_atual), usuario: Usuario = _ADMIN):
    partes = urlparse(dados.base_url)
    if partes.scheme != "https" or partes.hostname != "api.acessorias.com" or partes.username or partes.password:
        raise HTTPException(status_code=422, detail="Use o endereço oficial https://api.acessorias.com.")
    try:
        ClienteAcessorias(dados.base_url, dados.token).testar()
    except AcessoriasErro as exc:
        raise _erro(exc)
    item = db.query(AcessoriasCredencial).filter_by(escritorio_id=escritorio_id).first()
    if item is None:
        item = AcessoriasCredencial(escritorio_id=escritorio_id, token_cifrado="", base_url=dados.base_url.rstrip("/"))
        db.add(item)
    item.base_url = dados.base_url.rstrip("/")
    item.token_cifrado = cifrar_segredo(dados.token)
    auditoria.registrar(db, usuario, "acessorias_credencial_atualizada", entidade="integracao", detalhe="Token Acessórias atualizado no cofre")
    db.commit()
    return {"configurado": True, "base_url": item.base_url}


@router.delete("/credencial", status_code=204)
def remover_credencial(db: Session = Depends(get_db), escritorio_id: int = Depends(escritorio_id_atual), usuario: Usuario = _ADMIN):
    db.query(AcessoriasCredencial).filter_by(escritorio_id=escritorio_id).delete()
    auditoria.registrar(db, usuario, "acessorias_credencial_removida", entidade="integracao", detalhe="Token Acessórias removido")
    db.commit()
    return Response(status_code=204)


@router.post("/testar")
def testar(db: Session = Depends(get_db), escritorio_id: int = Depends(escritorio_id_atual), _usuario: Usuario = _ADMIN):
    try:
        _cliente(_credencial(db, escritorio_id)).testar()
    except AcessoriasErro as exc:
        raise _erro(exc)
    return {"ok": True, "mensagem": "Conexão autenticada com o Acessórias verificada."}


@router.post("/sincronizar-empresas")
def sincronizar_empresas(dados: SincronizacaoEntrada, db: Session = Depends(get_db), escritorio_id: int = Depends(escritorio_id_atual), usuario: Usuario = _ADMIN):
    credencial = _credencial(db, escritorio_id)
    try:
        remotas = _cliente(credencial).listar_empresas(somente_ativas=dados.somente_ativas)
    except AcessoriasErro as exc:
        raise _erro(exc)
    locais = {e.cnpj_cpf: e for e in db.query(Empresa).filter_by(escritorio_id=escritorio_id).all()}
    criadas = atualizadas = ignoradas = invalidas = 0
    for remota in remotas:
        try:
            documento = normalizar_documento(str(remota.get("Identificador") or ""))
        except ValueError:
            invalidas += 1
            continue
        razao = str(remota.get("Razao") or remota.get("Fantasia") or documento).strip()[:255]
        uf = str(remota.get("UF") or "").strip().upper()
        if len(uf) != 2:
            invalidas += 1
            continue
        ativa = str(remota.get("Status") or "").strip().lower() == "ativa"
        empresa = locais.get(documento)
        if empresa is None:
            empresa = Empresa(escritorio_id=escritorio_id, cnpj_cpf=documento, razao_social=razao, uf=uf, ativa=ativa)
            db.add(empresa); locais[documento] = empresa; criadas += 1
        elif dados.atualizar_existentes:
            empresa.razao_social, empresa.uf, empresa.ativa = razao, uf, ativa
            atualizadas += 1
        else:
            ignoradas += 1
    credencial.ultima_sincronizacao_em = datetime.now(timezone.utc)
    auditoria.registrar(db, usuario, "acessorias_empresas_sincronizadas", entidade="integracao", detalhe=f"{criadas} criadas, {atualizadas} atualizadas, {invalidas} inválidas")
    db.commit()
    return {"recebidas": len(remotas), "criadas": criadas, "atualizadas": atualizadas, "ignoradas": ignoradas, "invalidas": invalidas}
