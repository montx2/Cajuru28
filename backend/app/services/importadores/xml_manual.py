"""
Importação de XML que chega pronto — ZIP ou arquivos soltos exportados de
outro sistema (Jettax360, e-mail, pasta do computador).

Quando dois sistemas consultam a Distribuição DF-e com o mesmo certificado,
a SEFAZ responde 656 (consumo indevido) e trava o certificado por ~1 hora.
Com um só capturando, o outro recebe: este módulo lê o XML exportado e grava
o documento como se tivesse vindo da fonte — mesma nota, mesma chave, mesma
regra de não duplicar.
"""

import io
import os
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.documentos import normalizar_documento
from app.models import DirecaoDocumento, DocumentoFiscal, Empresa, TipoDocumentoFiscal
from app.services.proveniencia import registrar_proveniencia

from .base import DocumentoBaixado
from .cte_sefaz import ImportadorCTeSEFAZ
from .nfse_adn import ImportadorNFSeADN
from .nfe_sefaz import ImportadorNFeSEFAZ
from ._distribuicao_dfe import competencia_de_texto, metadados_da_chave

# Espelha o limite de arquivos do lote de empresas: um lote de XMLs é o mesmo
# gesto operacional (uma pasta/ZIP exportada), não uma importação infinita.
LIMITE_XMLS = 200
LIMITE_BYTES_XML = 2 * 1024 * 1024
LIMITE_BYTES_LOTE = 100 * 1024 * 1024


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def classificar_xml(conteudo: bytes) -> str:
    """'nfe' | 'nfe_resumo' | 'nfe_autorizacao' | 'cte' | 'cte_resumo' | 'nfse' | ''.

    `infNFe`/`infCTe`/`infNFSe` são os elementos que carregam a chave (Id) em
    todos os leiautes; o nome da raiz varia com o envelope (proc, res, lote).
    NFS-e é checado por último e por igualdade exata: `infNFSe` NÃO começa
    com `infNFe`.

    **Resumo não é nota.** Portais e outros sistemas exportam `resNFe` (e o
    `protNFe`) com o nome da chave; são documentos legítimos, mas não contêm a
    nota (itens, totais). Antes, os dois entravam como "nfe" e a nota ficava
    marcada como completa guardando só a autorização — o contador exportava um
    XML que não serve para escriturar. Agora cada um tem seu tipo: o resumo
    entra como nota EM RESUMO (a captura completa sozinha) e o protocolo é
    recusado com instrução.
    """
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError:
        return ""
    for elemento in raiz.iter():
        nome = _local(elemento.tag)
        if nome == "infNFe":
            return "nfe"
        if nome == "infCTe":
            return "cte"
        if nome == "infNFSe":
            return "nfse"
    nome_raiz = _local(raiz.tag)
    # Protocolo de autorização isolado: confirma que a NF-e existe, mas não é a
    # nota. Não deve ir para a contabilidade como XML fiscal completo.
    if nome_raiz in {"protNFe", "protCTe"}:
        return "nfe_autorizacao"
    if nome_raiz == "resNFe":
        return "nfe_resumo"
    if nome_raiz == "resCTe":
        return "cte_resumo"
    if nome_raiz in {"procNFe", "NFe", "enviNFe"}:
        return "nfe"
    if nome_raiz in {"procCTe", "CTe", "enviCTe"}:
        return "cte"
    if "nfse" in nome_raiz.lower():
        return "nfse"
    return ""


def converter_xml(conteudo: bytes, tipo: str) -> DocumentoBaixado | None:
    """Reaproveita os conversores dos importadores oficiais — sem HTTP.

    O CNPJ consultado entra vazio: aqui a empresa só é conhecida DEPOIS, pelo
    destinatário/emitente do próprio documento.
    """
    if tipo in {"nfe", "nfe_resumo"}:
        # O schema é só um palpite: quem decide o leiaute é o conteúdo (um
        # resNFe importado manualmente nasce como "resumo" e entra na fila de
        # complemento em vez de fingir ser a nota).
        schema = "resNFe" if tipo == "nfe_resumo" else "procNFe"
        return ImportadorNFeSEFAZ()._converter("0", schema, conteudo, "")  # noqa: SLF001
    if tipo in {"cte", "cte_resumo"}:
        schema = "resCTe" if tipo == "cte_resumo" else "procCTe"
        return ImportadorCTeSEFAZ()._converter("0", schema, conteudo, "")  # noqa: SLF001
    if tipo == "nfse":
        return ImportadorNFSeADN()._converter_documento({}, "", xml_bytes=conteudo)  # noqa: SLF001
    return None


def casar_com_empresa(
    db: Session, escritorio_id: int, doc: DocumentoBaixado
) -> tuple[Empresa | None, str]:
    """
    O XML é da empresa que o recebeu (destinatário/tomador); se quem recebeu
    não estiver no cadastro, ainda pode ser nota PRESTADA por uma empresa do
    escritório (emitente/prestador). Sem casamento nenhum, o item volta para
    o operador — importar para a empresa errada é pior que não importar.
    """
    casamentos = casar_com_empresas(db, escritorio_id, doc)
    return casamentos[0] if casamentos else (None, "")


