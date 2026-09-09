"""
Identidade de certificados A1: CNPJ/CPF e razão social.

Não tenta "adivinhar" senha nenhuma: a senha é sempre a que o usuário
informa explicitamente. Este módulo só extrai os dados do X.509 —
o CNPJ vem do campo ICP-Brasil (OID 2.16.76.1.3.3 no SubjectAltName)
com fallback para serialNumber e para o nome do arquivo, exatamente como o
pipeline CAJURUFINAL faz com certificados reais de produção.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtensionOID, NameOID, ObjectIdentifier

OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")
OID_CPF = ObjectIdentifier("2.16.76.1.3.1")


def apenas_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def _digito_cnpj(base: str) -> int:
    # Pesos oficiais (Receita Federal): 12 dígitos → 5..2; 13 → 6..2
    pesos = (
        [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        if len(base) == 12
        else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    )
    soma = sum(int(d) * p for d, p in zip(base, pesos))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def validar_cnpj(cnpj: str) -> bool:
    digitos = apenas_digitos(cnpj)
    if len(digitos) != 14 or len(set(digitos)) == 1:
        return False
    if _digito_cnpj(digitos[:12]) != int(digitos[12]):
        return False
    return _digito_cnpj(digitos[:13]) == int(digitos[13])


def validar_cpf(cpf: str) -> bool:
    digitos = apenas_digitos(cpf)
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for base, digito in ((digitos[:9], digitos[9]), (digitos[:10], digitos[10])):
        soma = sum(int(d) * p for d, p in zip(base, range(len(base) + 1, 1, -1)))
        resto = soma % 11
        esperado = 0 if resto < 2 else 11 - resto
        if esperado != int(digito):
            return False
    return True


def validar_documento(valor: str) -> bool:
    digitos = apenas_digitos(valor)
    if len(digitos) == 14:
        return validar_cnpj(digitos)
    if len(digitos) == 11:
        return validar_cpf(digitos)
    return False


def cnpj_de_nome_arquivo(nome_arquivo: str) -> str:
    """Última sequência de 14 dígitos válida como CNPJ no nome do arquivo."""
    digitos = apenas_digitos(nome_arquivo)
    for inicio in range(len(digitos) - 13):
        candidato = digitos[inicio : inicio + 14]
        if validar_cnpj(candidato):
            return candidato
    return ""


def _docs_de_other_name(raw: bytes) -> list[str]:
    # cryptography entrega DER; procurar sequência ASCII de dígitos dentro
    # do DER é mais seguro que concatenar textos (evita documento fantasma).
    texto = raw.decode("latin-1", errors="ignore")
    return [m for m in re.findall(r"\d{11,14}", texto)]


@dataclass
class IdentidadeCertificado:
    documento: str  # CNPJ (14) ou CPF (11), sem máscara
    razao_social: str
    validade: datetime
    validade_utc: datetime
    evidencia_documento: str  # de onde o documento veio (para depuração)


def extrair_identidade(pfx_bytes: bytes, senha: str) -> IdentidadeCertificado:
    """
    Abre o .pfx com a senha INFORMADA PELO USUÁRIO e extrai CNPJ/razão
    social do certificado. Levanta ValueError com mensagem clara quando a
    senha não confere ou o documento não pode ser identificado.
    """
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

    cnps: list[str] = []
    cpfs: list[str] = []
    evidencias: list[str] = []

    def adicionar_documento(valor: str, evidencia: str) -> None:
        candidato = apenas_digitos(valor)
        alvo = cnps if len(candidato) == 14 else cpfs
        if validar_documento(candidato) and candidato not in alvo:
            alvo.append(candidato)
            evidencias.append(evidencia)

    # 1) SubjectAltName ICP-Brasil (e-CNPJ): OID 2.16.76.1.3.3 (CNPJ) / .1 (CPF)
    try:
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        for nome in san.value:
            if not isinstance(nome, x509.OtherName) or nome.type_id not in {OID_CNPJ, OID_CPF}:
                continue
            for doc in _docs_de_other_name(getattr(nome, "value", b"")):
                alvo = cnps if nome.type_id == OID_CNPJ else cpfs
                if len(doc) == 14 and validar_documento(doc) and doc not in alvo:
                    cnps.append(doc)
                    evidencias.append("subjectAltName ICP-Brasil")
                elif len(doc) == 11 and validar_documento(doc) and doc not in cpfs:
                    cpfs.append(doc)
                    evidencias.append("subjectAltName ICP-Brasil")
    except x509.ExtensionNotFound:
        pass
    except Exception:  # noqa: BLE001
        evidencias.append("subjectAltName ilegível")

    # 2) serialNumber do Subject (muito comum em A1)
    try:
        for atributo in cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER):
            adicionar_documento(str(atributo.value), "serialNumber")
    except Exception:  # noqa: BLE001
        pass

    # 3) Fallback: dígitos delimitados no DN (sem concatenar)
    if not cnps and not cpfs:
        for candidato in re.findall(r"\d{11,14}", cert.subject.rfc4514_string()):
            adicionar_documento(candidato, "subject DN")

    # Razão social: organizationName → commonName (limpando sufixo :CNPJ)
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
    if razao and (cnps or cpfs):
        documento = (cnps[0] if cnps else cpfs[0])
        razao = re.sub(rf"\s*[:\-]\s*{re.escape(documento)}\s*$", "", razao).strip()

    # validade
    validade_utc = (
        cert.not_valid_after_utc
        if hasattr(cert, "not_valid_after_utc")
        else cert.not_valid_after.replace(tzinfo=timezone.utc)
    )
    validade_local = validade_utc.astimezone()

    documento = cnps[0] if cnps else (cpfs[0] if cpfs else "")
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
        validade=validade_local,
        validade_utc=validade_utc,
        evidencia_documento=evidencias[0] if evidencias else "desconhecida",
    )
