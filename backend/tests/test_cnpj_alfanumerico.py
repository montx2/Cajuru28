"""CNPJ alfanumérico é identificador: letras não podem desaparecer."""

from __future__ import annotations

import pytest

from app.core.documentos import normalizar_cnpj, normalizar_documento, validar_cnpj
from app.schemas import EmpresaCriar, JettaxImportarNFe
from app.services.cnpj import consultar_cnpj
from app.services.jettax import ClienteJettax, JettaxErro

CNPJ_ALFA = "ABCDEF12345680"  # DV calculado conforme regra RFB alfanumérica


def test_normalizacao_preserva_letras_mas_remove_somente_mascara():
    assert validar_cnpj(CNPJ_ALFA)
    assert normalizar_cnpj("ab.cd-ef/123456-80") == CNPJ_ALFA
    assert normalizar_documento("ab.cd-ef/123456-80") == CNPJ_ALFA
    assert EmpresaCriar(cnpj_cpf="ab.cd-ef/123456-80", razao_social="Alfa", uf="MG").cnpj_cpf == CNPJ_ALFA


@pytest.mark.parametrize("valor", ["ABCDEF1234567X", "ABCDEF12345680!", "ABCDEF1234568"])
def test_normalizacao_nao_faz_fallback_destrutivo_para_digitos(valor):
    with pytest.raises(ValueError):
        normalizar_documento(valor)


def test_brasilapi_nao_recebe_cnpj_alfanumerico(monkeypatch):
    class ClienteQueNaoPodeSerUsado:
        def __enter__(self):
            raise AssertionError("fonte pública não deveria ser chamada")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("app.services.cnpj.httpx.Client", lambda **_kwargs: ClienteQueNaoPodeSerUsado())
    assert consultar_cnpj(CNPJ_ALFA) is None


def test_jettax_recusa_cnpj_alfanumerico_antes_da_requisicao():
    cliente = ClienteJettax(token="segredo-somente-teste")
    with pytest.raises(JettaxErro) as erro:
        cliente.listar_nfse(CNPJ_ALFA)
    assert erro.value.categoria == "contrato"
    assert "alfanumérico" in str(erro.value)


def test_filtro_jettax_preserva_alfa_e_o_cliente_recusa_contrato_nao_confirmado():
    filtros = JettaxImportarNFe(direcao="sales", cnpj_emitente="ab.cd-ef/123456-80")
    assert filtros.cnpj_emitente == CNPJ_ALFA
    with pytest.raises(JettaxErro, match="alfanumérico"):
        ClienteJettax(token="segredo-somente-teste").listar_nfes(
            "12345678000195", "sales", cnpj_emitente=filtros.cnpj_emitente
        )
