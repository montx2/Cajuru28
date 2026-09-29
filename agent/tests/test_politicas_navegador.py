from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from cajuru_agent.certificados import CertificadoLocal
from cajuru_agent.human_gate import TipoHumanGate, classificar_intervencao
from cajuru_agent import politicas_navegador as pol


def _cert(**kwargs) -> CertificadoLocal:
    agora = datetime.now(timezone.utc)
    base = {
        "thumbprint": "a" * 64,
        "documento": "12345678000195",
        "titular_nome": "PADARIA AURORA LTDA",
        "subject": "CN=PADARIA AURORA LTDA:12345678000195, OU=RFB e-CNPJ A1, O=ICP-Brasil",
        "issuer": "CN=AC SERPRO RFB v5, O=ICP-Brasil",
        "numero_serie": "01",
        "valido_de": (agora - timedelta(days=1)).isoformat(),
        "valido_ate": (agora + timedelta(days=30)).isoformat(),
        "origem": "windows_store",
        "referencia_local": "CurrentUser\\My:" + "a" * 64,
        "tem_chave_privada": True,
    }
    base.update(kwargs)
    return CertificadoLocal(**base)


def test_regra_autoselect_usa_subject_e_issuer_do_certificado():
    regra = pol.gerar_politica(_cert(), navegador="edge", padroes=["https://sso.acesso.gov.br"]).regras[0]
    payload = json.loads(regra.para_json())

    assert payload["pattern"] == "https://sso.acesso.gov.br"
    assert payload["filter"]["SUBJECT"]["CN"].startswith("PADARIA AURORA")
    assert payload["filter"]["ISSUER"]["CN"] == "AC SERPRO RFB v5"


def test_selecao_de_certificado_falha_fechado_em_ambiguidade():
    certificados = [_cert(thumbprint="a" * 64), _cert(thumbprint="b" * 64)]
    with pytest.raises(pol.PoliticaNavegadorError) as erro:
        pol.selecionar_certificado_unico(certificados, "12.345.678/0001-95")

    assert "Mais de um certificado" in str(erro.value)


def test_classificacao_de_human_gate():
    assert classificar_intervencao("apareceu reCAPTCHA").tipo is TipoHumanGate.CAPTCHA_REQUIRED
    assert classificar_intervencao("gov.br pediu código SMS").tipo is TipoHumanGate.TWO_FACTOR_REQUIRED
    assert classificar_intervencao("janela pediu PIN do certificado").tipo is TipoHumanGate.PIN_REQUIRED
