"""
Cofre de segredos.

A senha do certificado A1 nunca é gravada em texto puro: é cifrada
(Fernet/AES) antes de tocar o banco, com uma chave mestra que só existe
na variável de ambiente do servidor.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_fernet: Fernet | None = None


def _obter_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    chave = (settings.vault_master_key or "").strip()
    if not chave:
        raise RuntimeError(
            "VAULT_MASTER_KEY não configurada. Gere com: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    _fernet = Fernet(chave.encode())
    return _fernet


def cifrar_segredo(texto_puro: str) -> str:
    """Cifra a senha do certificado antes de gravar no banco."""
    return _obter_fernet().encrypt(texto_puro.encode()).decode()


def decifrar_segredo(texto_cifrado: str) -> str:
    """
    Decifra a senha do certificado. Só deve ser chamado no exato momento de
    abrir o .pfx para autenticação mTLS — nunca para exibir em tela, log ou
    resposta de API.
    """
    try:
        return _obter_fernet().decrypt(texto_cifrado.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Não foi possível decifrar o segredo — chave mestra incorreta "
            "ou dado corrompido."
        ) from exc
