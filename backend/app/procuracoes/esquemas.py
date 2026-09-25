"""
Contratos de entrada e saída do módulo (Pydantic v2).

Dois princípios que explicam as escolhas abaixo:

1. **O que entra é validado na borda.** Documento, thumbprint, versão e
   identificador de estação têm formato conhecido; recusar cedo evita que
   lixo chegue ao banco e vire investigação depois.
2. **O que sai nunca carrega segredo.** Não existe campo de senha, PFX,
   cookie de portal ou token em nenhum modelo de resposta. O segredo de
   matrícula aparece **uma única vez**, no retorno da própria matrícula.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.documentos import normalizar_documento, validar_documento
from app.procuracoes.estados import ModoOperacao, StatusAutorizacao, StatusJob

_HEX64 = re.compile(r"^[0-9a-f]{40,64}$")


class Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


def _documento(valor: str) -> str:
    texto = normalizar_documento(valor)
    if not validar_documento(texto):
        raise ValueError("CNPJ/CPF inválido.")
    return texto


# --------------------------------------------------------------------------
# Configuração e modelos de autorização
# --------------------------------------------------------------------------


class ConfiguracaoEntrada(Base):
    outorgado_documento: str = ""
    outorgado_nome: str = Field("", max_length=255)
    modo_padrao: Literal["assistido", "consulta_api", "nao_assistido"] = "assistido"
    processamento_automatico: bool = False
    sincronizacao_automatica: bool = True
    hora_sincronizacao: int = Field(6, ge=0, le=23)
    intervalo_entre_jobs_segundos: int = Field(30, ge=0, le=3600)
    max_jobs_simultaneos: int = Field(2, ge=1, le=50)
    max_jobs_por_agente: int = Field(1, ge=1, le=10)
    max_tentativas: int = Field(3, ge=1, le=10)
    timeout_etapa_segundos: int = Field(900, ge=60, le=7200)
    timeout_job_segundos: int = Field(5400, ge=300, le=86400)
    heartbeat_tolerancia_segundos: int = Field(120, ge=30, le=3600)
    alerta_dias: str = Field("30,60,90", max_length=60)
    assinador_versao_minima: str = Field("4.0.0", max_length=20)
    assinador_exigido: bool = True
    autorizacao_formal_rfb: bool = False
    autorizacao_formal_referencia: str = Field("", max_length=500)

    @field_validator("outorgado_documento")
    @classmethod
    def _valida_outorgado(cls, valor: str) -> str:
        if not valor:
            return ""
        return _documento(valor)

    @field_validator("alerta_dias")
    @classmethod
    def _valida_alertas(cls, valor: str) -> str:
        numeros = [parte.strip() for parte in (valor or "").split(",") if parte.strip()]
        if not numeros:
            return "30"
        limpos: list[int] = []
        for numero in numeros[:6]:
            if not numero.isdigit():
                raise ValueError("Informe apenas números inteiros separados por vírgula.")
            dias = int(numero)
            if not 1 <= dias <= 365:
                raise ValueError("Cada janela de alerta deve ficar entre 1 e 365 dias.")
            limpos.append(dias)
        return ",".join(str(dia) for dia in sorted(set(limpos)))

    @model_validator(mode="after")
    def _coerencia(self):
        if self.timeout_job_segundos < self.timeout_etapa_segundos:
            raise ValueError(
                "O tempo limite do job precisa ser maior que o tempo limite de uma etapa."
            )
        if self.modo_padrao == ModoOperacao.NAO_ASSISTIDO.value and not self.autorizacao_formal_rfb:
            raise ValueError(
                "O modo não assistido só pode ser selecionado com autorização formal da "
                "Receita Federal registrada (IN RFB nº 2.320/2026, art. 13)."
            )
        return self


class ConfiguracaoSaida(ConfiguracaoEntrada):
    id: int
    atualizado_em: datetime | None = None
    modo_efetivo: str = ""
    fundamento_politica: str = ""


class ServicoModelo(Base):
    codigo: str = Field(..., min_length=1, max_length=120)
    rotulo: str = Field("", max_length=255)
    ordem: int = Field(0, ge=0, le=999)


class ModeloEntrada(Base):
    nome: str = Field(..., min_length=2, max_length=120)
    descricao: str = Field("", max_length=500)
    vigencia_meses: int = Field(60, ge=1, le=60)
    escopo_servicos: Literal["ALL", "LISTA"] = "ALL"
    padrao: bool = False
    ativo: bool = True
    servicos: list[ServicoModelo] = Field(default_factory=list)

    @model_validator(mode="after")
    def _lista_preenchida(self):
        if self.escopo_servicos == "LISTA" and not self.servicos:
            raise ValueError(
                "Um modelo com escopo 'LISTA' precisa de pelo menos um serviço marcado."
            )
        return self


class ModeloSaida(Base):
    id: int
    nome: str
    descricao: str
    vigencia_meses: int
    escopo_servicos: str
    padrao: bool
    ativo: bool
    servicos: list[ServicoModelo] = Field(default_factory=list)
    criado_em: datetime | None = None
    atualizado_em: datetime | None = None


# --------------------------------------------------------------------------
# Painel
# --------------------------------------------------------------------------


class ResumoSaida(Base):
    total_empresas: int = 0
    sem_autorizacao: int = 0
    em_analise: int = 0
    aguardando_aceite: int = 0
    ativas: int = 0
    expiradas: int = 0
    vencendo: int = 0
    canceladas: int = 0
    jobs_na_fila: int = 0
    jobs_aguardando_humano: int = 0
    jobs_com_erro: int = 0
    jobs_concluidos_24h: int = 0
    agentes_online: int = 0
    agentes_total: int = 0
    agentes_com_assinador: int = 0
    certificados_disponiveis: int = 0
    certificados_vencendo: int = 0
    notificacoes_abertas: int = 0
    duracao_media_minutos: float = 0.0
    taxa_sucesso: float = 0.0


class LinhaSaida(Base):
    empresa_id: int
    razao_social: str
    documento: str
    uf: str
    situacao: str
    data_validade: date | None = None
    dias_para_vencer: int | None = None
    prazo_aceite_ate: date | None = None
    dias_para_aceite: int | None = None
    outorgado_documento: str = ""
    protocolo: str = ""
    origem_dado: str = ""
    sincronizado_em: datetime | None = None
    job_id: int | None = None
    job_status: str = ""
    job_etapa: str = ""
    job_modo: str = ""
    job_atualizado_em: datetime | None = None
    certificado_disponivel: bool = False
    servicos: int = 0


class ListaSaida(Base):
    itens: list[LinhaSaida] = Field(default_factory=list)
    total: int = 0
    pagina: int = 1
    tamanho: int = 50


class PermissaoSaida(Base):
    codigo: str
    rotulo: str = ""
    expira_em: date | None = None
    origem: str = ""


class JobResumoSaida(Base):
    id: int
    status: str
    fase: str = ""
    etapa_atual: str = ""
    modo: str = ""
    tentativas: int = 0
    codigo_erro: str = ""
    classe_erro: str = ""
    mensagem_erro: str = ""
    motivo_intervencao: str = ""
    criado_em: datetime | None = None
    iniciado_em: datetime | None = None
    finalizado_em: datetime | None = None
    agente_id: int | None = None
    vigencia_ate: date | None = None
    protocolo: str = ""


class EventoSaida(Base):
    id: int
    job_id: int
    quando: datetime
    tipo: str
    etapa: str = ""
    status_anterior: str = ""
    status_novo: str = ""
    mensagem: str = ""
    codigo_erro: str = ""
    ator: str = ""


class CertificadoSaida(Base):
    id: int
    agente_id: int
    thumbprint: str
    titular_nome: str = ""
    documento: str = ""
    valido_ate: datetime | None = None
    situacao: str = ""
    tipo: str = ""


class DetalheSaida(Base):
    empresa: LinhaSaida
    permissoes: list[PermissaoSaida] = Field(default_factory=list)
    jobs: list[JobResumoSaida] = Field(default_factory=list)
    eventos: list[EventoSaida] = Field(default_factory=list)
    certificados: list[CertificadoSaida] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Fila
# --------------------------------------------------------------------------


class CriarJobEntrada(Base):
    empresa_id: int = Field(..., ge=1)
    modelo_id: int | None = None
    modo: Literal["assistido", "consulta_api", "nao_assistido"] | None = None
    prioridade: int = Field(100, ge=1, le=999)
    forcar: bool = False


class ProcessarPendenciasEntrada(Base):
    empresa_ids: list[int] = Field(default_factory=list, max_length=2000)
    limite: int = Field(200, ge=1, le=2000)
    modelo_id: int | None = None


class ProcessarPendenciasSaida(Base):
    avaliadas: int = 0
    criados: int = 0
    ja_na_fila: int = 0
    ignoradas: int = 0
    #: Jobs que nasceram travados por falta de A1 vigente na frota. Aparecem
    #: na tela com o motivo em vez de esperarem em silêncio.
    bloqueados_por_certificado: int = 0
    motivos: dict[str, int] = Field(default_factory=dict)
    job_ids: list[int] = Field(default_factory=list)


class AcaoJobEntrada(Base):
    motivo: str = Field("", max_length=500)


class JobDetalheSaida(JobResumoSaida):
    empresa_id: int
    empresa_nome: str = ""
    empresa_documento: str = ""
    escopo_servicos: str = "ALL"
    servicos: list[dict[str, str]] = Field(default_factory=list)
    outorgado_documento: str = ""
    outorgado_nome: str = ""
    certificado_thumbprint: str = ""
    proxima_tentativa_em: datetime | None = None
    eventos: list[EventoSaida] = Field(default_factory=list)
    evidencias: list["EvidenciaSaida"] = Field(default_factory=list)
    roteiro: list[dict[str, Any]] = Field(default_factory=list)


class EvidenciaSaida(Base):
    id: int
    etapa: str = ""
    tipo: str = ""
    sha256: str = ""
    tamanho_bytes: int = 0
    url_observada: str = ""
    criado_em: datetime | None = None


# --------------------------------------------------------------------------
# Integrações
# --------------------------------------------------------------------------


#: Tamanho mínimo de um segredo de integração. Não é número mágico: abaixo
#: disso o valor digitado é quase sempre um engano (nome do sistema, "teste",
#: usuário), e um token real de qualquer um dos fornecedores é muito maior.
MIN_SEGREDO_INTEGRACAO = 8


class CredencialEntrada(Base):
    """Credencial de fonte externa.

    As duas regras abaixo já existiam; o que mudou é **a mensagem**. Um 422 que
    diz apenas "valor inválido" obriga o operador a adivinhar qual dos três
    campos está errado — e foi exatamente o que aconteceu em produção.
    """

    fonte: Literal["jettax360", "integra_contador"]
    base_url: str = Field("", max_length=500)
    identificador: str = Field("", max_length=255)
    segredo: str = Field(..., max_length=500)
    opcoes: dict[str, Any] = Field(default_factory=dict)
    ativo: bool = True

    @field_validator("segredo")
    @classmethod
    def _segredo_utilizavel(cls, valor: str) -> str:
        texto = (valor or "").strip()
        if not texto:
            raise ValueError(
                "Informe o token/segredo da integração. Ele é cifrado no cofre e "
                "nunca mais aparece em tela, log ou resposta da API."
            )
        if len(texto) < MIN_SEGREDO_INTEGRACAO:
            raise ValueError(
                f"O segredo da integração precisa de pelo menos "
                f"{MIN_SEGREDO_INTEGRACAO} caracteres (recebido: {len(texto)}). "
                "Cole o token completo entregue pelo fornecedor."
            )
        return texto

    @field_validator("base_url")
    @classmethod
    def _https(cls, valor: str) -> str:
        texto = (valor or "").strip()
        if not texto:
            return ""
        if texto.startswith("http://"):
            raise ValueError(
                "A URL da integração precisa usar HTTPS. Troque 'http://' por "
                "'https://' — credencial não trafega em texto claro."
            )
        if not texto.startswith("https://"):
            raise ValueError(
                f"A URL da integração precisa começar com 'https://' "
                f"(recebido: '{texto[:60]}'). Exemplo: https://{texto[:60]}"
            )
        return texto.rstrip("/")


class CredencialSaida(Base):
    """Nunca inclui o segredo — só a evidência de que existe um configurado."""

    fonte: str
    rotulo: str = ""
    base_url: str = ""
    identificador: str = ""
    configurado: bool = False
    ativo: bool = False
    opcoes: dict[str, Any] = Field(default_factory=dict)
    ultima_utilizacao_em: datetime | None = None
    ultimo_erro: str = ""
    atualizado_em: datetime | None = None


class SincronizarEntrada(Base):
    fonte: Literal["jettax360", "integra_contador"]
    empresa_ids: list[int] = Field(default_factory=list, max_length=2000)


class SincronizacaoSaida(Base):
    fonte: str
    recebidos: int = 0
    criados: int = 0
    atualizados: int = 0
    inalterados: int = 0
    ignorados: int = 0
    invalidos: int = 0
    mensagem: str = ""
    erros: list[dict[str, str]] = Field(default_factory=list)


#: Fontes que entram por texto/arquivo, sem credencial. `jettax360` aqui não é
#: chamada de API: é a lista **do painel do Jettax** trazida pelo operador, e
#: por isso vale a mesma precedência da fonte Jettax na reconciliação.
FONTES_MANUAIS = ("jettax360", "planilha")


class ImportarListaEntrada(Base):
    """Importação da lista copiada da tela do fornecedor."""

    texto: str = Field(..., min_length=3, max_length=2_000_000)
    fonte: Literal["jettax360", "planilha"] = "jettax360"
    #: Declarar a aba de origem é o que permite importar uma colagem que só
    #: tem nome e documento. Vazio = deduzir do próprio texto.
    situacao_padrao: Literal["", "ativa", "expirada"] = ""

    @field_validator("texto")
    @classmethod
    def _tem_conteudo(cls, valor: str) -> str:
        if not (valor or "").strip():
            raise ValueError("Cole a lista copiada da tela antes de importar.")
        return valor


class TesteIntegracaoSaida(Base):
    fonte: str
    ok: bool
    mensagem: str


# --------------------------------------------------------------------------
# Agents (administração)
# --------------------------------------------------------------------------


class AgenteEntrada(Base):
    """Matrícula de estação.

    `identificador` é **opcional de propósito**: quem o gera é o servidor
    (`srv_agentes.gerar_identificador`). O operador não tem como saber um hash
    hexadecimal de 32 caracteres antes de a estação existir, e deixar o cliente
    escolher o próprio identificador abriria espaço para colisão e para palpite
    entre escritórios. Ele continua sendo aceito quando informado porque
    **re-credenciar** a mesma máquina (mesmo identificador, segredo novo) é o
    caminho de rotação já implementado em `registrar_agente`.
    """

    nome: str = Field(..., min_length=2, max_length=80)
    identificador: Annotated[str, Field(max_length=64)] = ""

    @field_validator("identificador")
    @classmethod
    def _hex(cls, valor: str) -> str:
        texto = (valor or "").strip().lower()
        if not texto:
            return ""
        if not re.fullmatch(r"[0-9a-f]{16,64}", texto):
            raise ValueError(
                "Identificador de estação deve ser hexadecimal de 16 a 64 caracteres. "
                "Deixe em branco para o Cajuru28 gerar um."
            )
        return texto


class AgenteSaida(Base):
    id: int
    identificador: str
    nome: str
    hostname: str = ""
    usuario_windows: str = ""
    sistema_operacional: str = ""
    versao_agente: str = ""
    versao_navegador: str = ""
    versao_assinador: str = ""
    assinador_ok: bool = False
    assinador_detalhe: str = ""
    jobs_em_andamento: int = 0
    ativo: bool = True
    revogado_em: datetime | None = None
    revogado_motivo: str = ""
    ultimo_heartbeat_em: datetime | None = None
    criado_em: datetime | None = None
    situacao: str = "offline"
    certificados: int = 0


class AgenteCredencialSaida(Base):
    """Resposta da matrícula. O segredo aparece **uma vez** e não é recuperável."""

    agente: AgenteSaida
    segredo: str
    aviso: str = (
        "Guarde este segredo agora: ele não é exibido novamente. Para trocar, "
        "gere uma nova credencial nesta tela."
    )


# --------------------------------------------------------------------------
# Protocolo do Agent
# --------------------------------------------------------------------------


class SessaoAgentEntrada(Base):
    identificador: str
    segredo: str = Field(..., min_length=20, max_length=200)
    versao_agente: str = Field("", max_length=30)
    hostname: str = Field("", max_length=255)
    usuario_windows: str = Field("", max_length=255)
    sistema_operacional: str = Field("", max_length=120)


class SessaoAgentSaida(Base):
    jti: str
    chave_sessao: str
    expira_em: datetime
    intervalo_heartbeat_segundos: int = 60
    intervalo_busca_segundos: int = 15
    versao_minima_assinador: str = ""


class DiagnosticoAssinador(Base):
    instalado: bool = False
    em_execucao: bool = False
    hosts_mapeado: bool = False
    porta_local: bool = False
    certificado_visivel: bool = False
    permissao_navegador: bool = False
    versao: str = Field("", max_length=30)
    detalhe: str = Field("", max_length=255)


class HeartbeatEntrada(Base):
    versao_agente: str = Field("", max_length=30)
    versao_navegador: str = Field("", max_length=80)
    assinador: DiagnosticoAssinador = Field(default_factory=DiagnosticoAssinador)


class HeartbeatSaida(Base):
    reconhecido: bool = True
    assinador_apto: bool = False
    assinador_detalhe: str = ""
    jobs_disponiveis: int = 0
    intervalo_busca_segundos: int = 15
    versao_minima_assinador: str = ""
    pausado: bool = False


class CertificadoInventarioEntrada(Base):
    thumbprint: str = Field(..., min_length=40, max_length=64)
    subject: str = Field("", max_length=500)
    issuer: str = Field("", max_length=500)
    numero_serie: str = Field("", max_length=80)
    documento: str = Field("", max_length=20)
    titular_nome: str = Field("", max_length=255)
    valido_de: datetime | None = None
    valido_ate: datetime | None = None
    origem: str = Field("windows_store", max_length=20)
    referencia_local: str = Field("", max_length=128)
    tipo: Literal["cliente", "contabilidade"] = "cliente"
    senha_disponivel: bool = False

    @field_validator("thumbprint")
    @classmethod
    def _hex(cls, valor: str) -> str:
        texto = valor.strip().lower()
        if not _HEX64.fullmatch(texto):
            raise ValueError("Thumbprint deve ser hexadecimal (SHA-1 40 ou SHA-256 64).")
        return texto

    @field_validator("documento")
    @classmethod
    def _doc(cls, valor: str) -> str:
        if not valor:
            return ""
        return normalizar_documento(valor)


class InventarioEntrada(Base):
    certificados: list[CertificadoInventarioEntrada] = Field(
        default_factory=list, max_length=500
    )


class InventarioSaida(Base):
    recebidos: int = 0
    novos: int = 0
    atualizados: int = 0
    indisponiveis: int = 0
    invalidos: int = 0


class ReivindicarEntrada(Base):
    capacidade: int = Field(1, ge=1, le=5)


class OrdemDeTrabalho(Base):
    """O que o Agent recebe. Nada aqui é segredo — nem senha, nem PFX.

    O certificado é referenciado por `thumbprint` e por uma referência local
    opaca que só a própria estação sabe resolver.
    """

    job_id: int
    lease_token: str
    lease_ate: datetime
    fase: str
    etapa: str
    modo: str
    status: str
    empresa_documento: str
    empresa_nome: str
    outorgado_documento: str
    outorgado_nome: str
    vigencia_ate: date | None = None
    escopo_servicos: str = "ALL"
    servicos: list[dict[str, str]] = Field(default_factory=list)
    certificado_thumbprint: str = ""
    certificado_referencia: str = ""
    certificado_documento: str = ""
    certificado_titular: str = ""
    certificado_tipo: str = "cliente"
    url_portal: str = ""
    roteiro: list[dict[str, Any]] = Field(default_factory=list)
    timeout_etapa_segundos: int = 900
    intervalo_heartbeat_segundos: int = 60


class ReivindicarSaida(Base):
    ordens: list[OrdemDeTrabalho] = Field(default_factory=list)
    intervalo_busca_segundos: int = 15


class ProgressoEntrada(Base):
    """Relato de avanço vindo da estação.

    Repare no que **não** existe aqui: um campo `status`. A estação informa a
    etapa do roteiro em que está; o estado do job é derivado no servidor por
    `ESTADO_DA_ETAPA`. Se a estação pudesse declarar o status, poderia pular
    de "atribuído" para "assinado" sem passar pela assinatura — e a máquina de
    estados viraria decoração.
    """

    lease_token: str = Field(..., min_length=8, max_length=64)
    etapa: str = Field(..., max_length=40)
    mensagem: str = Field("", max_length=1000)
    detalhe: dict[str, Any] = Field(default_factory=dict)


class ResultadoEntrada(Base):
    """Fechamento de uma fase — só com evidência do que aconteceu de fato."""

    lease_token: str = Field(..., min_length=8, max_length=64)
    resultado: Literal["outorga_registrada", "aceite_registrado", "falha", "intervencao"]
    protocolo: str = Field("", max_length=120)
    situacao_observada: str = Field("", max_length=60)
    vigencia_ate: date | None = None
    codigo_erro: str = Field("", max_length=60)
    mensagem: str = Field("", max_length=1000)
    confirmacao_portal: str = Field("", max_length=500)

    @model_validator(mode="after")
    def _exige_confirmacao(self):
        if self.resultado in {"outorga_registrada", "aceite_registrado"}:
            if not (self.protocolo or self.confirmacao_portal):
                raise ValueError(
                    "Conclusão sem confirmação do portal não é aceita: informe o "
                    "protocolo ou o texto de confirmação exibido na tela."
                )
        if self.resultado == "falha" and not self.codigo_erro:
            raise ValueError("Falha exige um código de erro do catálogo.")
        return self


class ErroSaida(Base):
    codigo: str
    mensagem: str


class NotificacaoSaida(Base):
    id: int
    tipo: str
    nivel: str
    titulo: str
    detalhe: str = ""
    empresa_id: int | None = None
    job_id: int | None = None
    criado_em: datetime | None = None
    reconhecida_em: datetime | None = None


class SituacaoOpcao(Base):
    valor: str
    rotulo: str


def situacoes_disponiveis() -> list[SituacaoOpcao]:
    rotulos = {
        StatusAutorizacao.SEM_AUTORIZACAO: "Sem autorização",
        StatusAutorizacao.EM_ANALISE: "Em análise",
        StatusAutorizacao.AGUARDANDO_ACEITE: "Aguardando aceite",
        StatusAutorizacao.ATIVA: "Ativa",
        StatusAutorizacao.EXPIRADA: "Expirada",
        StatusAutorizacao.CANCELADA: "Cancelada",
        StatusAutorizacao.REJEITADA: "Rejeitada",
        StatusAutorizacao.ERRO: "Erro",
        StatusAutorizacao.INTERVENCAO_MANUAL: "Intervenção manual",
    }
    return [SituacaoOpcao(valor=chave.value, rotulo=valor) for chave, valor in rotulos.items()]


JobDetalheSaida.model_rebuild()
