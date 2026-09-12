import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_escrita
from app.core.config import settings
from app.core.vault import cifrar_segredo
from app.db.session import get_db
from app.models import Certificado, Empresa, Usuario
from app.schemas import CertificadoResposta, ResumoCertificado, ResumoCertificadoPainel
from app.services import auditoria
from app.services.certificados import extrair_identidade, guardar_pfx_protegido

_LIMITE_BYTES_PFX = 30 * 1024 * 1024

router = APIRouter(prefix="/certificados", tags=["certificados"])


@router.post("", response_model=CertificadoResposta, status_code=status.HTTP_201_CREATED)
async def enviar_certificado(
    empresa_id: int = Form(...),
    senha: str = Form(...),
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """
    Recebe o .pfx e a senha em texto puro apenas nesta requisição (via
    HTTPS). A senha é cifrada e o arquivo original nunca é devolvido —
    dali em diante, só o cofre sabe abri-lo.
    """
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    # Leitura limitada: um upload autenticado não pode esgotar a memória da API.
    pfx_bytes = await arquivo.read(_LIMITE_BYTES_PFX + 1)
    if len(pfx_bytes) > _LIMITE_BYTES_PFX:
        raise HTTPException(status_code=413, detail="O certificado excede o limite de 30 MB.")

    try:
        identidade = extrair_identidade(pfx_bytes, senha)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if identidade.documento != empresa.cnpj_cpf:
        # Um A1 é uma credencial fiscal: aceitar o de outra empresa permitiria
        # consultas e captura sob uma identidade diferente da cadastrada.
        raise HTTPException(
            status_code=422,
            detail="O CNPJ/CPF do certificado não corresponde à empresa selecionada.",
        )
    validade = identidade.validade_utc

    pasta_empresa = os.path.join(settings.dados_dir, "certificados", str(empresa_id))
    os.makedirs(pasta_empresa, exist_ok=True)
    caminho_arquivo = os.path.join(pasta_empresa, f"{empresa.cnpj_cpf}.pfx.enc")
    guardar_pfx_protegido(caminho_arquivo, pfx_bytes)

    # Desativa certificados anteriores desta empresa — só um ativo por vez
    db.query(Certificado).filter(
        Certificado.empresa_id == empresa_id, Certificado.ativo.is_(True)
    ).update({"ativo": False})

    certificado = Certificado(
        empresa_id=empresa_id,
        arquivo_path=caminho_arquivo,
        senha_cifrada=cifrar_segredo(senha),
        validade=validade,
        ativo=True,
        # A extração da identidade acima É a validação: o .pfx abriu, a chave
        # existe e a validade foi lida do X.509.
        ultima_validacao_em=datetime.now(timezone.utc),
        ultimo_erro=None,
    )
    db.add(certificado)
    db.flush()
    auditoria.registrar(
        db, usuario, "certificado_enviado",
        entidade="empresa", entidade_id=empresa.id,
        detalhe=f"{empresa.razao_social} — válido até {validade.strftime('%d/%m/%Y')}",
    )
    db.commit()
    db.refresh(certificado)
    return certificado


@router.get("/resumo", response_model=list[ResumoCertificado])
def resumo_certificados(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Um certificado por empresa, com a data de validade e os dias restantes.

    Existe porque **certificado vencido para a importação sem nenhum aviso** —
    e o sintoma que o contador vê ("não importa mais") não tem nada a ver com a
    causa. Com esta rota o painel consegue avisar com 30 dias de antecedência,
    que é o prazo real de renovação de um A1.
    """
    empresas = (
        db.query(Empresa.id, Empresa.razao_social)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .all()
    )
    ativos = {
        certificado.empresa_id: certificado
        for certificado in db.query(Certificado).filter(Certificado.ativo.is_(True)).all()
    }

    agora = datetime.now(timezone.utc)
    saida: list[ResumoCertificado] = []
    for empresa_id, razao_social in empresas:
        certificado = ativos.get(empresa_id)
        if certificado is None:
            saida.append(
                ResumoCertificado(
                    empresa_id=empresa_id, razao_social=razao_social, tem_certificado=False
                )
            )
            continue
        validade = certificado.validade
        if validade is not None and validade.tzinfo is None:
            validade = validade.replace(tzinfo=timezone.utc)
        dias = (validade - agora).days if validade is not None else None
        saida.append(
            ResumoCertificado(
                empresa_id=empresa_id,
                razao_social=razao_social,
                tem_certificado=True,
                validade=validade,
                dias_para_vencer=dias,
                vencido=bool(dias is not None and dias < 0),
                vence_em_breve=bool(dias is not None and 0 <= dias <= 30),
            )
        )
    saida.sort(key=lambda item: item.razao_social)
    return saida


@router.get("/painel", response_model=list[ResumoCertificadoPainel])
def painel_certificados(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    O centro de certificados: tudo de cada A1 num só lugar.

    Além da validade, devolve a telemetria de uso — última utilização real
    numa varredura, última validação e o erro da última autenticação. É o
    que transforma "vence em 20 dias" em "vence em 20 dias E não autentica
    desde terça": o operador troca o certificado ANTES de virar incêndio.
    """
    empresas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .order_by(Empresa.razao_social)
        .all()
    )
    ativos = {
        certificado.empresa_id: certificado
        for certificado in db.query(Certificado).filter(Certificado.ativo.is_(True)).all()
    }

    agora = datetime.now(timezone.utc)
    saida: list[ResumoCertificadoPainel] = []
    for empresa in empresas:
        certificado = ativos.get(empresa.id)
        if certificado is None:
            saida.append(
                ResumoCertificadoPainel(
                    empresa_id=empresa.id,
                    razao_social=empresa.razao_social,
                    cnpj_cpf=empresa.cnpj_cpf,
                    tem_certificado=False,
                )
            )
            continue
        validade = certificado.validade
        if validade is not None and validade.tzinfo is None:
            validade = validade.replace(tzinfo=timezone.utc)
        dias = (validade - agora).days if validade is not None else None
        saida.append(
            ResumoCertificadoPainel(
                empresa_id=empresa.id,
                razao_social=empresa.razao_social,
                cnpj_cpf=empresa.cnpj_cpf,
                tem_certificado=True,
                validade=validade,
                dias_para_vencer=dias,
                vencido=bool(dias is not None and dias < 0),
                vence_em_breve=bool(dias is not None and 0 <= dias <= 30),
                ultima_utilizacao_em=certificado.ultima_utilizacao_em,
                ultima_validacao_em=certificado.ultima_validacao_em,
                ultimo_erro=certificado.ultimo_erro,
            )
        )
    # Ordem de prioridade do operador: vencidos → sem certificado → vencendo
    # em breve → saudáveis. Dentro de cada grupo, alfabética.
    saida.sort(
        key=lambda item: (
            not item.vencido,
            item.tem_certificado,  # sem certificado sobe (False < True)
            not item.vence_em_breve,
            item.razao_social,
        )
    )
    return saida


@router.get("/empresa/{empresa_id}", response_model=list[CertificadoResposta])
def listar_certificados_da_empresa(
    empresa_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return db.query(Certificado).filter(Certificado.empresa_id == empresa_id).all()
