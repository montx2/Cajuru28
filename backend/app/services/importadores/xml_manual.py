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
    """'nfe' | 'nfe_autorizacao' | 'cte' | 'nfse' | '' — pelo leiaute.

    `infNFe`/`infCTe`/`infNFSe` são os elementos que carregam a chave (Id) em
    todos os leiautes; o nome da raiz varia com o envelope (proc, res, lote).
    NFS-e é checado por último e por igualdade exata: `infNFSe` NÃO começa
    com `infNFe`.
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
    # Alguns portais exportam apenas o protocolo de autorização (`protNFe`).
    # Ele confirma que a NF-e foi autorizada, mas não contém a nota (itens,
    # emitente, destinatário e totais). Não deve ser enviado à contabilidade
    # como se fosse um XML fiscal completo.
    if nome_raiz == "protNFe":
        return "nfe_autorizacao"
    if nome_raiz in {"procNFe", "resNFe", "NFe"}:
        return "nfe"
    if nome_raiz in {"procCTe", "resCTe", "CTe"}:
        return "cte"
    if "nfse" in nome_raiz.lower():
        return "nfse"
    return ""


def converter_xml(conteudo: bytes, tipo: str) -> DocumentoBaixado | None:
    """Reaproveita os conversores dos importadores oficiais — sem HTTP.

    O CNPJ consultado entra vazio: aqui a empresa só é conhecida DEPOIS, pelo
    destinatário/emitente do próprio documento.
    """
    if tipo == "nfe":
        return ImportadorNFeSEFAZ()._converter("0", "procNFe", conteudo, "")  # noqa: SLF001
    if tipo == "cte":
        return ImportadorCTeSEFAZ()._converter("0", "procCTe", conteudo, "")  # noqa: SLF001
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
        if empresa is not None:
            return empresa, direcao
    return None, ""


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
    """"importado" | "duplicada" — idempotente por (empresa, chave)."""
    chave = "".join(d for d in str(doc.chave_acesso) if d.isdigit()) or str(doc.chave_acesso)
    if not chave:
        return "sem_chave"

    existente = (
        db.query(DocumentoFiscal)
        .filter(DocumentoFiscal.empresa_id == empresa.id, DocumentoFiscal.chave_acesso == chave)
        .first()
    )
    if existente is not None:
        # A nota é única, mas cada fonte que a confirma fica rastreável.
        registrar_proveniencia(db, existente.id, "xml", nome_arquivo)
        return "duplicada"

    data_emissao = _para_datetime(doc.data_emissao)
    if data_emissao is None and tipo in (TipoDocumentoFiscal.NFE, TipoDocumentoFiscal.CTE):
        # A chave de acesso carrega AAMM da emissão (formato fixo do Manual
        # de Orientação do Contribuinte) — leitura, não adivinhação.
        da_chave = competencia_de_texto(
            metadados_da_chave(doc.chave_acesso).get("competencia", ""), ""
        )
        data_emissao = _para_datetime(da_chave) if da_chave else None
    if data_emissao is None:
        # Coluna NOT NULL sem valor legível: registrar data inventada é pior
        # que devolver o item para o operador.
        return "sem_data"
    competencia_texto = competencia_de_texto(doc.competencia, doc.data_emissao)
    competencia = None
    if competencia_texto:
        try:
            competencia = date.fromisoformat(competencia_texto[:10])
        except ValueError:
            competencia = None

    pasta = os.path.join(settings.dados_dir, "xml", str(empresa.id), tipo.value)
    nome_seguro = "".join(c for c in chave if c.isalnum() or c in "-_") or nome_arquivo
    xml_path = os.path.join(pasta, f"{nome_seguro}.xml")

    documento = DocumentoFiscal(
        empresa_id=empresa.id,
        tipo=tipo,
        direcao=DirecaoDocumento(doc.direcao if doc.direcao in ("tomada", "prestada") else "tomada"),
        chave_acesso=chave,
        nsu="manual",
        data_emissao=data_emissao,
        competencia=competencia,
        valor_total=float(doc.valor_total or 0),
        xml_path=xml_path,
        leiaute=doc.leiaute or "completo",
        numero=(doc.numero or "")[:20] or None,
        serie=(doc.serie or "")[:10] or None,
        emitente_documento=(doc.emitente_documento or "")[:18] or None,
        emitente_nome=(doc.emitente_nome or "")[:255] or None,
        destinatario_documento=(doc.destinatario_documento or "")[:18] or None,
        destinatario_nome=(doc.destinatario_nome or "")[:255] or None,
        situacao=(doc.status_autorizacao or "")[:255] or None,
        origem="xml",
    )
    db.add(documento)
    db.flush()
    registrar_proveniencia(db, documento.id, "xml", nome_arquivo)
    os.makedirs(pasta, exist_ok=True)
    with open(xml_path, "wb") as f:
        f.write(doc.xml)
    return "importado"


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
            saida: list[tuple[str, bytes]] = []
            for membro in arquivo_zip.namelist():
                nome = os.path.basename(membro)
                if not nome.lower().endswith(".xml"):
                    continue
                saida.append((nome, arquivo_zip.read(membro)))
            return saida
    except RuntimeError as exc:
        raise ValueError("ZIP protegido por senha — exporte novamente sem senha.") from exc
    except (zipfile.BadZipFile, NotImplementedError, OSError) as exc:
        raise ValueError("ZIP ilegível ou corrompido.") from exc
