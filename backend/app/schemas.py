from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import DirecaoDocumento, StatusExecucao, TipoDocumentoFiscal


# ---------- Auth ----------

class LoginRequest(BaseModel):
    email: str
    senha: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Empresa ----------

class EmpresaCriar(BaseModel):
    razao_social: str
    cnpj_cpf: str
    uf: str


class EmpresaResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    razao_social: str
    cnpj_cpf: str
    uf: str
    ativa: bool
    criado_em: datetime


# ---------- Certificado ----------
# A senha entra em texto puro só nesta requisição (via HTTPS) e é cifrada
# imediatamente no endpoint antes de tocar o banco — nunca é devolvida.

class CertificadoCriar(BaseModel):
    empresa_id: int
    senha: str


class CertificadoResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    validade: datetime
    ativo: bool
    criado_em: datetime
    # note: sem campo de senha aqui, de propósito


# ---------- Documento fiscal ----------

class DocumentoFiscalResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    tipo: TipoDocumentoFiscal
    direcao: DirecaoDocumento
    chave_acesso: str
    data_emissao: datetime
    valor_total: float


# ---------- Importação ----------

class ImportacaoSolicitar(BaseModel):
    empresa_id: int
    tipo: TipoDocumentoFiscal
    forcar: bool = False  # pula o cooldown de 1h — usar com consciência


class ItemImportacaoLote(BaseModel):
    empresa_id: int
    razao_social: str
    status: str  # "enfileirada" | "em_cooldown" | "sem_certificado"
    execucao_id: int | None = None
    disponivel_em: datetime | None = None


class ExecucaoImportacaoResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    tipo: TipoDocumentoFiscal
    status: StatusExecucao
    documentos_importados: int
    iniciado_em: datetime
    finalizado_em: datetime | None
    empresa_razao_social: str | None = None
