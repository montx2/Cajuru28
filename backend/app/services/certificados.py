"""Identidade e armazenamento protegido de certificados A1.

O PFX é material de chave privada. Além da senha cifrada no banco, o arquivo
inteiro é cifrado antes de tocar o volume. Arquivos legados em claro são
migrados atomicamente na primeira leitura bem-sucedida.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtensionOID, NameOID, ObjectIdentifier

from app.core.documentos import (
    normalizar_cnpj,
    normalizar_documento,
    validar_cnpj,
    validar_cpf,
    validar_documento,
)
from app.core.vault import cifrar_bytes, decifrar_bytes

OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")
OID_CPF = ObjectIdentifier("2.16.76.1.3.1")
_MARCADOR_PFX_CIFRADO = b"NOTASFLOW-PFX-FERNET-V1\n"


def _escrever_atomico(caminho: str | Path, conteudo: bytes) -> None:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(destino.parent, 0o700)
    fd, temporario = tempfile.mkstemp(prefix=".novo-", dir=destino.parent)
    try:
        with os.fdopen(fd, "wb") as arquivo:
            arquivo.write(conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.chmod(temporario, 0o600)
        os.replace(temporario, destino)
        os.chmod(destino, 0o600)
    except Exception:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise


def guardar_pfx_protegido(caminho: str | Path, pfx_bytes: bytes) -> None:
    """Persiste somente PFX cifrado; nunca grava a chave privada em claro."""
    if not pfx_bytes:
        raise ValueError("O arquivo PFX está vazio.")
    _escrever_atomico(caminho, _MARCADOR_PFX_CIFRADO + cifrar_bytes(pfx_bytes))


def ler_pfx_protegido(caminho: str | Path, *, migrar_legado: bool = True) -> bytes:
    """Lê PFX em memória e cifra automaticamente arquivos legados em claro."""
    origem = Path(caminho)
    bruto = origem.read_bytes()
    if bruto.startswith(_MARCADOR_PFX_CIFRADO):
        return decifrar_bytes(bruto[len(_MARCADOR_PFX_CIFRADO) :])
    if not bruto:
        raise ValueError("O arquivo PFX está vazio.")
    if migrar_legado:
        guardar_pfx_protegido(origem, bruto)
    return bruto


def _candidatos_cnpj(texto: str) -> list[str]:
    """Extrai somente candidatos de 14 caracteres, preservando letras."""
    candidatos: list[str] = []
    texto_maiusculo = texto.upper()
    # CNPJ alfanumérico direto no DER/subject.
    for achado in re.finditer(r"(?<![A-Z0-9])([A-Z0-9]{14})(?![A-Z0-9])", texto_maiusculo):
        try:
            candidato = normalizar_cnpj(achado.group(1))
        except ValueError:
            continue
        if candidato not in candidatos:
            candidatos.append(candidato)
    # Máscara de CNPJ pode aparecer também em identificadores alfanuméricos
    # novos (por exemplo AB.CD-EF12345680). Busca janelas sobrepostas: um
    # prefixo como "certificado-" não pode impedir o encontro que começa em
    # "AB". Remove-se somente pontuação de apresentação, nunca letras.
    caracteres_documento = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    for inicio, primeiro in enumerate(texto_maiusculo):
        if primeiro not in caracteres_documento:
            continue
        compactado: list[str] = []
        for caractere in texto_maiusculo[inicio:]:
            if caractere in caracteres_documento:
                compactado.append(caractere)
            elif caractere in ".-/ ":
                continue
            else:
                break
            if len(compactado) == 14:
                try:
                    candidato = normalizar_cnpj("".join(compactado))
                except ValueError:
                    pass
                else:
                    if candidato not in candidatos:
                        candidatos.append(candidato)
                break
            if len(compactado) > 14:
                break
    return candidatos


def cnpj_de_nome_arquivo(nome_arquivo: str) -> str:
    """Último CNPJ válido no nome, aceitando o formato alfanumérico atual."""
    encontrados = [c for c in _candidatos_cnpj(Path(nome_arquivo).stem) if validar_cnpj(c)]
    return encontrados[-1] if encontrados else ""


def _docs_de_other_name(raw: bytes, *, tipo_cnpj: bool) -> list[str]:
    # A extensão ICP-Brasil identifica o tipo, portanto procuramos apenas um
    # token completo e nunca concatenamos fragmentos soltos do DER.
    texto = raw.decode("latin-1", errors="ignore")
    if tipo_cnpj:
        return _candidatos_cnpj(texto)
    return re.findall(r"(?<!\d)\d{11}(?!\d)", texto)


@dataclass
class IdentidadeCertificado:
    documento: str
    razao_social: str
    validade: datetime
    validade_utc: datetime
    evidencia_documento: str


def extrair_identidade(pfx_bytes: bytes, senha: str) -> IdentidadeCertificado:
    """Extrai CNPJ/CPF e razão social sem adivinhar senha ou modificar dados."""
    try:
        chave, cert, _ = pkcs12.load_key_and_certificates(
            pfx_bytes, (senha or "").encode("utf-8")
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "Não foi possível abrir o certificado com a senha informada "
            "(senha incorreta ou arquivo corrompido)."
        ) from exc
    if cert is None or chave is None:
        raise ValueError("O arquivo não contém certificado e chave privada (.pfx A1).")

    cnpjs: list[str] = []
    cpfs: list[str] = []
    evidencias: list[str] = []

    def adicionar_documento(valor: str, evidencia: str, *, esperado: str | None = None) -> None:
        try:
            candidato = normalizar_documento(valor)
        except ValueError:
            return
        if esperado == "cnpj" and len(candidato) != 14:
            return
        if esperado == "cpf" and len(candidato) != 11:
            return
        alvo = cnpjs if len(candidato) == 14 else cpfs
        if validar_documento(candidato) and candidato not in alvo:
            alvo.append(candidato)
            evidencias.append(evidencia)

    try:
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        for nome in san.value:
            if not isinstance(nome, x509.OtherName) or nome.type_id not in {OID_CNPJ, OID_CPF}:
                continue
            esperado = "cnpj" if nome.type_id == OID_CNPJ else "cpf"
            for doc in _docs_de_other_name(getattr(nome, "value", b""), tipo_cnpj=esperado == "cnpj"):
                adicionar_documento(doc, "subjectAltName ICP-Brasil", esperado=esperado)
    except x509.ExtensionNotFound:
        pass
    except Exception:  # noqa: BLE001
        evidencias.append("subjectAltName ilegível")

    # serialNumber de alguns A1 traz CNPJ alfanumérico com ou sem máscara.
    try:
        for atributo in cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER):
            texto = str(atributo.value)
            for candidato in _candidatos_cnpj(texto):
                adicionar_documento(candidato, "serialNumber", esperado="cnpj")
            for candidato in re.findall(r"(?<!\d)\d{11}(?!\d)", texto):
                adicionar_documento(candidato, "serialNumber", esperado="cpf")
    except Exception:  # noqa: BLE001
        pass

    if not cnpjs and not cpfs:
        subject = cert.subject.rfc4514_string()
        for candidato in _candidatos_cnpj(subject):
            adicionar_documento(candidato, "subject DN", esperado="cnpj")
        for candidato in re.findall(r"(?<!\d)\d{11}(?!\d)", subject):
            adicionar_documento(candidato, "subject DN", esperado="cpf")

    razao = ""
    for oid in (NameOID.ORGANIZATION_NAME, NameOID.COMMON_NAME):
        try:
            valores = [str(a.value).strip() for a in cert.subject.get_attributes_for_oid(oid)]
            valores = [v for v in valores if v]
            if valores:
                razao = valores[0]
                break
        except Exception:  # noqa: BLE001
            continue
    documento = cnpjs[0] if cnpjs else (cpfs[0] if cpfs else "")
    if razao and documento:
        razao = re.sub(rf"\s*[:\-]\s*{re.escape(documento)}\s*$", "", razao).strip()

    validade_utc = (
        cert.not_valid_after_utc
        if hasattr(cert, "not_valid_after_utc")
        else cert.not_valid_after.replace(tzinfo=timezone.utc)
    )
    if not documento:
        raise ValueError(
            "Não foi possível identificar o CNPJ/CPF dentro do certificado. "
            "Verifique se é um certificado A1 ICP-Brasil válido."
        )
    if not razao:
        razao = f"Empresa {documento}"

    return IdentidadeCertificado(
        documento=documento,
        razao_social=razao,
        validade=validade_utc.astimezone(),
        validade_utc=validade_utc,
        evidencia_documento=evidencias[0] if evidencias else "desconhecida",
    )


# Reexports estáveis para importadores e testes que historicamente importavam
# os validadores deste módulo.
__all__ = [
    "cnpj_de_nome_arquivo", "extrair_identidade", "guardar_pfx_protegido",
    "ler_pfx_protegido", "normalizar_cnpj", "validar_cnpj", "validar_cpf", "validar_documento",
]
