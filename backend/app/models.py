"""
Modelos do banco.

Toda tabela carrega `escritorio_id`. Hoje só existe um escritório — o seu —
mas o isolamento por tenant já está no schema desde a Fase 0, então virar
multiempresa depois é ligar uma trava de acesso, não migrar dado.
"""

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Escritorio(Base):
    """O tenant. Hoje só existe uma linha aqui."""

    __tablename__ = "escritorios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(255))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="escritorio")
    empresas: Mapped[list["Empresa"]] = relationship(back_populates="escritorio")


class AcessoriasCredencial(Base):
    """Token da API Acessórias, isolado por escritório e cifrado no cofre."""

    __tablename__ = "acessorias_credenciais"
    __table_args__ = (UniqueConstraint("escritorio_id", name="uq_acessorias_credencial_escritorio"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    base_url: Mapped[str] = mapped_column(String(500), default="https://api.acessorias.com")
    token_cifrado: Mapped[str] = mapped_column(Text)
    ultima_sincronizacao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JettaxCredencial(Base):
    """Credencial Jettax do escritório, cifrada pelo mesmo cofre dos A1."""

    __tablename__ = "jettax_credenciais"
    __table_args__ = (UniqueConstraint("escritorio_id", name="uq_jettax_credencial_escritorio"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    base_url: Mapped[str] = mapped_column(String(500))
    token_cifrado: Mapped[str] = mapped_column(Text)
    # Formato do header Authorization que esta instância Morfeu aceitou
    # ("puro" ou "bearer"). Guardado para não repetir a descoberta — e o 401
    # extra que ela custa — a cada chamada do conector.
    esquema_autenticacao: Mapped[str] = mapped_column(String(10), default="puro", server_default="puro")
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Usuario(Base):
    """Pessoa do escritório que acessa o sistema (login)."""

    __tablename__ = "usuarios"
    __table_args__ = (UniqueConstraint("escritorio_id", "email", name="uq_usuario_email_por_escritorio"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"))
    nome: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    # Papel: admin (tudo + equipe) | operador (opera, não gerencia usuários)
    # | leitura (só vê e baixa). Usuários antigos assumem admin na migração.
    papel: Mapped[str] = mapped_column(String(20), default="admin")
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Incrementada ao trocar senha, desligar o usuário ou realizar logout.
    # O JWT carrega esta versão, então sessões antigas deixam de valer sem
    # armazenar o token inteiro no banco.
    versao_sessao: Mapped[int] = mapped_column(Integer, default=1)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    escritorio: Mapped["Escritorio"] = relationship(back_populates="usuarios")


class Empresa(Base):
    """Empresa cliente do escritório — de quem as notas são importadas."""

    __tablename__ = "empresas"
    __table_args__ = (UniqueConstraint("escritorio_id", "cnpj_cpf", name="uq_empresa_documento_por_escritorio"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"))
    razao_social: Mapped[str] = mapped_column(String(255))
    cnpj_cpf: Mapped[str] = mapped_column(String(14), index=True)
    uf: Mapped[str] = mapped_column(String(2))  # necessário para o cUFAutor da consulta ao SEFAZ (NFe/CT-e)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)
    # Sincronização automática (Celery Beat). Com "sim", o sistema entra
    # sozinho no ADN/SEFAZ respeitando as janelas de consumo — nenhum clique.
    sincronizar_automaticamente: Mapped[bool] = mapped_column(Boolean, default=True)
    quais_tipos_sincronizar: Mapped[str] = mapped_column(String(30), default="nfse,nfe,cte")
    # Dados municipais usados apenas pela integração Jettax/Morfeu. Permanecem
    # opcionais porque a empresa também pode operar somente pela distribuição
    # direta ADN/SEFAZ, que não depende deles.
    codigo_ibge: Mapped[str | None] = mapped_column(String(7), nullable=True)
    inscricao_municipal: Mapped[str | None] = mapped_column(String(100), nullable=True)

    sincronizacoes: Mapped[list["SincronizacaoDFe"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    jettax_configuracao: Mapped[Optional["JettaxConfiguracaoEmpresa"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan", uselist=False
    )
    jettax_execucoes: Mapped[list["JettaxExecucao"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    escritorio: Mapped["Escritorio"] = relationship(back_populates="empresas")
    certificados: Mapped[list["Certificado"]] = relationship(back_populates="empresa")
    documentos: Mapped[list["DocumentoFiscal"]] = relationship(back_populates="empresa")


class Certificado(Base):
    """
    Certificado A1 de uma empresa. A senha NUNCA fica aqui em texto puro —
    `senha_cifrada` é o resultado de app.core.vault.cifrar_segredo().

    Os campos `ultima_utilizacao_em` / `ultimo_erro` alimentam o centro de
    certificados: é o que diferencia "vence em 20 dias" de "vence em 20 dias
    E não autentica desde terça" — o operador só precisa olhar o segundo.
    """

    __tablename__ = "certificados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"))
    arquivo_path: Mapped[str] = mapped_column(String(500))  # caminho do .pfx no volume
    senha_cifrada: Mapped[str] = mapped_column(Text)
    validade: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Telemetria de uso — atualizada pelo worker a cada varredura.
    ultima_utilizacao_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultima_validacao_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultimo_erro: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped["Empresa"] = relationship(back_populates="certificados")


class TipoDocumentoFiscal(str, enum.Enum):
    NFSE = "nfse"
    NFE = "nfe"
    CTE = "cte"


class DirecaoDocumento(str, enum.Enum):
    TOMADA = "tomada"      # nota recebida (a empresa é tomadora/destinatária)
    PRESTADA = "prestada"  # nota emitida (a empresa é prestadora/emitente)


class StatusDocumentoFiscal(str, enum.Enum):
    NORMAL = "normal"
    CANCELADA = "cancelada"


class DocumentoFiscal(Base):
    """Uma nota importada — NFS-e, NFe ou CT-e.

    A nota continua existindo mesmo quando cancelada: o status é aplicado
    pelo evento de cancelamento (que pode chegar antes ou depois da nota),
    e o painel continua exibindo o documento com a marcação.
    """

    __tablename__ = "documentos_fiscais"
    __table_args__ = (UniqueConstraint("empresa_id", "chave_acesso", name="uq_documento_por_empresa"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"))
    tipo: Mapped[TipoDocumentoFiscal] = mapped_column(Enum(TipoDocumentoFiscal))
    direcao: Mapped[DirecaoDocumento] = mapped_column(Enum(DirecaoDocumento))
    chave_acesso: Mapped[str] = mapped_column(String(60), index=True)
    nsu: Mapped[str] = mapped_column(String(20), index=True)
    data_emissao: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Competência ("mês do documento"). É isto que o contador pede quando diz
    # "me dá as notas de 08/2026" — a distribuição oficial não aceita filtro de
    # data, então guardamos a competência de tudo que chega e filtramos aqui:
    # trocar de mês passa a custar zero consultas à SEFAZ.
    competencia: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    valor_total: Mapped[float] = mapped_column()
    xml_path: Mapped[str] = mapped_column(String(500))
    # "completo" = XML inteiro; "resumo" = só o resNFe/resCTe (a SEFAZ libera o
    # XML completo do destinatário após manifestação — dá para buscar pela
    # chave, e o botão "completar XML" faz isso respeitando a cota de 20/h).
    leiaute: Mapped[str] = mapped_column(String(12), default="completo")
    numero: Mapped[str | None] = mapped_column(String(20), nullable=True)
    serie: Mapped[str | None] = mapped_column(String(10), nullable=True)
    emitente_documento: Mapped[str | None] = mapped_column(String(18), nullable=True)
    emitente_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    destinatario_documento: Mapped[str | None] = mapped_column(String(18), nullable=True)
    destinatario_nome: Mapped[str | None] = mapped_column(String(255), nullable=True)
    situacao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origem: Mapped[str | None] = mapped_column(String(20), nullable=True)  # adn/sefaz/distDFe...
    status: Mapped[StatusDocumentoFiscal] = mapped_column(
        Enum(StatusDocumentoFiscal), default=StatusDocumentoFiscal.NORMAL
    )
    motivo_cancelamento: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    importado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped["Empresa"] = relationship(back_populates="documentos")
    fontes: Mapped[list["DocumentoFiscalFonte"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan"
    )


class DocumentoFiscalFonte(Base):
    """Proveniência de uma nota sem duplicar a identidade fiscal dela.

    A mesma chave pode chegar pela distribuição oficial e pela Jettax. A nota
    continua única em `documentos_fiscais`; esta tabela preserva todas as
    fontes que a confirmaram, sem trocar silenciosamente o XML já arquivado.
    """

    __tablename__ = "documentos_fiscais_fontes"
    __table_args__ = (
        UniqueConstraint(
            "documento_id", "origem", "identificador_externo",
            name="uq_documento_fonte_identificador",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey("documentos_fiscais.id"), index=True)
    origem: Mapped[str] = mapped_column(String(30))
    identificador_externo: Mapped[str] = mapped_column(String(100), default="")
    registrado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    documento: Mapped["DocumentoFiscal"] = relationship(back_populates="fontes")


class StatusExecucao(str, enum.Enum):
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDA = "concluida"
    ERRO = "erro"
    # A SEFAZ/ADN bloqueou o CNPJ por consumo indevido (cStat 656) e a própria
    # regra oficial manda esperar 1 hora. Não é erro: o sistema reagendou a
    # continuação sozinho e o checkpoint de NSU está intacto.
    AGUARDANDO = "aguardando"


class ExecucaoImportacao(Base):
    """Histórico de cada rodada de importação — o que rodou, quando, com que resultado."""

    __tablename__ = "execucoes_importacao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"))
    tipo: Mapped[TipoDocumentoFiscal] = mapped_column(Enum(TipoDocumentoFiscal))
    status: Mapped[StatusExecucao] = mapped_column(Enum(StatusExecucao), default=StatusExecucao.EM_ANDAMENTO)
    documentos_importados: Mapped[int] = mapped_column(Integer, default=0)
    documentos_cancelados: Mapped[int] = mapped_column(Integer, default=0)
    eventos_nao_reconhecidos: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_nsu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Período pedido pelo operador (ex.: 01/08/2026 a 31/08/2026). É um filtro
    # de verdade: a varredura na origem continua por NSU, mas só as notas
    # emitidas dentro deste intervalo são gravadas — o que vem de fora é
    # descartado e contado em `documentos_fora_do_periodo`, para a execução
    # conseguir provar o que deixou de fora.
    data_inicio: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    data_fim: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    documentos_no_periodo: Mapped[int] = mapped_column(Integer, default=0)
    documentos_fora_do_periodo: Mapped[int] = mapped_column(Integer, default=0)
    # Controle do "quase 100% automático": quantas rodadas esta execução já
    # dormiu esperando a janela de consumo da SEFAZ abrir.
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    origem: Mapped[str] = mapped_column(String(20), default="manual")  # manual | lote | agendador
    # Pulou a janela de consumo por ordem explícita do operador. Fica registrado
    # para a tela conseguir explicar um 656 logo em seguida ("você forçou").
    forcar: Mapped[bool] = mapped_column(Boolean, default=False)
    mensagem_erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    aviso: Mapped[str | None] = mapped_column(Text, nullable=True)
    iniciado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    empresa: Mapped["Empresa"] = relationship()


class SincronizacaoDFe(Base):
    """
    Estado de sincronização de uma empresa+tipo — a peça que faltava.

    Antes, cursor e "quando posso consultar de novo" viviam espalhados no
    histórico de execuções. Com o bloqueio por consumo indevido (cStat 656)
    isso virou frágil: um re-tento cedo demais zera o cronômetro da SEFAZ e o
    CNPJ fica preso em loop. Aqui mora a verdade única:

    - `ultimo_nsu` → cursor oficial (só anda para frente, exceto realinhamento
      explícito a partir do `ultNSU` que o próprio ambiente devolveu);
    - `max_nsu`    → até onde o ambiente tem documento para este CNPJ
                      (`ultimo_nsu == max_nsu` é a definição oficial de "em dia");
    - `proxima_consulta_em` / `bloqueado_ate` → janelas de consumo;
    - `travado_em` → lease: garante que duas tasks do mesmo CNPJ+tipo nunca
                      consultem ao mesmo tempo (fora de sequência = 656).
    """

    __tablename__ = "sincronizacoes_dfe"
    __table_args__ = (
        UniqueConstraint("empresa_id", "tipo", name="uq_sincronizacao_empresa_tipo"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    tipo: Mapped[TipoDocumentoFiscal] = mapped_column(Enum(TipoDocumentoFiscal))

    ultimo_nsu: Mapped[str] = mapped_column(String(20), default="0")
    max_nsu: Mapped[str | None] = mapped_column(String(20), nullable=True)

    proxima_consulta_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo_bloqueio: Mapped[str | None] = mapped_column(Text, nullable=True)
    bloqueios_seguidos: Mapped[int] = mapped_column(Integer, default=0)

    # Cota de consultas pontuais (consChNFe/consNSU): 20 por hora, por CNPJ.
    consultas_pontuais: Mapped[int] = mapped_column(Integer, default=0)
    janela_pontual_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Lease mútuo entre workers.
    travado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tarefas_pendentes: Mapped[int] = mapped_column(Integer, default=0)
    ultima_consulta_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    empresa: Mapped["Empresa"] = relationship(back_populates="sincronizacoes")


class JettaxConfiguracaoEmpresa(Base):
    """Estado local e cursores da captura Jettax/Morfeu de uma empresa.

    Estes cursores pertencem à Jettax e nunca são misturados ao NSU da
    distribuição direta. A ativação é explícita: cadastrar uma empresa no
    NotasFlow não envia nada ao fornecedor automaticamente.
    """

    __tablename__ = "jettax_configuracoes_empresas"
    __table_args__ = (UniqueConstraint("empresa_id", name="uq_jettax_configuracao_empresa"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="nao_registrada")
    ativa: Mapped[bool] = mapped_column(Boolean, default=False)
    baixar_nfes: Mapped[bool] = mapped_column(Boolean, default=False)
    baixar_nfes_enviadas: Mapped[bool] = mapped_column(Boolean, default=False)
    ultimo_id_nfse: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ultimo_id_nfe_saida: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ultimo_id_nfe_entrada: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ultimo_registro_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultima_sincronizacao_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    falhas_seguidas: Mapped[int] = mapped_column(Integer, default=0)
    travado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    empresa: Mapped["Empresa"] = relationship(back_populates="jettax_configuracao")


class JettaxExecucao(Base):
    """Resultado auditável de uma consulta Jettax, separado do fluxo SEFAZ."""

    __tablename__ = "jettax_execucoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    tipo: Mapped[TipoDocumentoFiscal] = mapped_column(Enum(TipoDocumentoFiscal))
    fluxo: Mapped[str] = mapped_column(String(20), default="")  # sales | purchases | nfse
    status: Mapped[str] = mapped_column(String(30), default="em_andamento")
    avancar_cursor: Mapped[bool] = mapped_column(Boolean, default=True)
    cursor_antes: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cursor_depois: Mapped[str | None] = mapped_column(String(100), nullable=True)
    documentos_importados: Mapped[int] = mapped_column(Integer, default=0)
    documentos_duplicados: Mapped[int] = mapped_column(Integer, default=0)
    documentos_ignorados: Mapped[int] = mapped_column(Integer, default=0)
    mensagem_erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    aviso: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticket: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    origem: Mapped[str] = mapped_column(String(20), default="manual")
    iniciado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    empresa: Mapped["Empresa"] = relationship(back_populates="jettax_execucoes")


class JettaxSaudeConector(Base):
    """Última verificação autenticada do conector por escritório."""

    __tablename__ = "jettax_saude_conector"
    __table_args__ = (UniqueConstraint("escritorio_id", name="uq_jettax_saude_escritorio"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="desconhecido")
    verificado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mensagem: Mapped[str | None] = mapped_column(Text, nullable=True)


class JettaxWebhookEvento(Base):
    """Notificação recebida da Jettax, deduplicada para suportar retries."""

    __tablename__ = "jettax_webhook_eventos"
    __table_args__ = (
        UniqueConstraint("tipo", "ticket", "status", name="uq_jettax_webhook_retentativa"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int | None] = mapped_column(ForeignKey("escritorios.id"), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(String(60))
    ticket: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30))
    mensagem: Mapped[str | None] = mapped_column(Text, nullable=True)
    recebido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventoFiscalPendente(Base):
    """
    Evento fiscal (ex.: cancelamento) que chegou ANTES da nota a que se
    refere. A ordem de NSU não garante que a nota original venha primeiro,
    então o evento fica guardado aqui até o documento ser gravado — nesse
    momento é aplicado automaticamente e a linha é marcada como processada.
    """

    __tablename__ = "eventos_fiscais_pendentes"
    __table_args__ = (
        UniqueConstraint(
            "empresa_id",
            "tipo",
            "chave_acesso",
            "tipo_evento",
            name="uq_evento_pendente_por_documento",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"))
    tipo: Mapped[TipoDocumentoFiscal] = mapped_column(Enum(TipoDocumentoFiscal))
    chave_acesso: Mapped[str] = mapped_column(String(60), index=True)
    tipo_evento: Mapped[str] = mapped_column(String(30))  # "cancelamento"
    nsu: Mapped[str] = mapped_column(String(20), index=True)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_evento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processado: Mapped[bool] = mapped_column(Boolean, default=False)
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documentos_fiscais.id"), nullable=True)
    recebido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped["Empresa"] = relationship()
    documento: Mapped[Optional["DocumentoFiscal"]] = relationship()


class RegistroAuditoria(Base):
    """
    Trilha de auditoria: quem fez o quê, quando.

    Registra logins, cadastros, certificados, disparos de importação,
    downloads e gestão da equipe. `escritorio_id` é anulável para acomodar
    tentativas de login com e-mail inexistente (dono desconhecido).
    """

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int | None] = mapped_column(
        ForeignKey("escritorios.id"), nullable=True, index=True
    )
    quando: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id"), nullable=True
    )
    usuario_email: Mapped[str] = mapped_column(String(255), default="")
    acao: Mapped[str] = mapped_column(String(60), index=True)
    entidade: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entidade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)

    escritorio: Mapped[Optional["Escritorio"]] = relationship()
    usuario: Mapped[Optional["Usuario"]] = relationship()


class BatimentoSistema(Base):
    """
    Batimento (heartbeat) de componentes de fundo: agendador e worker.

    O Celery Beat não expõe "estou vivo" por API — mas só ele dispara a task
    `sincronizar_tudo`. Cada tarefa periódica marca aqui o seu passo; se o
    batimento do agendador envelhece além de alguns intervalos, é porque o
    contêiner do beat está parado e ninguém avisou o operador. É o mínimo
    de observabilidade que faz a diferença entre "sistema parado há 2 dias"
    e "sistema trabalhando sozinho".
    """

    __tablename__ = "batimentos_sistema"

    componente: Mapped[str] = mapped_column(String(30), primary_key=True)
    visto_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    detalhe: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class StatusBackup(str, enum.Enum):
    EM_ANDAMENTO = "em_andamento"
    OK = "ok"
    ERRO = "erro"


class BackupRegistro(Base):
    """
    Histórico de backups reais (banco + manifesto + espelho de XMLs).

    Um backup não é "exportar banco": é o pacote que permite reconstruir o
    sistema num servidor novo. Cada execução registra aqui o resultado,
    o tamanho e quando a restauração foi testada pela última vez — porque
    backup que nunca foi restaurado é uma esperança, não um plano.
    """

    __tablename__ = "backups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), default="agendado")  # agendado | manual
    status: Mapped[StatusBackup] = mapped_column(
        Enum(StatusBackup), default=StatusBackup.EM_ANDAMENTO
    )
    iniciado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finalizado_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tamanho_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    caminho: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    checksum_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    objeto_remoto: Mapped[Optional[str]] = mapped_column(String(700), nullable=True)
    arquivos_incluidos: Mapped[int] = mapped_column(Integer, default=0)
    empresas: Mapped[int] = mapped_column(Integer, default=0)
    documentos: Mapped[int] = mapped_column(Integer, default=0)
    execucoes: Mapped[int] = mapped_column(Integer, default=0)
    detalhe: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    erro: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    restauracao_testada_em: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    restauracao_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
