"""
Cofre de segredos.

Problema que isso resolve: no fluxo antigo, a senha de cada certificado A1
vivia em texto puro numa planilha Excel sincronizada por Dropbox — qualquer
pessoa com acesso à pasta (ou a um backup antigo, ou a uma cópia "em
conflito" esquecida) lia todas as senhas de todos os clientes.

Aqui a senha nunca é gravada em texto puro em lugar nenhum: nem no banco,
nem em log, nem em export. Ela é cifrada (Fernet/AES) antes de tocar o
banco, com uma chave mestra que só existe na variável de ambiente do
servidor (nunca no repositório, nunca no banco).

Isso NÃO é um substituto para um cofre de verdade (HashiCorp Vault, AWS KMS)
se este projeto crescer para multiempresa com dado sensível de muitos
clientes distintos — é o suficiente para eliminar o risco real de hoje sem
adicionar uma peça de infraestrutura nova. Ver docs/ARQUITETURA.md.
"""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_fernet = Fernet(settings.vault_master_key.encode())


def cifrar_segredo(texto_puro: str) -> str:
    """Cifra a senha do certificado antes de gravar no banco."""
    return _fernet.encrypt(texto_puro.encode()).decode()


def decifrar_segredo(texto_cifrado: str) -> str:
    """
    Decifra a senha do certificado. Só deve ser chamado no exato momento de
    abrir o .pfx para autenticação mTLS — nunca para exibir em tela, log ou
    resposta de API. Ver app/services/mtls.py.
    """
    try:
        return _fernet.decrypt(texto_cifrado.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Não foi possível decifrar o segredo — chave mestra incorreta "
            "ou dado corrompido."
        ) from exc
