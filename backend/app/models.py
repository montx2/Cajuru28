"""
Modelos do banco.

Toda tabela carrega `escritorio_id`. Hoje só existe um escritório — o seu —
mas o isolamento por tenant já está no schema desde a Fase 0, então virar
multiempresa depois é ligar uma trava de acesso, não migrar dado.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class Usuario(Base):
    """Pessoa do escritório que acessa o sistema (login)."""

    __tablename__ = "usuarios"
    __table_args__ = (UniqueConstraint("escritorio_id", "email", name="uq_usuario_email_por_escritorio"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    escritorio_id: Mapped[int] = mapped_column(ForeignKey("escritorios.id"))
    nome: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255), index=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
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
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    escritorio: Mapped["Escritorio"] = relationship(back_populates="empresas")
    certificados: Mapped[list["Certificado"]] = relationship(back_populates="empresa")
    documentos: Mapped[list["DocumentoFiscal"]] = relationship(back_populates="empresa")


class Certificado(Base):
    """
    Certificado A1 de uma empresa. A senha NUNCA fica aqui em texto puro —
    `senha_cifrada` é o resultado de app.core.vault.cifrar_segredo().
    """

    __tablename__ = "certificados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"))
    arquivo_path: Mapped[str] = mapped_column(String(500))  # caminho do .pfx no volume
    senha_cifrada: Mapped[str] = mapped_column(Text)
    validade: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped["Empresa"] = relationship(back_populates="certificados")


class TipoDocumentoFiscal(str, enum.Enum):
    NFSE = "nfse"
    NFE = "nfe"
    CTE = "cte"


class DirecaoDocumento(str, enum.Enum):
    TOMADA = "tomada"      # nota recebida (a empresa é tomadora/destinatária)
    PRESTADA = "prestada"  # nota emitida (a empresa é prestadora/emitente)


class DocumentoFiscal(Base):
    """Uma nota importada — NFS-e, NFe ou CT-e."""

    __tablename__ = "documentos_fiscais"
    __table_args__ = (UniqueConstraint("empresa_id", "chave_acesso", name="uq_documento_por_empresa"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"))
    tipo: Mapped[TipoDocumentoFiscal] = mapped_column(Enum(TipoDocumentoFiscal))
    direcao: Mapped[DirecaoDocumento] = mapped_column(Enum(DirecaoDocumento))
    chave_acesso: Mapped[str] = mapped_column(String(60), index=True)
    nsu: Mapped[str] = mapped_column(String(20), index=True)
    data_emissao: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valor_total: Mapped[float] = mapped_column()
    xml_path: Mapped[str] = mapped_column(String(500))
    importado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    empresa: Mapped["Empresa"] = relationship(back_populates="documentos")


class StatusExecucao(str, enum.Enum):
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDA = "concluida"
    ERRO = "erro"


class ExecucaoImportacao(Base):
    """Histórico de cada rodada de importação — o que rodou, quando, com que resultado."""

    __tablename__ = "execucoes_importacao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"))
    tipo: Mapped[TipoDocumentoFiscal] = mapped_column(Enum(TipoDocumentoFiscal))
    status: Mapped[StatusExecucao] = mapped_column(Enum(StatusExecucao), default=StatusExecucao.EM_ANDAMENTO)
    documentos_importados: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_nsu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mensagem_erro: Mapped[str | None] = mapped_column(Text, nullable=True)
    iniciado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalizado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    empresa: Mapped["Empresa"] = relationship()