def casar_com_empresas(db: Session, escritorio_id: int, doc: DocumentoBaixado) -> list[tuple[Empresa, str]]:
    """Ambas as partes cadastradas recebem sua cópia, sem atravessar tenant."""
    casamentos: list[tuple[Empresa, str]] = []
    for campo, direcao in (
        ("destinatario_documento", "tomada"),
        ("emitente_documento", "prestada"),
    ):
        bruto = (getattr(doc, campo) or "").strip()
        if not bruto:
            continue
        try:
            documento = normalizar_documento(bruto)
        except ValueError:
            continue
        empresa = (
            db.query(Empresa)
            .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == documento)
            .first()
        )
        if empresa is not None and all(cadastrada.id != empresa.id for cadastrada, _ in casamentos):
            casamentos.append((empresa, direcao))
    return casamentos


def _para_datetime(valor: str) -> datetime | None:
    texto = (valor or "").strip()
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        pass
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto[: len(formato) + 2], formato).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
    return None


def gravar_documento(
    db: Session, empresa: Empresa, tipo: TipoDocumentoFiscal, doc: DocumentoBaixado, nome_arquivo: str
) -> str:
    """importado | completada | duplicada | sem_chave | sem_data.

    Compartilha o insert idempotente do worker. Importar um XML integral para
    uma nota em resumo promove a nota existente em vez de ignorar o arquivo.
    """
    from app.worker.tasks import _aplicar_eventos_pendentes, _gravar_documento, _normalizar_chave, _sobrescrever_xml

    chave = _normalizar_chave(doc.chave_acesso)
    if not chave:
        return "sem_chave"
    existente = db.query(DocumentoFiscal).filter(
        DocumentoFiscal.empresa_id == empresa.id, DocumentoFiscal.chave_acesso == chave,
    ).with_for_update().first()
    if existente is not None:
        registrar_proveniencia(db, existente.id, "xml", nome_arquivo)
        if existente.tipo == tipo and existente.leiaute == "resumo" and doc.leiaute == "completo":
            # `_sobrescrever_xml` recusa payload que não seja a nota inteira
            # (ex.: um resNFe rotulado como completo): nesse caso a nota segue
            # em resumo, na fila, em vez de virar um "completo" que não é.
            if _sobrescrever_xml(existente, doc):
                _aplicar_eventos_pendentes(db, empresa.id, tipo, chave)
                return "completada"
        return "duplicada"

    data_emissao = _para_datetime(doc.data_emissao)
    if data_emissao is None and tipo in (TipoDocumentoFiscal.NFE, TipoDocumentoFiscal.CTE):
        da_chave = competencia_de_texto(metadados_da_chave(chave).get("competencia", ""), "")
        data_emissao = _para_datetime(da_chave) if da_chave else None
    if data_emissao is None:
        return "sem_data"
    doc = replace(doc, chave_acesso=chave, data_emissao=data_emissao)
    criado = _gravar_documento(db, empresa.id, tipo, doc,
        origem="xml", identificador_externo=nome_arquivo, nsu_registro="manual")
    if criado:
        _aplicar_eventos_pendentes(db, empresa.id, tipo, chave)
        return "importado"
    # Um insert concorrente pode ter criado justamente o resumo que este
    # arquivo completa. Releia o estado atualizado antes de declarar duplicata.
    db.expire_all()
    existente = db.query(DocumentoFiscal).filter(
        DocumentoFiscal.empresa_id == empresa.id, DocumentoFiscal.chave_acesso == chave,
    ).with_for_update().first()
    if existente and existente.tipo == tipo and existente.leiaute == "resumo" and doc.leiaute == "completo":
        if _sobrescrever_xml(existente, doc):
            _aplicar_eventos_pendentes(db, empresa.id, tipo, chave)
            return "completada"
    return "duplicada"


def documento_com_direcao(doc: DocumentoBaixado, direcao: str) -> DocumentoBaixado:
    return replace(doc, direcao=direcao)


def extrair_xmls_do_zip(conteudo: bytes) -> list[tuple[str, bytes]]:
    """Membros .xml de um ZIP — só o conteúdo interessa, nada é extraído
    para disco (sem risco de caminho); o resto da pasta é ignorado.

    Levanta `ValueError` com mensagem em português para ZIP corrompido ou
    protegido por senha — quem chama transforma em item do resultado.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as arquivo_zip:
            membros = [membro for membro in arquivo_zip.infolist() if not membro.is_dir() and membro.filename.lower().endswith(".xml")]
            if len(membros) > LIMITE_XMLS:
                raise ValueError(f"ZIP contém mais de {LIMITE_XMLS} XMLs; importe em etapas.")
            if any(membro.file_size > LIMITE_BYTES_XML for membro in membros):
                raise ValueError("ZIP contém XML maior que 2 MB; separe o arquivo antes de importar.")
            if sum(membro.file_size for membro in membros) > LIMITE_BYTES_LOTE:
                raise ValueError("Conteúdo descompactado do ZIP ultrapassa o limite do lote.")
            # ZipInfo identifica a entrada, não apenas seu nome: ZIPs podem
            # conter dois membros homônimos com notas DIFERENTES.
            return [(os.path.basename(membro.filename), arquivo_zip.read(membro)) for membro in membros]
    except RuntimeError as exc:
        raise ValueError("ZIP protegido por senha — exporte novamente sem senha.") from exc
    except (zipfile.BadZipFile, NotImplementedError, OSError) as exc:
        raise ValueError("ZIP ilegível ou corrompido.") from exc
