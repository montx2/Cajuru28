from cryptography.fernet import Fernet
import pytest

from app.core import vault
from app.core.vault import cifrar_segredo, decifrar_segredo


def test_cifrar_e_decifrar_devolve_o_texto_original():
    senha_original = "S3nh4-Do-Certificado!"
    cifrado = cifrar_segredo(senha_original)

    assert cifrado != senha_original  # nunca em texto puro
    assert decifrar_segredo(cifrado) == senha_original


def test_texto_cifrado_nao_e_reutilizavel_como_texto_puro():
    cifrado = cifrar_segredo("outra-senha")
    # Garante que o valor gravado no banco não é, por acidente, legível.
    assert "outra-senha" not in cifrado


def test_decifra_certificado_com_chave_anterior_durante_rotacao(monkeypatch):
    chave_anterior = Fernet.generate_key().decode()
    chave_nova = Fernet.generate_key().decode()
    cifrado_antigo = Fernet(chave_anterior.encode()).encrypt(b"senha-antiga").decode()

    monkeypatch.setattr(vault.settings, "vault_master_key", chave_nova)
    monkeypatch.setattr(vault.settings, "vault_previous_master_keys", chave_anterior)

    assert vault.decifrar_segredo(cifrado_antigo) == "senha-antiga"
    # A escrita sempre usa a chave nova, nunca uma chave de recuperação.
    assert Fernet(chave_nova.encode()).decrypt(vault.cifrar_segredo("senha-nova").encode()) == b"senha-nova"


def test_decifrar_valor_invalido_indica_como_recuperar_certificado():
    with pytest.raises(vault.SegredoIndecifravelError, match="envie o .pfx novamente"):
        decifrar_segredo("isto-nao-e-um-token-fernet-valido")
