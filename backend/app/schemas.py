from datetime import date, datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.documentos import normalizar_cnpj, normalizar_documento
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

    @field_validator("email")
    @classmethod
    def email_normalizado(cls, v: str) -> str:
        # O usuário digita "Admin@NotasFlow.local " com maiúscula, espaço no
        # fim, ou o autofill do navegador capitaliza a primeira letra. O
        # cadastro (bootstrap/UsuarioCriar) grava sempre minúsculo e sem
        # espaços — normalizar aqui é o que faz os dois lados baterem.
        return (v or "").strip().lower()

    @field_validator("senha")
    @classmethod
    def senha_sem_espaco_nas_pontas(cls, v: str) -> str:
        # Copiar a senha do CREDENCIAIS.txt costuma trazer espaço/quebra de
        # linha junto. Espaço interno é preservado (pode ser parte da senha).
        return (v or "").strip()


class TokenResponse(BaseModel):
    """Resposta de login sem expor a sessão ao JavaScript do navegador."""

    autenticado: bool = True
    token_type: str = "cookie"


class UsuarioAtual(BaseModel):
    """Quem está logado — alimenta o avatar e o nome na barra superior."""

    id: int
    nome: str
    email: str
    papel: str = "admin"
    escritorio_id: int
    escritorio_nome: str


# ---------- Empresa ----------

