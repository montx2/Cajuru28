from datetime import datetime
import re

from pydantic import BaseModel, ConfigDict, field_validator

from app.models import (
    DirecaoDocumento,
    StatusDocumentoFiscal,
    StatusExecucao,
    TipoDocumentoFiscal,
)

_UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}


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

    @field_validator("cnpj_cpf")
    @classmethod
    def normalizar_documento(cls, v: str) -> str:
        digitos = re.sub(r"\D", "", v or "")
        if len(digitos) not in (11, 14):
            raise ValueError("CNPJ deve ter 14 dígitos ou CPF 11 dígitos")
        return digitos

    @field_validator("uf")
    @classmethod
    def validar_uf(cls, v: str) -> str:
        uf = (v or "").strip().upper()
        if uf not in _UFS_VALIDAS:
            raise ValueError(f"UF inválida: {v!r}")
        return uf

    @field_validator("razao_social")
    @classmethod
    def razao_nao_vazia(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Razão social é obrigatória")
        return v


class EmpresaResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    razao_social: str
    cnpj_cpf: str
    uf: str
    ativa: bool
    criado_em: datetime


class ItemLoteEmpresas(BaseModel):
    """Resultado de UMA entrada (arquivo .pfx ou linha do CSV) do lote."""

    origem: str  # nome do arquivo ou "CSV linha N"
    cnpj_cpf: str = ""
    razao_social: str = ""
    uf: str = ""
    status: str  # criada | certificado_atualizado | ja_existia | erro
    mensagem: str = ""
    empresa_id: int | None = None
    certificado_id: int | None = None
    validade: datetime | None = None


class LoteEmpresasResposta(BaseModel):
    total: int
    criadas: int
    certificados: int
    ja_existiam: int
    erros: int
    itens: list[ItemLoteEmpresas]


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
    status: StatusDocumentoFiscal
    motivo_cancelamento: str | None = None
    cancelado_em: datetime | None = None


class ResumoDocumentos(BaseModel):
    total: int
    normais: int
    canceladas: int
    por_tipo: dict[str, int]


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
    documentos_cancelados: int
    eventos_nao_reconhecidos: int
    iniciado_em: datetime
    finalizado_em: datetime | None
    mensagem_erro: str | None = None
    aviso: str | None = None
    ultimo_nsu: str | None = None
    empresa_razao_social: str | None = None
