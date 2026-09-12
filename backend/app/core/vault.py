"""
Cofre de segredos.

A senha do certificado A1 nunca é gravada em texto puro: é cifrada
(Fernet/AES) antes de tocar o banco, com uma chave mestra que só existe
na variável de ambiente do servidor.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SegredoIndecifravelError(ValueError):
    """A senha cifrada não pode ser aberta com nenhuma chave configurada."""


_MENSAGEM_SEGREDO_INDECIFRAVEL = (
    "Certificado inacessível; restaure a chave do cofre anterior ou envie o .pfx novamente."
)


def _obter_fernets() -> list[Fernet]:
    """
    Retorna a chave atual e, opcionalmente, as chaves anteriores.

    `VAULT_PREVIOUS_MASTER_KEYS` permite uma rotação segura: a chave nova é
    usada para novas gravações e as antigas são aceitas apenas para leitura
    enquanto os certificados existentes são reenviados. As chaves são
    separadas por vírgula e, assim como a chave principal, jamais vão ao banco.
    """
    chave_atual = (settings.vault_master_key or "").strip()
    if not chave_atual:
        raise RuntimeError(
            "VAULT_MASTER_KEY não configurada. Gere com: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )

    chaves = [chave_atual]
    chaves.extend(
        chave.strip()
        for chave in (settings.vault_previous_master_keys or "").split(",")
        if chave.strip() and chave.strip() != chave_atual
    )

    try:
        return [Fernet(chave.encode()) for chave in chaves]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "VAULT_MASTER_KEY ou VAULT_PREVIOUS_MASTER_KEYS não contém uma chave Fernet válida."
        ) from exc


def cifrar_segredo(texto_puro: str) -> str:
    """Cifra a senha do certificado antes de gravar no banco."""
    return _obter_fernets()[0].encrypt(texto_puro.encode()).decode()


def decifrar_segredo(texto_cifrado: str) -> str:
    """Decifra a senha somente no instante em que ela é necessária."""
    return decifrar_bytes(texto_cifrado.encode()).decode()


def cifrar_bytes(conteudo: bytes) -> bytes:
    """Cifra conteúdo sensível persistido (como o PFX A1) com a chave atual."""
    return _obter_fernets()[0].encrypt(conteudo)


def decifrar_bytes(conteudo_cifrado: bytes) -> bytes:
    """Tenta chave atual e chaves anteriores sem expor material secreto."""
    for fernet in _obter_fernets():
        try:
            return fernet.decrypt(conteudo_cifrado)
        except InvalidToken:
            continue
    raise SegredoIndecifravelError(_MENSAGEM_SEGREDO_INDECIFRAVEL)