class EmpresaCriar(BaseModel):
    razao_social: str = ""
    cnpj_cpf: str
    # UF pode vir vazia: a rota tenta descobrir automaticamente pelo CNPJ.
    # Se não conseguir, aí sim devolve erro pedindo preenchimento manual.
    uf: str | None = ""
    # Preenchidos apenas se a empresa também for usar o conector Jettax.
    codigo_ibge: str | None = None
    inscricao_municipal: str | None = None

    @field_validator("cnpj_cpf")
    @classmethod
    def normalizar_documento(cls, v: str) -> str:
        try:
            return normalizar_documento(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("uf")
    @classmethod
    def validar_uf(cls, v: str | None) -> str:
        uf = (v or "").strip().upper()
        if not uf:
            return ""
        if uf not in _UFS_VALIDAS:
            raise ValueError(f"UF inválida: {v!r}")
        return uf

    @field_validator("razao_social")
    @classmethod
    def razao_normalizada(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("codigo_ibge")
    @classmethod
    def codigo_ibge_valido(cls, v: str | None) -> str | None:
        if v is None or not str(v).strip():
            return None
        digitos = re.sub(r"\D", "", str(v))
        if len(digitos) != 7:
            raise ValueError("Código IBGE deve ter 7 dígitos")
        return digitos

    @field_validator("inscricao_municipal")
    @classmethod
    def inscricao_municipal_valida(cls, v: str | None) -> str | None:
        valor = (v or "").strip()
        if not valor:
            return None
        if len(valor) > 100:
            raise ValueError("Inscrição municipal deve ter no máximo 100 caracteres")
        return valor


class ConsultaCNPJResposta(BaseModel):
    documento: str
    encontrado: bool
    razao_social: str = ""
    nome_fantasia: str = ""
    uf: str = ""
    municipio: str = ""
    codigo_ibge: str = ""
    fonte: str = ""
    mensagem: str = ""


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
    codigo_ibge: str | None = None
    inscricao_municipal: str | None = None


class EmpresaAtualizar(BaseModel):
    """Tudo opcional: só o que vier é alterado."""

    razao_social: str | None = None
    uf: str | None = None
    ativa: bool | None = None
    sincronizar_automaticamente: bool | None = None
    quais_tipos_sincronizar: list[TipoDocumentoFiscal] | None = None
    codigo_ibge: str | None = None
    inscricao_municipal: str | None = None

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

    @field_validator("codigo_ibge")
    @classmethod
    def codigo_ibge_atualizado(cls, v: str | None) -> str | None:
        if v is None or not str(v).strip():
            return None
        digitos = re.sub(r"\D", "", str(v))
        if len(digitos) != 7:
            raise ValueError("Código IBGE deve ter 7 dígitos")
        return digitos

    @field_validator("inscricao_municipal")
    @classmethod
    def inscricao_municipal_atualizada(cls, v: str | None) -> str | None:
        if v is None:
            return None
        valor = v.strip()
        if valor and len(valor) > 100:
            raise ValueError("Inscrição municipal deve ter no máximo 100 caracteres")
        return valor or None


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


# ---------- Integração Jettax 360 / Morfeu ----------

class JettaxConfiguracaoAtualizar(BaseModel):
    """Preferências locais; não aceita token, senha ou certificado."""

    ativa: bool | None = None
    baixar_nfes: bool | None = None
    baixar_nfes_enviadas: bool | None = None


class JettaxRegistroEmpresa(BaseModel):
    """Ação explícita que cria/atualiza o cliente remoto."""

    enviar_certificado: bool = False


class JettaxConfiguracaoResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    empresa_id: int
    status: str = "nao_registrada"
    ativa: bool = False
    baixar_nfes: bool = False
    baixar_nfes_enviadas: bool = False
    ultimo_id_nfse: str | None = None
    ultimo_id_nfe_saida: str | None = None
    ultimo_id_nfe_entrada: str | None = None
    ultimo_registro_em: datetime | None = None
    ultima_sincronizacao_em: datetime | None = None
    ultimo_erro: str | None = None
    falhas_seguidas: int = 0
    travado_em: datetime | None = None
    atualizado_em: datetime | None = None


class JettaxCredencialAtualizar(BaseModel):
    token: str
    base_url: str = "https://morfeu-api.jettax.com.br"

    @field_validator("token")
    @classmethod
    def token_obrigatorio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Informe o token da API Jettax")
        if len(v) > 4096:
            raise ValueError("Token muito longo")
        return v.strip()


class JettaxStatusResposta(BaseModel):
    configurado: bool
    base_url: str
    webhook_configurado: bool
    saude: str = "desconhecido"
    verificado_em: datetime | None = None
    mensagem: str | None = None
    empresas_registradas: int = 0
    empresas_ativas: int = 0


class JettaxTesteConexaoResposta(BaseModel):
    status: str
    verificado_em: datetime
    mensagem: str


class JettaxImportarNFSe(BaseModel):
    """Filtros documentados para `GET /api/nfse/invoices/{cnpj}`.

    Ao informar filtro, a execução é pontual e não move o cursor incremental,
    para que uma consulta seletiva jamais pule notas na próxima captura.
    """

    numero: str | None = None
    nota_situacao: Literal["autorizada", "cancelada"] | None = None
    tipo_nota: Literal["enviada", "recebida", "nfts"] | None = None
    period: str | None = None

    @field_validator("period")
    @classmethod
    def periodo_morfeu(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        valor = v.strip()
        if not re.fullmatch(r"(?:[1-9]|1[0-2])-\d{4}", valor):
            raise ValueError("period deve usar m-AAAA, por exemplo 8-2026")
        return valor

    @property
    def tem_filtros(self) -> bool:
        return any((self.numero, self.nota_situacao, self.tipo_nota, self.period))


class JettaxImportarNFe(BaseModel):
    direcao: Literal["sales", "purchases"]
    chave: str | None = None
    data_inicial: date | None = None
    data_final: date | None = None
    cnpj_destinatario: str | None = None
    cnpj_emitente: str | None = None

    @field_validator("chave")
    @classmethod
    def chave_numerica_opcional(cls, v: str | None) -> str | None:
        # Chave de acesso é um campo contratualmente numérico; sua máscara não
        # identifica pessoa/empresa e pode ser removida sem perda semântica.
        if v is None or not v.strip():
            return None
        return re.sub(r"\D", "", v)

    @field_validator("cnpj_destinatario", "cnpj_emitente")
    @classmethod
    def documento_jettax_preservado(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        try:
            return normalizar_cnpj(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @property
    def tem_filtros(self) -> bool:
        return any((self.chave, self.data_inicial, self.data_final, self.cnpj_destinatario, self.cnpj_emitente))


class JettaxExecucaoResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    empresa_id: int
    tipo: TipoDocumentoFiscal
    fluxo: str
    status: str
    avancar_cursor: bool
    cursor_antes: str | None = None
    cursor_depois: str | None = None
    documentos_importados: int = 0
    documentos_duplicados: int = 0
    documentos_ignorados: int = 0
    mensagem_erro: str | None = None
    aviso: str | None = None
    ticket: str | None = None
    origem: str = "manual"
    iniciado_em: datetime | None = None
    finalizado_em: datetime | None = None


class JettaxWebhookEntrada(BaseModel):
    """Contrato público documentado pela Jettax para a entrega de webhook."""

    type: str
    ticket: str
    status: Literal["SUCCESS", "ERROR"]
    message: str | None = None


class JettaxWebhookEventoResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    ticket: str
    status: str
    mensagem: str | None = None
    recebido_em: datetime | None = None


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


class ResumoCertificado(BaseModel):
    """
    Estado do certificado de cada empresa — para o painel avisar antes do
    problema, não depois.

    Um A1 vencido não dá erro na hora de subir: ele simplesmente faz toda
    importação daquela empresa falhar. Avisar com 30 dias de antecedência (o
    prazo real de renovação) é a diferença entre uma tarefa planejada e um
    chamado de urgência.
    """

    empresa_id: int
    razao_social: str
    tem_certificado: bool = False
    validade: datetime | None = None
    dias_para_vencer: int | None = None
    vencido: bool = False
    vence_em_breve: bool = False


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
    destinatario_documento: str | None = None
    nsu: str | None = None
    origem: str | None = None


class DocumentosExcluirLote(BaseModel):
    """Exclusão manual das notas marcadas na tela."""

    ids: list[int]

    @field_validator("ids")
    @classmethod
    def ids_validos(cls, v: list[int]) -> list[int]:
        vistos: list[int] = []
        for item in v or []:
            if item <= 0:
                raise ValueError("IDs de documentos devem ser positivos")
            if item not in vistos:
                vistos.append(item)
        if not vistos:
            raise ValueError("Selecione ao menos uma nota/documento para excluir.")
        return vistos


class ResultadoExclusaoDocumentos(BaseModel):
    excluidos: int
    ids: list[int]
    arquivos_removidos: int = 0


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
    # Período da importação: **obrigatório** (a rota recusa com 422 se as duas
    # formas vierem vazias). Ou a competência ("08/2026", que vira o mês
    # inteiro), ou o intervalo explícito — que é o que o operador digita:
    # "01/08/2026" a "31/08/2026". Aceita DD/MM/AAAA e AAAA-MM-DD; a validação
    # e a conversão ficam em `app/services/periodo.py`, uma regra só para todo
    # o sistema.
    #
    # A descarga na origem continua por NSU (a SEFAZ/ADN não filtra por data),
    # mas o período decide o que é gravado: o que estiver fora dele é
    # descartado pelo worker em vez de entulhar o acervo.
    competencia: str | None = None
    data_inicio: str | None = None
    data_fim: str | None = None


class ItemImportacaoLote(BaseModel):
    empresa_id: int
    razao_social: str
    # enfileirada | em_cooldown | sem_certificado | sem_uf | ja_em_andamento
    status: str
    execucao_id: int | None = None
    disponivel_em: datetime | None = None
    mensagem: str = ""


class ImportacaoSelecionadas(BaseModel):
    """
    Importar exatamente as empresas marcadas na tela.

    Existe porque "importar de todas" era o comportamento errado para o uso
    real: o escritório não quer varrer 30 CNPJs quando precisa de 3, e cada
    CNPJ varrido desnecessariamente gasta a cota de 1 hora da SEFAZ e atrasa a
    fila dos que importam. Selecionar é a operação padrão; "todas" passa a ser
    apenas o caso em que o usuário marca todas.
    """

    empresa_ids: list[int]
    # Tipos a puxar para cada empresa marcada. Vazio = os três.
    tipos: list[TipoDocumentoFiscal] = []
    # Período obrigatório — competência (mês inteiro) OU intervalo explícito
    # em DD/MM/AAAA / AAAA-MM-DD. A rota valida e recusa o pedido sem período.
    competencia: str | None = None
    data_inicio: str | None = None
    data_fim: str | None = None
    # Ignora a janela de 1 hora da SEFAZ. Só sob consciência explícita.
    forcar: bool = False

    @field_validator("empresa_ids")
    @classmethod
    def sem_duplicadas(cls, v: list[int]) -> list[int]:
        vistos: list[int] = []
        for item in v:
            if item not in vistos:
                vistos.append(item)
        if not vistos:
            raise ValueError("Selecione ao menos uma empresa.")
        return vistos


class ItemImportacaoSelecionada(BaseModel):
    """Resultado por empresa **e** tipo — é o que a tabela marca linha a linha."""

    empresa_id: int
    razao_social: str
    tipo: TipoDocumentoFiscal
    status: str
    execucao_id: int | None = None
    disponivel_em: datetime | None = None
    mensagem: str = ""
    enfileirada: bool = False


class ResultadoImportacaoSelecionada(BaseModel):
    total: int
    enfileiradas: int
    aguardando: int
    ignoradas: int
    itens: list[ItemImportacaoSelecionada]


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
    # Quantas notas a distribuição entregou fora do período pedido e foram
    # descartadas. É o número que explica "baixou 500, guardou 12".
    documentos_fora_do_periodo: int = 0
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
    # Quando a próxima consulta desta empresa+tipo fica liberada (o mais tarde
    # entre "fim do bloqueio 656" e "fim da janela de 1h"). É o campo que a
    # tela usa para o cronômetro regressivo — já vem calculado pela API, sem o
    # front precisar fazer conta com fuso horário.
    liberacao_em: datetime | None = None
    # Segundos que faltam até `liberacao_em` (0 = já liberado). Pronto para um
    # contador regressivo ou uma checagem "posso consultar agora?".
    segundos_para_liberar: int = 0
    # Frase pronta em português: "liberado", "libera em 42 min", etc.
    liberacao_rotulo: str = "liberado"
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


class ItemConferenciaCompetencia(BaseModel):
    """Prova operacional de uma empresa+tipo para fechar uma competência."""

    empresa_id: int
    razao_social: str
    tipo: TipoDocumentoFiscal
    status: str  # ok | precisa_conferir | pendente | aguardando | rodando | sem_certificado | sem_uf | erro | risco
    documentos: int = 0
    canceladas: int = 0
    sem_xml_completo: int = 0
    ultimo_nsu: str | None = None
    max_nsu: str | None = None
    pendencia: int = 0
    ultima_consulta_em: datetime | None = None
    proxima_consulta_em: datetime | None = None
    bloqueado_ate: datetime | None = None
    mensagem: str = ""


class ConferenciaCompetenciaResposta(BaseModel):
    """
    Resultado da conferência "posso fechar este mês sem medo?".

    `ok=True` significa: para todas as empresas/tipos pedidos, existe
    certificado/UF quando necessário, o cursor local chegou no `maxNSU` oficial
    e houve consulta depois do fim da competência. É a garantia possível sobre
    a distribuição oficial (SEFAZ/ADN), sem depender de contagem externa.
    """

    competencia: str
    inicio: date
    fim: date
    status: str  # completa | parcial | pendente | critico
    ok: bool
    mensagem: str
    documentos: int = 0
    canceladas: int = 0
    sem_xml_completo: int = 0
    empresas: int = 0
    itens_total: int = 0
    itens_ok: int = 0
    itens_pendentes: int = 0
    itens_criticos: int = 0
    itens: list[ItemConferenciaCompetencia]


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


class ResetGeralResposta(BaseModel):
    """Resultado da limpeza geral do escritório logado."""

    empresas: int = 0
    documentos: int = 0
    certificados: int = 0
    execucoes: int = 0
    sincronizacoes: int = 0
    arquivos_removidos: int = 0
    integracoes: int = 0


class DocumentoFonteResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    origem: str
    identificador_externo: str
    registrado_em: datetime | None = None


class DocumentoDetalhe(DocumentoFiscalResposta):
    """Tudo que o painel de detalhes precisa numa única chamada."""

    empresa_razao_social: str
    empresa_cnpj: str
    empresa_uf: str
    importado_em: datetime | None = None
    xml_disponivel: bool = False
    xml_bytes: int | None = None
    execucao_id: int | None = None
    fontes: list[DocumentoFonteResposta] = []


# ---------- Dashboard ----------

class KpisDashboard(BaseModel):
    competencia: str
    documentos_mes: int
    documentos_mes_anterior: int
    variacao_pct: float | None = None
    valor_mes: float
    canceladas_mes: int
    sem_xml_completo: int
    documentos_total: int
    empresas_total: int
    empresas_em_dia: int
    combinacoes_em_dia: int
    combinacoes_total: int
    certificados_vencidos: int
    certificados_vencendo: int
    empresas_sem_certificado: int
    bloqueadas_agora: int
    em_andamento: int


class EvolucaoMensal(BaseModel):
    mes: str  # AAAA-MM
    rotulo: str  # ago/26
    total: int
    valor: float
    nfse: int
    nfe: int
    cte: int


class TipoBreakdown(BaseModel):
    tipo: TipoDocumentoFiscal
    rotulo: str
    total: int
    valor: float
    percentual: float


class EmitenteTop(BaseModel):
    documento: str | None = None
    nome: str | None = None
    total: int
    valor: float


class EmpresaRanking(BaseModel):
    empresa_id: int
    razao_social: str
    total: int
    valor: float
    canceladas: int
    sem_xml: int


# ---------- Alertas ----------

class AlertaItem(BaseModel):
    id: str
    nivel: str  # critico | atencao | info
    categoria: str  # certificado | cadastro | sefaz | distribuicao | sincronismo | xml | execucao | sistema
    titulo: str
    detalhe: str
    empresa_id: int | None = None
    empresa_razao_social: str | None = None
    acao_rotulo: str | None = None
    acao_href: str | None = None


class AlertasResposta(BaseModel):
    total: int
    criticos: int
    atencao: int
    infos: int
    itens: list[AlertaItem]


# ---------- Relatórios ----------

class FechamentoTipo(BaseModel):
    qtd: int = 0
    valor: float = 0.0


class FechamentoEmpresa(BaseModel):
    empresa_id: int
    razao_social: str
    cnpj: str
    uf: str
    total: int
    valor: float
    canceladas: int
    sem_xml: int
    por_tipo: dict[str, FechamentoTipo]


class FechamentoTotais(BaseModel):
    documentos: int
    valor: float
    canceladas: int
    sem_xml: int
    empresas_com_documento: int
    empresas_total: int
    por_tipo: dict[str, FechamentoTipo]


class FechamentoMensal(BaseModel):
    competencia: str
    inicio: date
    fim: date
    totais: FechamentoTotais
    empresas: list[FechamentoEmpresa]


# ---------- Equipe ----------

_PAPEIS_VALIDOS = {"admin", "operador", "leitura"}


class UsuarioResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    email: str
    papel: str = "admin"
    ativo: bool
    criado_em: datetime


class UsuarioCriar(BaseModel):
    nome: str
    email: str
    senha: str
    papel: str = "operador"

    @field_validator("email")
    @classmethod
    def email_normalizado(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if "@" not in v or len(v) < 5:
            raise ValueError("Email inválido.")
        return v

    @field_validator("senha")
    @classmethod
    def senha_minima(cls, v: str) -> str:
        if len(v or "") < 12:
            raise ValueError("A senha precisa de ao menos 12 caracteres.")
        return v

    @field_validator("papel")
    @classmethod
    def papel_valido(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in _PAPEIS_VALIDOS:
            raise ValueError(f"Papel inválido: {v!r} (use admin, operador ou leitura).")
        return v

    @field_validator("nome")
    @classmethod
    def nome_ok(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Nome é obrigatório.")
        return v


class UsuarioAtualizar(BaseModel):
    """Tudo opcional: só o que vier é alterado."""

    nome: str | None = None
    papel: str | None = None
    ativo: bool | None = None
    senha: str | None = None

    @field_validator("papel")
    @classmethod
    def papel_ok(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in _PAPEIS_VALIDOS:
            raise ValueError(f"Papel inválido: {v!r} (use admin, operador ou leitura).")
        return v

    @field_validator("senha")
    @classmethod
    def senha_ok(cls, v: str | None) -> str | None:
        if v is not None and len(v) < 12:
            raise ValueError("A senha precisa de ao menos 12 caracteres.")
        return v


# ---------- Auditoria ----------

class RegistroAuditoriaResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    quando: datetime
    usuario_email: str
    acao: str
    entidade: str | None = None
    entidade_id: int | None = None
    detalhe: str | None = None


class TesteWebhookResposta(BaseModel):
    ok: bool
    detalhe: str


# ---------- Painel operacional (a tela "está tudo funcionando?") ----------


class PainelEmpresas(BaseModel):
    """Saúde do rebanho de empresas — a escala que importa (não usuários)."""

    cadastradas: int = 0
    ativas: int = 0
    habilitadas_sincronizacao: int = 0
    sincronizadas_hoje: int = 0
    em_dia: int = 0
    aguardando_janela: int = 0
    com_erro_24h: int = 0
    sem_certificado: int = 0


class PainelCertificados(BaseModel):
    validos: int = 0
    vencendo: int = 0
    vencidos: int = 0


class PainelExecucoes(BaseModel):
    em_andamento: int = 0
    aguardando: int = 0
    bloqueadas: int = 0
    concluidas_hoje: int = 0
    erros_24h: int = 0
    duracao_media_minutos: float | None = None


class PainelDocumentos(BaseModel):
    hoje: int = 0
    cancelados_hoje: int = 0
    total: int = 0
    aguardando_xml_completo: int = 0
    mes: int = 0
    valor_mes: float = 0.0
    competencia: str = ""


class ComponenteStatus(BaseModel):
    nome: str  # api | banco | fila | worker | agendador
    status: str  # ok | atencao | erro | desconhecido | desligado
    detalhe: str = ""


class UltimaSincronizacao(BaseModel):
    empresa_id: int
    razao_social: str
    tipo: str
    status: str
    documentos: int = 0
    finalizado_em: datetime | None = None
    iniciado_em: datetime | None = None
    mensagem_erro: str | None = None
    aviso: str | None = None


class PainelOperacional(BaseModel):
    """
    A resposta da pergunta que abre o dia: "está tudo funcionando, e existe
    algo que EU preciso resolver?".

    `status_geral` é o semáforo do topo do dashboard:
    - "operando": nada crítico, automação saudável;
    - "atencao": há pendências que precisam de olho humano em breve;
    - "critico": há bloqueio/risco ativo — a lista de atenção é o próximo clique.
    """

    status_geral: str
    mensagem: str
    alertas: dict[str, int] = {}  # {"criticos": n, "atencao": n, "info": n}
    empresas: PainelEmpresas = PainelEmpresas()
    certificados: PainelCertificados = PainelCertificados()
    execucoes: PainelExecucoes = PainelExecucoes()
    documentos: PainelDocumentos = PainelDocumentos()
    componentes: list[ComponenteStatus] = []
    ultimas_sincronizacoes: list[UltimaSincronizacao] = []


class ExecucaoAoVivo(BaseModel):
    """Uma empresa sendo trabalhada agora (ou esperando a janela abrir)."""

    execucao_id: int
    empresa_id: int
    razao_social: str
    tipo: str
    status: str  # em_andamento | aguardando
    documentos_importados: int = 0
    ultimo_nsu: str | None = None
    iniciado_em: datetime | None = None
    aguardando_ate: datetime | None = None
    motivo_espera: str | None = None
    aviso: str | None = None
    mensagem_erro: str | None = None


class JanelaProximaConsulta(BaseModel):
    """Empresa parada por janela oficial de consumo — e quando volta."""

    empresa_id: int
    razao_social: str
    tipo: str
    proxima_consulta_em: datetime
    bloqueada: bool = False
    pendencia: int = 0


class CentralExecucoes(BaseModel):
    """A tela 'Execuções': o que roda agora, o que vem depois, o que caiu."""

    agora: list[ExecucaoAoVivo] = []
    proximas: list[JanelaProximaConsulta] = []
    recentes: list[ExecucaoImportacaoResposta] = []
    erros: list[ExecucaoImportacaoResposta] = []


# ---------- Certificados (centro de certificados) ----------


class ResumoCertificadoPainel(ResumoCertificado):
    """O resumo por empresa com a telemetria de uso do A1."""

    ultima_utilizacao_em: datetime | None = None
    ultima_validacao_em: datetime | None = None
    ultimo_erro: str | None = None
    cnpj_cpf: str = ""


# ---------- Backup ----------


class BackupRegistroResposta(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    status: str
    iniciado_em: datetime
    finalizado_em: datetime | None = None
    tamanho_bytes: int | None = None
    checksum_sha256: str | None = None
    objeto_remoto: str | None = None
    arquivos_incluidos: int = 0
    empresas: int = 0
    documentos: int = 0
    execucoes: int = 0
    detalhe: str | None = None
    erro: str | None = None
    restauracao_testada_em: datetime | None = None
    restauracao_ok: bool | None = None


class SaudeBackupResposta(BaseModel):
    ativo: bool
    ultimo_ok_em: datetime | None = None
    ultimo_ok_tamanho_bytes: int | None = None
    horas_desde_ultimo_ok: float | None = None
    ultimo_teste_em: datetime | None = None
    ultimo_teste_ok: bool | None = None
    proximo_previsto_em: datetime | None = None
    retencao: int = 14
    atrasado: bool = False
    total_registros: int = 0
    erros_recentes: int = 0
    tamanho_total_bytes: int = 0
