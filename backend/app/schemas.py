from datetime import date, datetime
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
    sincronizar_automaticamente: bool = True
    quais_tipos_sincronizar: str = "nfse,nfe,cte"


class EmpresaAtualizar(BaseModel):
    """Tudo opcional: só o que vier é alterado."""

    razao_social: str | None = None
    uf: str | None = None
    ativa: bool | None = None
    sincronizar_automaticamente: bool | None = None
    quais_tipos_sincronizar: list[TipoDocumentoFiscal] | None = None

    @field_validator("uf")
    @classmethod
    def uf_valida(cls, v: str | None) -> str | None:
        if v is None:
            return None
        uf = v.strip().upper()
        if uf not in _UFS_VALIDAS:
            raise ValueError(f"UF inválida: {v!r}")
        return uf

    @field_validator("razao_social")
    @classmethod
    def razao_ok(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("Razão social não pode ficar vazia.")
        return v


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
    competencia: date | None = None
    valor_total: float
    status: StatusDocumentoFiscal
    motivo_cancelamento: str | None = None
    cancelado_em: datetime | None = None
    # "resumo" = a SEFAZ ainda só distribuiu o resNFe; dá para buscar o XML
    # inteiro pela chave (botão "completar XML" / task automática).
    leiaute: str = "completo"
    numero: str | None = None
    serie: str | None = None
    emitente_nome: str | None = None
    emitente_documento: str | None = None
    destinatario_nome: str | None = None
    nsu: str | None = None


class EmpresaResumoDocumentos(BaseModel):
    """Por empresa: quantas notas há no período pedido (alimenta o 'baixar tudo')."""

    empresa_id: int
    razao_social: str
    total: int
    normais: int
    canceladas: int
    sem_xml_completo: int = 0
    valor_total: float = 0.0


# ---------- Importação ----------

class ImportacaoSolicitar(BaseModel):
    empresa_id: int
    tipo: TipoDocumentoFiscal
    forcar: bool = False  # pula a janela de consumo de 1h — usar com consciência
    # Competência desejada, ex.: "08/2026". Alternativa: data_inicio/data_fim.
    # Ela não corta a descarga (a API oficial anda por NSU), mas registra o mês
    # na execução, conta quantas notas caíram nele e pré-seleciona o download.
    competencia: str | None = None
    data_inicio: date | None = None
    data_fim: date | None = None


class ItemImportacaoLote(BaseModel):
    empresa_id: int
    razao_social: str
    # enfileirada | em_cooldown | sem_certificado | sem_uf | ja_em_andamento
    status: str
    execucao_id: int | None = None
    disponivel_em: datetime | None = None
    mensagem: str = ""


class ExecucaoImportacaoResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    tipo: TipoDocumentoFiscal
    status: StatusExecucao
    documentos_importados: int
    documentos_cancelados: int
    eventos_nao_reconhecidos: int
    documentos_no_periodo: int = 0
    iniciado_em: datetime
    finalizado_em: datetime | None
    mensagem_erro: str | None = None
    aviso: str | None = None
    ultimo_nsu: str | None = None
    empresa_razao_social: str | None = None
    data_inicio: date | None = None
    data_fim: date | None = None
    tentativas: int = 0
    bloqueado_ate: datetime | None = None
    origem: str = "manual"
    forcar: bool = False


class EstadoSincronizacaoResposta(BaseModel):
    """Estado vivo de uma combinação empresa+tipo (o "preciso fazer algo?")."""

    empresa_id: int
    razao_social: str
    tipo: str
    ultimo_nsu: str = "0"
    max_nsu: str | None = None
    pendencia: int = 0
    em_dia: bool = False
    bloqueado_ate: datetime | None = None
    motivo_bloqueio: str | None = None
    bloqueios_seguidos: int = 0
    proxima_consulta_em: datetime | None = None
    ultima_consulta_em: datetime | None = None
    em_andamento: bool = False
    travado: bool = False
    sincronizar_automaticamente: bool = True
    cota_pontual_disponivel: int = 20
    #: dias desde a última varredura bem-sucedida (None = nunca varreu)
    dias_sem_varrer: int | None = None
    #: a distribuição só guarda ~3 meses: parado esse tempo todo, o que falta
    #: pode já ter saído do webservice — vale conferir com o cliente
    risco_documento_fora_da_distribuicao: bool = False


class ResumoSincronizacao(BaseModel):
    empresas: int = 0
    combinacoes: int = 0
    em_dia: int = 0
    com_pendencia: int = 0
    em_andamento: int = 0
    aguardando_janela: int = 0
    bloqueadas_sefaz: int = 0
    documentos_no_banco: int = 0
    sincronismo_automatico: bool = True
    intervalo_minutos: int = 5
    tick_a_partir_de: datetime | None = None


# ---------- Exportação em massa ----------

class EstimativaExportacao(BaseModel):
    """O tamanho do "baixar tudo" antes de clicar nele."""

    documentos: int
    empresas: int
    periodo: str
    estimado_bytes: int
    limite: int

    @property
    def estourou_limite(self) -> bool:
        return self.documentos > self.limite


class ResumoDocumentos(BaseModel):
    total: int
    normais: int
    canceladas: int
    por_tipo: dict[str, int]
