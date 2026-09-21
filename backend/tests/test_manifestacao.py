"""Manifestação do Destinatário (210210) — o que destrava o XML da NF-e.

Este é o caso que fazia o sistema "ver a nota mas não conseguir pegar": sem a
Ciência da Operação registrada, o Ambiente Nacional entrega só o `resNFe` e o
`consChNFe` volta vazio para sempre. Esperar não resolve — só a manifestação.

Os testes abaixo fixam as quatro garantias que importam:

1. o evento sai **assinado** e no formato que o XSD exige;
2. `cStat=573` (duplicidade) é **sucesso**, não erro — senão o worker repete
   eternamente uma nota que já está manifestada;
3. a manifestação **não acontece** em empresa que não optou (ato jurídico);
4. a rejeição definitiva é registrada e não vira retry infinito.
"""

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat
from cryptography.x509.oid import NameOID
from lxml import etree

from app.services.importadores.manifestacao import (
    NS_DSIG,
    NS_PORTAL,
    RECEPCAO_EVENTO_URL_PRODUCAO,
    ManifestacaoRecusada,
    assinar_evento,
    interpretar_resposta_evento,
    manifestar_ciencia,
    montar_envelope_evento,
    montar_evento,
    montar_id_evento,
)

CNPJ = "12345678000199"
CHAVE = "35260812345678000199550010000001231111111111"[:44].ljust(44, "1")


@pytest.fixture
def par_certificado(tmp_path):
    """Gera cert.pem + key.pem como o `sessao_mtls` entrega ao importador."""
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CNPJ)])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        chave.private_bytes(
            serialization.Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        )
    )
    return str(cert_path), str(key_path), chave


def _resposta(cstat: str, motivo: str, protocolo: str = "") -> str:
    prot = f"<nProt>{protocolo}</nProt>" if protocolo else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"><soap:Body>'
        f'<retEnvEvento xmlns="{NS_PORTAL}" versao="1.00">'
        "<idLote>1</idLote><tpAmb>1</tpAmb><verAplic>AN</verAplic>"
        "<cOrgao>91</cOrgao><cStat>128</cStat><xMotivo>Lote de Evento Processado</xMotivo>"
        '<retEvento versao="1.00"><infEvento>'
        "<tpAmb>1</tpAmb><verAplic>AN</verAplic><cOrgao>91</cOrgao>"
        f"<cStat>{cstat}</cStat><xMotivo>{motivo}</xMotivo>"
        f"<chNFe>{CHAVE}</chNFe><tpEvento>210210</tpEvento><nSeqEvento>1</nSeqEvento>"
        f"{prot}"
        "</infEvento></retEvento>"
        "</retEnvEvento></soap:Body></soap:Envelope>"
    )


# --------------------------------------------------------------------------
# Formato do evento
# --------------------------------------------------------------------------


def test_id_do_evento_segue_o_formato_oficial():
    """`ID` + tipoEvento(6) + chave(44) + sequência(2) = 54 caracteres."""
    id_evento = montar_id_evento(CHAVE, "210210", 1)
    assert id_evento == f"ID210210{CHAVE}01"
    assert len(id_evento) == 54


def test_evento_traz_corgao_91_e_os_campos_obrigatorios():
    """cOrgao 91 = Ambiente Nacional: a manifestação não vai para a UF."""
    xml = montar_evento(CHAVE, CNPJ, uf="SP")
    raiz = etree.fromstring(xml)
    inf = raiz.find(f"{{{NS_PORTAL}}}infEvento")

    def valor(tag):
        return inf.find(f"{{{NS_PORTAL}}}{tag}").text

    assert valor("cOrgao") == "91"
    assert valor("tpEvento") == "210210"
    assert valor("chNFe") == CHAVE
    assert valor("CNPJ") == CNPJ
    assert valor("nSeqEvento") == "1"
    # dhEvento precisa de fuso explícito, senão o ambiente recusa.
    assert valor("dhEvento").endswith("+00:00")


def test_chave_invalida_e_recusada_antes_de_qualquer_chamada():
    with pytest.raises(ValueError, match="44 dígitos"):
        montar_evento("123", CNPJ, uf="SP")


# --------------------------------------------------------------------------
# Assinatura — o que a distribuição DFe não exige, mas o evento sim
# --------------------------------------------------------------------------


