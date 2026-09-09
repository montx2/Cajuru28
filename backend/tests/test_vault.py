import pytest

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


def test_decifrar_valor_invalido_levanta_erro_claro():
    with pytest.raises(ValueError):
        decifrar_segredo("isto-nao-e-um-token-fernet-valido")
