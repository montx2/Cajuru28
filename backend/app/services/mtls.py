"""
Extrai o certificado e a chave privada de um arquivo .pfx (A1) para uso em
autenticação mTLS contra o ADN e o SEFAZ.

Regras de segurança portadas do Importarnotas original, que já acertava
isso:
- os arquivos .pem/.key temporários nascem numa pasta com permissão 0700;
- são apagados assim que a chamada HTTP termina, com ou sem erro (bloco
  `finally`) — nunca sobra chave privada solta em disco;
- a senha em texto puro só existe na memória do processo pelo tempo mínimo
  necessário para abrir o .pfx, nunca é logada.
"""

import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    pkcs12,
)


def obter_validade_certificado(pfx_bytes: bytes, senha: str) -> datetime:
    """Lê a data de validade (notAfter) direto do X.509 dentro do .pfx."""
    _, cert, _ = pkcs12.load_key_and_certificates(pfx_bytes, senha.encode())
    if cert is None:
        raise ValueError("Certificado não encontrado dentro do .pfx — arquivo inválido?")
    return cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(
        tzinfo=timezone.utc
    )


def obter_cnpj_do_certificado(pfx_bytes: bytes, senha: str) -> str:
    """Lê CNPJ do A1 sem remover letras de identificadores alfanuméricos.

    O parser de identidade conhece os OIDs ICP-Brasil e somente devolve um
    CNPJ validado. CPF é um certificado válido para outros usos, mas não é
    um CNPJ utilizável nas integrações fiscais desta função.
    """
    # Import tardio evita acoplamento no caminho quente de criação do contexto
    # mTLS e mantém um único parser da identidade do certificado.
    from app.services.certificados import extrair_identidade

    identidade = extrair_identidade(pfx_bytes, senha)
    return identidade.documento if len(identidade.documento) == 14 else ""


@contextmanager
def sessao_mtls(pfx_bytes: bytes, senha: str) -> Iterator[tuple[str, str]]:
    """
    Context manager: gera arquivos .pem/.key temporários numa pasta 0700,
    entrega os caminhos para uso em `httpx.Client(cert=(...))`, e apaga tudo
    ao sair do bloco `with` — mesmo se a chamada HTTP falhar.

    Uso:
        with sessao_mtls(pfx_bytes, senha) as (cert_path, key_path):
            client = httpx.Client(cert=(cert_path, key_path))
            ...
    """
    chave, cert, _ = pkcs12.load_key_and_certificates(pfx_bytes, senha.encode())
    if chave is None or cert is None:
        raise ValueError("Falha ao abrir o .pfx — senha incorreta ou arquivo corrompido")

    pasta_temp = tempfile.mkdtemp(prefix="notasflow_mtls_")
    os.chmod(pasta_temp, stat.S_IRWXU)  # 0700 — só o dono do processo lê

    cert_path = os.path.join(pasta_temp, "cert.pem")
    key_path = os.path.join(pasta_temp, "key.pem")

    try:
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(Encoding.PEM))
        with open(key_path, "wb") as f:
            f.write(
                chave.private_bytes(Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption())
            )
        os.chmod(cert_path, stat.S_IRUSR | stat.S_IWUSR)
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)

        yield cert_path, key_path
    finally:
        for caminho in (cert_path, key_path):
            if os.path.exists(caminho):
                os.remove(caminho)
        os.rmdir(pasta_temp)