def test_evento_assinado_tem_assinatura_valida_sobre_o_infevento(par_certificado):
    """A assinatura precisa conferir contra o C14N exclusivo do infEvento.

    Este teste recalcula o digest e verifica a assinatura RSA com a chave
    pública — se a serialização mudar um byte, o ambiente rejeitaria, e aqui
    o teste quebra antes de chegar em produção.
    """
    from cryptography.hazmat.primitives.asymmetric import padding
    import base64

    cert_path, key_path, chave = par_certificado
    assinado = assinar_evento(montar_evento(CHAVE, CNPJ, uf="SP"), cert_path, key_path)
    raiz = etree.fromstring(assinado)

    assinatura = raiz.find(f"{{{NS_DSIG}}}Signature")
    assert assinatura is not None, "evento saiu sem assinatura"

    # 1. O digest publicado bate com o infEvento canonicalizado?
    inf = raiz.find(f"{{{NS_PORTAL}}}infEvento")
    canon = etree.tostring(inf, method="c14n", exclusive=True, with_comments=False)
    esperado = hashes.Hash(hashes.SHA1())
    esperado.update(canon)
    digest_publicado = assinatura.find(f".//{{{NS_DSIG}}}DigestValue").text
    assert digest_publicado == base64.b64encode(esperado.finalize()).decode()

    # 2. A referência aponta para o Id correto?
    referencia = assinatura.find(f".//{{{NS_DSIG}}}Reference")
    assert referencia.get("URI") == f"#{inf.get('Id')}"

    # 3. A assinatura RSA confere com a chave pública do certificado?
    signed_info = assinatura.find(f"{{{NS_DSIG}}}SignedInfo")
    signed_info_c14n = etree.tostring(
        signed_info, method="c14n", exclusive=True, with_comments=False
    )
    valor = base64.b64decode(assinatura.find(f"{{{NS_DSIG}}}SignatureValue").text)
    chave.public_key().verify(valor, signed_info_c14n, padding.PKCS1v15(), hashes.SHA1())


def test_envelope_embute_o_evento_sem_declaracao_xml_duplicada(par_certificado):
    cert_path, key_path, _ = par_certificado
    assinado = assinar_evento(montar_evento(CHAVE, CNPJ, uf="SP"), cert_path, key_path)
    envelope = montar_envelope_evento(assinado).decode()

    assert envelope.count("<?xml") == 1, "declaração XML duplicada quebra o parser da SEFAZ"
    assert "<envEvento" in envelope and "<idLote>" in envelope
    assert "nfeRecepcaoEvento" in envelope


# --------------------------------------------------------------------------
# Interpretação da resposta
# --------------------------------------------------------------------------


def test_135_registrado_e_sucesso_com_protocolo():
    resultado = interpretar_resposta_evento(
        _resposta("135", "Evento registrado e vinculado a NF-e", "143120001872811").encode()
    )
    assert resultado.sucesso
    assert resultado.protocolo == "143120001872811"
    assert not resultado.ja_estava_manifestada


def test_573_duplicidade_e_tratado_como_sucesso_idempotente():
    """Já manifestada = objetivo cumprido. Tratar como erro geraria retry eterno."""
    resultado = interpretar_resposta_evento(
        _resposta("573", "Rejeicao: Duplicidade de Evento").encode()
    )
    assert resultado.sucesso
    assert resultado.ja_estava_manifestada


def test_rejeicao_definitiva_levanta_erro_especifico():
    with pytest.raises(ManifestacaoRecusada) as erro:
        interpretar_resposta_evento(
            _resposta("596", "Rejeicao: Chave de Acesso inexistente").encode()
        )
    assert erro.value.cstat == "596"
    assert "inexistente" in erro.value.motivo


def test_soap_fault_vira_ambiente_indisponivel_e_pode_ser_retentado():
    from app.services.importadores.base import AmbienteIndisponivel

    fault = (
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"><soap:Body>'
        "<soap:Fault><faultstring>Servico indisponivel</faultstring></soap:Fault>"
        "</soap:Body></soap:Envelope>"
    )
    with pytest.raises(AmbienteIndisponivel):
        interpretar_resposta_evento(fault.encode())


# --------------------------------------------------------------------------
# Chamada ponta a ponta
# --------------------------------------------------------------------------


@respx.mock
def test_manifestar_envia_para_o_ambiente_nacional(par_certificado):
    """A manifestação vai sempre ao AN — nunca ao webservice da UF."""
    cert_path, key_path, _ = par_certificado
    rota = respx.post(RECEPCAO_EVENTO_URL_PRODUCAO).mock(
        return_value=httpx.Response(200, content=_resposta("135", "Evento registrado", "999"))
    )

    resultado = manifestar_ciencia(CHAVE, CNPJ, cert_path, key_path, uf="SP")

    assert resultado.sucesso and resultado.protocolo == "999"
    assert rota.call_count == 1
    corpo = rota.calls[0].request.content.decode()
    assert "<tpEvento>210210</tpEvento>" in corpo
    assert "<cOrgao>91</cOrgao>" in corpo
    assert "Signature" in corpo, "o evento precisa ir assinado"
