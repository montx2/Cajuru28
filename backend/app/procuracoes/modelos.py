"""
Persistência do módulo Procurações RFB.

Três decisões de schema que valem explicação:

1. **Status como `String`, não `Enum` nativo do PostgreSQL.** O projeto já
   documentou (em `app/db/migracoes.py`) a dor de `ALTER TYPE ... ADD VALUE`
   para evoluir enum nativo. Este módulo vai ganhar estados novos conforme o
   portal evolui; texto com validação no domínio (`app.procuracoes.estados`)
   custa um índice e evita migração destrutiva.

2. **Nada de material secreto aqui.** Não existe coluna de senha de
   certificado, PFX, cookie de sessão ou token do portal. O inventário de
   certificados guarda apenas metadados públicos do X.509 (subject, issuer,
   serial, thumbprint, validade) e uma *referência opaca* que só a estação
   sabe resolver. Ver `docs/PROCURACOES_SEGURANCA.md`.

3. **`escritorio_id` em tudo que é raiz de agregado**, seguindo o padrão do
   projeto: o isolamento por tenant é do schema, não do endpoint.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.procuracoes.estados import (
    ModoOperacao,
    StatusAutorizacao,
    StatusJob,
    TipoCertificado,
)

# Tamanho máximo de um identificador fiscal canônico (CNPJ alfanumérico).
_TAM_DOC = 14


class ProcuracaoConfiguracao(Base):
    """Configuração do módulo, uma linha por escritório.

    Nada aqui é constante de código: vigência, serviços, retries, timeouts,
    janelas e limites de concorrência são operacionais e mudam sem deploy.
    """

    __tablename__ = "procuracao_configuracoes"
    __table_args__ = (
        UniqueConstraint("escritorio_id", name="uq_procuracao_config_escritorio"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)

    # --- identidade da contabilidade (o outorgado) -------------------------
    outorgado_documento: Mapped[str] = mapped_column(String(_TAM_DOC), default="")
    outorgado_nome: Mapped[str] = mapped_column(String(255), default="")

    # --- automação ---------------------------------------------------------
    modo_padrao: Mapped[str] = mapped_column(
        String(20), default=ModoOperacao.ASSISTIDO.value
    )
    # Ligado = o agendador monta fila e distribui sozinho. A execução do ato
    # continua assistida; o que o agendador automatiza é o preparo.
    processamento_automatico: Mapped[bool] = mapped_column(Boolean, default=False)
    sincronizacao_automatica: Mapped[bool] = mapped_column(Boolean, default=True)
    hora_sincronizacao: Mapped[int] = mapped_column(Integer, default=6)
    intervalo_entre_jobs_segundos: Mapped[int] = mapped_column(Integer, default=30)
    max_jobs_simultaneos: Mapped[int] = mapped_column(Integer, default=2)
    max_jobs_por_agente: Mapped[int] = mapped_column(Integer, default=1)
    max_tentativas: Mapped[int] = mapped_column(Integer, default=3)
    timeout_etapa_segundos: Mapped[int] = mapped_column(Integer, default=900)
    timeout_job_segundos: Mapped[int] = mapped_column(Integer, default=5400)
    # Segundos sem heartbeat para considerar a estação offline.
    heartbeat_tolerancia_segundos: Mapped[int] = mapped_column(Integer, default=120)

    # --- alertas de vencimento --------------------------------------------
    alerta_dias: Mapped[str] = mapped_column(String(60), default="30,60,90")

    # --- Assinador SERPRO ---------------------------------------------------
    assinador_versao_minima: Mapped[str] = mapped_column(String(20), default="4.0.0")
    assinador_exigido: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- conformidade -------------------------------------------------------
    # Só um administrador liga, e só com documento formal da RFB registrado.
    autorizacao_formal_rfb: Mapped[bool] = mapped_column(Boolean, default=False)
    autorizacao_formal_referencia: Mapped[str] = mapped_column(String(500), default="")

    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def alerta_dias_lista(self) -> list[int]:
        valores: list[int] = []
        for parte in (self.alerta_dias or "").split(","):
            parte = parte.strip()
            if parte.isdigit():
                valores.append(int(parte))
        return sorted(set(valores)) or [30, 60, 90]


class ModeloAutorizacao(Base):
    """Template de autorização: vigência e serviços padrão do escritório.

    Existe para que "Vigência 5 anos / Serviços: Todos" seja um dado editável
    na tela, não uma constante enterrada no código — e para que uma empresa
    específica possa fugir do padrão sem fork de lógica.
    """

    __tablename__ = "procuracao_modelos"
    __table_args__ = (
        UniqueConstraint("escritorio_id", "nome", name="uq_procuracao_modelo_nome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    descricao: Mapped[str] = mapped_column(String(500), default="")
    vigencia_meses: Mapped[int] = mapped_column(Integer, default=60)
    # "ALL" = marcar todos os serviços na tela da Receita. Caso contrário, a
    # lista explícita fica em `ModeloAutorizacaoServico`.
    escopo_servicos: Mapped[str] = mapped_column(String(10), default="ALL")
    padrao: Mapped[bool] = mapped_column(Boolean, default=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    servicos: Mapped[list["ModeloAutorizacaoServico"]] = relationship(
        back_populates="modelo", cascade="all, delete-orphan"
    )


class ModeloAutorizacaoServico(Base):
    """Serviço marcado quando o escopo do modelo não é `ALL`."""

    __tablename__ = "procuracao_modelo_servicos"
    __table_args__ = (
        UniqueConstraint("modelo_id", "codigo", name="uq_modelo_servico_codigo"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    modelo_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_modelos.id", ondelete="CASCADE"), index=True
    )
    # Rótulo tal como aparece no portal. Não inventamos códigos internos: o
    # operador confere contra a tela da Receita.
    codigo: Mapped[str] = mapped_column(String(120))
    rotulo: Mapped[str] = mapped_column(String(255), default="")
    ordem: Mapped[int] = mapped_column(Integer, default=0)

    modelo: Mapped["ModeloAutorizacao"] = relationship(back_populates="servicos")


class Agente(Base):
    """Estação Windows habilitada a operar (o Cajuru Agent).

    O segredo do Agent **não** fica aqui em claro: `segredo_hash` é um hash
    Argon2id do token de enrolamento, igual ao tratamento de senha de usuário.
    """

    __tablename__ = "procuracao_agentes"
    __table_args__ = (
        UniqueConstraint("escritorio_id", "identificador", name="uq_agente_identificador"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    # Identificador estável da máquina, calculado pelo Agent (ver docs).
    identificador: Mapped[str] = mapped_column(String(64), index=True)
    nome: Mapped[str] = mapped_column(String(80))
    hostname: Mapped[str] = mapped_column(String(255), default="")
    usuario_windows: Mapped[str] = mapped_column(String(255), default="")
    sistema_operacional: Mapped[str] = mapped_column(String(120), default="")
    versao_agente: Mapped[str] = mapped_column(String(30), default="")
    versao_navegador: Mapped[str] = mapped_column(String(80), default="")
    versao_assinador: Mapped[str] = mapped_column(String(30), default="")

    segredo_hash: Mapped[str] = mapped_column(Text)
    # Incrementada ao revogar/rotacionar: invalida credenciais antigas sem
    # guardar lista de tokens.
    versao_credencial: Mapped[int] = mapped_column(Integer, default=1)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    revogado_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revogado_motivo: Mapped[str] = mapped_column(String(255), default="")

    ultimo_heartbeat_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    assinador_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    assinador_detalhe: Mapped[str] = mapped_column(String(255), default="")
    #: Códigos de pendência separados por vírgula (ex.: "em_execucao,porta_local").
    #: Guardar o código, e não só a frase, deixa a tela agrupar e o Agent
    #: mostrar exatamente qual passo da instalação falta.
    assinador_pendencias: Mapped[str] = mapped_column(String(255), default="")
    jobs_em_andamento: Mapped[int] = mapped_column(Integer, default=0)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    sessoes: Mapped[list["AgenteSessao"]] = relationship(
        back_populates="agente", cascade="all, delete-orphan"
    )


class AgenteSessao(Base):
    """Sessão autenticada de um Agent (token de acesso de curta duração).

    Guardamos só o hash do token e o `jti`; revogar é apagar a linha.
    """

    __tablename__ = "procuracao_agente_sessoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agente_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_agentes.id", ondelete="CASCADE"), index=True
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    endereco_origem: Mapped[str] = mapped_column(String(64), default="")
    encerrada_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    agente: Mapped["Agente"] = relationship(back_populates="sessoes")


class AgenteNonce(Base):
    """Anti-replay: cada requisição assinada do Agent traz um nonce único.

    A linha vive apenas a janela de tolerância do relógio; a limpeza é feita
    pela tarefa periódica `procuracoes_manutencao`.
    """

    __tablename__ = "procuracao_agente_nonces"
    __table_args__ = (
        UniqueConstraint("agente_id", "nonce", name="uq_agente_nonce"),
        Index("ix_agente_nonce_expira", "expira_em"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agente_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_agentes.id", ondelete="CASCADE"), index=True
    )
    nonce: Mapped[str] = mapped_column(String(64))
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CertificadoInventario(Base):
    """Certificado A1 **visto** por uma estação — metadados, nunca a chave.

    Este não é o cadastro de certificados do módulo fiscal (`certificados`,
    com PFX cifrado no servidor): é o inventário do que existe *na máquina*
    que vai conduzir a operação no portal. A chave privada nunca sai de lá.
    """

    __tablename__ = "procuracao_certificados_inventario"
    __table_args__ = (
        UniqueConstraint(
            "agente_id", "thumbprint", name="uq_certificado_inventario_thumbprint"
        ),
        Index("ix_certificado_inventario_documento", "escritorio_id", "documento"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    agente_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_agentes.id", ondelete="CASCADE"), index=True
    )
    empresa_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("empresas.id"), nullable=True, index=True
    )

    # SHA-256 do DER do certificado — identificador global e não sensível.
    thumbprint: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(500), default="")
    issuer: Mapped[str] = mapped_column(String(500), default="")
    numero_serie: Mapped[str] = mapped_column(String(80), default="")
    documento: Mapped[str] = mapped_column(String(_TAM_DOC), default="", index=True)
    titular_nome: Mapped[str] = mapped_column(String(255), default="")
    valido_de: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valido_ate: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # "windows_store" | "arquivo"
    origem: Mapped[str] = mapped_column(String(20), default="windows_store")
    # Handle opaco resolvido apenas pela estação. Não é caminho de arquivo:
    # o servidor jamais deve conseguir apontar para um arquivo arbitrário.
    referencia_local: Mapped[str] = mapped_column(String(128), default="")
    tipo: Mapped[str] = mapped_column(String(20), default=TipoCertificado.CLIENTE.value)
    # "disponivel" | "expirado" | "sem_chave_privada" | "indisponivel"
    situacao: Mapped[str] = mapped_column(String(30), default="disponivel")
    senha_disponivel: Mapped[bool] = mapped_column(Boolean, default=False)
    ultima_validacao_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultimo_erro: Mapped[str] = mapped_column(String(255), default="")
    visto_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agente: Mapped["Agente"] = relationship()


class Autorizacao(Base):
    """Autorização de Acesso de uma empresa para a contabilidade.

    Uma linha por par (empresa, outorgado). O histórico de mudanças vive em
    `AutorizacaoEvento`; esta tabela carrega o estado corrente.
    """

    __tablename__ = "procuracao_autorizacoes"
    __table_args__ = (
        UniqueConstraint(
            "escritorio_id",
            "empresa_id",
            "outorgado_documento",
            name="uq_autorizacao_empresa_outorgado",
        ),
        Index("ix_autorizacao_situacao", "escritorio_id", "situacao"),
        Index("ix_autorizacao_validade", "escritorio_id", "data_validade"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)

    outorgante_documento: Mapped[str] = mapped_column(String(_TAM_DOC))
    outorgante_nome: Mapped[str] = mapped_column(String(255), default="")
    outorgado_documento: Mapped[str] = mapped_column(String(_TAM_DOC))
    outorgado_nome: Mapped[str] = mapped_column(String(255), default="")

    situacao: Mapped[str] = mapped_column(
        String(30), default=StatusAutorizacao.SEM_AUTORIZACAO.value, index=True
    )
    data_inicio: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    data_validade: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Prazo de 30 dias para a contabilidade validar. Calculado na outorga.
    prazo_aceite_ate: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    escopo_servicos: Mapped[str] = mapped_column(String(10), default="ALL")
    # Protocolo/identificador que o portal exibir, quando houver. Nunca é
    # inventado: só entra quando alguém o confirma ou a API oficial o devolve.
    protocolo: Mapped[str] = mapped_column(String(120), default="")

    origem_dado: Mapped[str] = mapped_column(String(30), default="manual")
    sincronizado_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmado_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultimo_erro: Mapped[str] = mapped_column(String(500), default="")
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    permissoes: Mapped[list["AutorizacaoPermissao"]] = relationship(
        back_populates="autorizacao", cascade="all, delete-orphan"
    )


class AutorizacaoPermissao(Base):
    """Serviço efetivamente autorizado, como consta no portal/API oficial."""

    __tablename__ = "procuracao_autorizacao_permissoes"
    __table_args__ = (
        UniqueConstraint(
            "autorizacao_id", "codigo", name="uq_autorizacao_permissao_codigo"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    autorizacao_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_autorizacoes.id", ondelete="CASCADE"), index=True
    )
    codigo: Mapped[str] = mapped_column(String(120))
    rotulo: Mapped[str] = mapped_column(String(255), default="")
    expira_em: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    origem: Mapped[str] = mapped_column(String(30), default="sincronizacao")

    autorizacao: Mapped["Autorizacao"] = relationship(back_populates="permissoes")


class JobProcuracao(Base):
    """Unidade de trabalho da fila operacional.

    Um job por empresa por ciclo. A `chave_idempotencia` é o que impede que
    dois cliques em "Processar pendências" criem duas outorgas.
    """

    __tablename__ = "procuracao_jobs"
    __table_args__ = (
        UniqueConstraint(
            "escritorio_id", "chave_idempotencia", name="uq_job_chave_idempotencia"
        ),
        Index("ix_job_status", "escritorio_id", "status"),
        Index("ix_job_empresa_status", "empresa_id", "status"),
        Index("ix_job_agente", "agente_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    autorizacao_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("procuracao_autorizacoes.id"), nullable=True, index=True
    )
    modelo_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("procuracao_modelos.id"), nullable=True
    )

    chave_idempotencia: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(
        String(40), default=StatusJob.PENDENTE.value, index=True
    )
    fase: Mapped[str] = mapped_column(String(20), default="outorga")
    etapa_atual: Mapped[str] = mapped_column(String(40), default="pre_requisitos")
    modo: Mapped[str] = mapped_column(String(20), default=ModoOperacao.ASSISTIDO.value)
    prioridade: Mapped[int] = mapped_column(Integer, default=100, index=True)

    # --- atribuição / lock distribuído -------------------------------------
    agente_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("procuracao_agentes.id"), nullable=True, index=True
    )
    # Lease: expira sozinho se o Agent sumir. Sem isso, uma estação que cai
    # deixa a empresa travada para sempre.
    lease_ate: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    lease_token: Mapped[str] = mapped_column(String(64), default="")

    # --- dados congelados no momento da criação ----------------------------
    # Congelar evita que mudar o template no meio do caminho altere o que já
    # está sendo assinado.
    outorgado_documento: Mapped[str] = mapped_column(String(_TAM_DOC), default="")
    outorgado_nome: Mapped[str] = mapped_column(String(255), default="")
    vigencia_ate: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    escopo_servicos: Mapped[str] = mapped_column(String(10), default="ALL")
    servicos_json: Mapped[str] = mapped_column(Text, default="[]")

    certificado_thumbprint: Mapped[str] = mapped_column(String(64), default="")
    certificado_inventario_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("procuracao_certificados_inventario.id"), nullable=True
    )

    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    proxima_tentativa_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    codigo_erro: Mapped[str] = mapped_column(String(60), default="")
    classe_erro: Mapped[str] = mapped_column(String(30), default="")
    mensagem_erro: Mapped[str] = mapped_column(Text, default="")
    motivo_intervencao: Mapped[str] = mapped_column(Text, default="")

    protocolo: Mapped[str] = mapped_column(String(120), default="")

    criado_por_usuario_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True
    )
    origem: Mapped[str] = mapped_column(String(20), default="manual")
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    iniciado_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalizado_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    eventos: Mapped[list["JobEvento"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobEvento(Base):
    """Evento imutável do job. Toda mudança de status gera um.

    Não há endpoint de exclusão: a trilha só cresce. A limpeza, quando for
    necessária, é procedimento documentado de retenção, não botão de tela.
    """

    __tablename__ = "procuracao_job_eventos"
    __table_args__ = (Index("ix_job_evento_job_quando", "job_id", "quando"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_jobs.id", ondelete="CASCADE"), index=True
    )
    quando: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    status_anterior: Mapped[str] = mapped_column(String(40), default="")
    status_novo: Mapped[str] = mapped_column(String(40), default="")
    etapa: Mapped[str] = mapped_column(String(40), default="")
    mensagem: Mapped[str] = mapped_column(Text, default="")
    codigo_erro: Mapped[str] = mapped_column(String(60), default="")
    # Quem provocou: "operador:<id>", "agente:<id>", "agendador", "sistema".
    ator: Mapped[str] = mapped_column(String(60), default="sistema")
    agente_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("procuracao_agentes.id"), nullable=True
    )
    usuario_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True
    )
    # Contexto técnico já sanitizado (URL, versões, seletor que falhou).
    detalhe_json: Mapped[str] = mapped_column(Text, default="{}")

    job: Mapped["JobProcuracao"] = relationship(back_populates="eventos")


class JobEvidencia(Base):
    """Evidência de execução (captura de tela, HTML reduzido, log de etapa).

    O binário não vai para o banco: fica no volume de dados, cifrado com a
    mesma chave do cofre, e aqui guardamos só o ponteiro e o hash.
    """

    __tablename__ = "procuracao_job_evidencias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_jobs.id", ondelete="CASCADE"), index=True
    )
    etapa: Mapped[str] = mapped_column(String(40), default="")
    tipo: Mapped[str] = mapped_column(String(20), default="screenshot")
    # Caminho relativo dentro de DADOS_DIR/procuracoes — validado contra
    # traversal na gravação e na leitura.
    caminho_relativo: Mapped[str] = mapped_column(String(300))
    sha256: Mapped[str] = mapped_column(String(64), default="")
    tamanho_bytes: Mapped[int] = mapped_column(Integer, default=0)
    url_observada: Mapped[str] = mapped_column(String(500), default="")
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SessaoNavegador(Base):
    """Sessão de navegador conduzida por uma estação, para um job.

    Guarda metadados operacionais (quando abriu, qual navegador, qual URL de
    partida). **Nunca** cookies, tokens ou conteúdo de sessão do portal.
    """

    __tablename__ = "procuracao_sessoes_navegador"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_jobs.id", ondelete="CASCADE"), index=True
    )
    agente_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_agentes.id"), index=True
    )
    navegador: Mapped[str] = mapped_column(String(40), default="")
    versao: Mapped[str] = mapped_column(String(40), default="")
    perfil: Mapped[str] = mapped_column(String(120), default="")
    url_inicial: Mapped[str] = mapped_column(String(500), default="")
    identidade: Mapped[str] = mapped_column(String(20), default="cliente")
    aberta_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    encerrada_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resultado: Mapped[str] = mapped_column(String(40), default="")


class IntegracaoJob(Base):
    """Execução de uma sincronização com fonte externa (Jettax, SERPRO…)."""

    __tablename__ = "procuracao_integracao_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    fonte: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="em_andamento", index=True)
    origem: Mapped[str] = mapped_column(String(20), default="manual")
    registros_recebidos: Mapped[int] = mapped_column(Integer, default=0)
    registros_criados: Mapped[int] = mapped_column(Integer, default=0)
    registros_atualizados: Mapped[int] = mapped_column(Integer, default=0)
    registros_ignorados: Mapped[int] = mapped_column(Integer, default=0)
    registros_invalidos: Mapped[int] = mapped_column(Integer, default=0)
    mensagem: Mapped[str] = mapped_column(Text, default="")
    iniciado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finalizado_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    erros: Mapped[list["IntegracaoErro"]] = relationship(
        back_populates="integracao_job", cascade="all, delete-orphan"
    )


class IntegracaoErro(Base):
    """Linha que a sincronização não conseguiu aproveitar, com o porquê."""

    __tablename__ = "procuracao_integracao_erros"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    integracao_job_id: Mapped[int] = mapped_column(
        ForeignKey("procuracao_integracao_jobs.id", ondelete="CASCADE"), index=True
    )
    documento: Mapped[str] = mapped_column(String(30), default="")
    #: Nome como a fonte o escreveu. Sem ele, uma pendência é só um CNPJ solto:
    #: o operador precisa saber *de quem* é o documento para decidir se cadastra
    #: a empresa ou se aquela linha não é cliente do escritório.
    nome: Mapped[str] = mapped_column(String(255), default="", server_default="")
    codigo: Mapped[str] = mapped_column(String(60), default="")
    mensagem: Mapped[str] = mapped_column(Text, default="")
    quando: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    integracao_job: Mapped["IntegracaoJob"] = relationship(back_populates="erros")


class CredencialIntegracao(Base):
    """Credencial de uma fonte externa, cifrada pelo cofre Fernet do projeto.

    Guardamos o segredo cifrado e **nunca** o devolvemos por API: a resposta
    diz apenas se está configurado e quando foi usado pela última vez.
    """

    __tablename__ = "procuracao_credenciais_integracao"
    __table_args__ = (
        UniqueConstraint("escritorio_id", "fonte", name="uq_credencial_integracao_fonte"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    fonte: Mapped[str] = mapped_column(String(40), index=True)
    base_url: Mapped[str] = mapped_column(String(500), default="")
    identificador: Mapped[str] = mapped_column(String(255), default="")
    segredo_cifrado: Mapped[str] = mapped_column(Text, default="")
    segredo_extra_cifrado: Mapped[str] = mapped_column(Text, default="")
    # Ajustes específicos do adaptador em JSON (rotas, mapeamento de campos).
    opcoes_json: Mapped[str] = mapped_column(Text, default="{}")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    ultima_utilizacao_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultimo_erro: Mapped[str] = mapped_column(String(500), default="")
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NotificacaoProcuracao(Base):
    """Notificação interna. Some quando o operador reconhece."""

    __tablename__ = "procuracao_notificacoes"
    __table_args__ = (
        UniqueConstraint("escritorio_id", "chave", name="uq_notificacao_chave"),
        Index("ix_notificacao_pendente", "escritorio_id", "reconhecida_em"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    # Chave estável (ex.: "certificado_expirando:<thumbprint>:30") — é o que
    # impede a mesma notificação de virar 400 linhas iguais.
    chave: Mapped[str] = mapped_column(String(160))
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    nivel: Mapped[str] = mapped_column(String(20), default="info")
    titulo: Mapped[str] = mapped_column(String(160))
    detalhe: Mapped[str] = mapped_column(Text, default="")
    empresa_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("empresas.id"), nullable=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("procuracao_jobs.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    reconhecida_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reconhecida_por: Mapped[Optional[int]] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True
    )


__all__ = [
    "Agente",
    "AgenteNonce",
    "AgenteSessao",
    "Autorizacao",
    "AutorizacaoPermissao",
    "CertificadoInventario",
    "CredencialIntegracao",
    "IntegracaoErro",
    "IntegracaoJob",
    "JobEvento",
    "JobEvidencia",
    "JobProcuracao",
    "ModeloAutorizacao",
    "ModeloAutorizacaoServico",
    "NotificacaoProcuracao",
    "ProcuracaoConfiguracao",
    "SessaoNavegador",
]
