"""Decodificação do `ArquivoXml` do ADN: o XML salvo tem que ser A NOTA.

Cenário real que motivou esta suíte: o escritório exporta os XMLs e o
sistema contábil rejeita com "arquivo de autorização do uso da NF-e" /
"não é um arquivo NF-e válido". O XML gravado precisa ser sempre o
documento fiscal (NFS-e nacional com a DPS dentro), nunca um auxiliar
(recibo, protocolo, DANFSe) que venha embalado junto no mesmo pacote.
"""

import base64
import gzip
import io
import zipfile

import pytest

from app.services.importadores.nfse_adn import decodificar_xml_adn

XML_NFSE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse" versao="1.01">'
    '<infNFSe Id="NFS31338081211025402000167000000001007226091788367242">'
    "<nNFSe>10072</nNFSe>"
    "<DPS><infDPS Id=\"DPS313380821102540200016770002000000000010072\">"
    "<serie>70002</serie><nDPS>10072</nDPS>"
    "</infDPS></DPS>"
    "</infNFSe></NFSe>"
).encode("utf-8")

# Auxiliares que provedores já empacotaram junto da nota — nenhum deles é
# documento fiscal e nenhum pode ser entregue no lugar da NFS-e.
XML_RECIBO = b"<?xml version='1.0'?><recibo><nRec>999</nRec></recibo>"
XML_PROTOCOLO = b"<?xml version='1.0'?><protNFe><infProt><cStat>100</cStat></infProt></protNFe>"


def _gzip_b64(dados: bytes) -> str:
    return base64.b64encode(gzip.compress(dados)).decode("ascii")


def _zip(*membros: tuple[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as pacote:
        for nome, dados in membros:
            pacote.writestr(nome, dados)
    return buffer.getvalue()


def test_xml_puro_passa_direto():
    assert decodificar_xml_adn(XML_NFSE) == XML_NFSE


def test_string_xml_pura_passa_direto():
    assert decodificar_xml_adn(XML_NFSE.decode("utf-8")) == XML_NFSE


def test_base64_gzip_formato_padrao_do_adn():
    assert decodificar_xml_adn(_gzip_b64(XML_NFSE)) == XML_NFSE


def test_base64_sem_gzip():
    assert decodificar_xml_adn(base64.b64encode(XML_NFSE).decode("ascii")) == XML_NFSE


def test_zip_com_um_unico_membro_devolve_a_nota():
    assert decodificar_xml_adn(_zip(("10072.xml", XML_NFSE))) == XML_NFSE


def test_zip_com_auxiliar_antes_da_nota_entrega_a_nota():
    # O bug: "primeiro membro do ZIP" devolvia o recibo, não a NFS-e.
    pacote = _zip(("recibo.xml", XML_RECIBO), ("10072.xml", XML_NFSE))
    assert decodificar_xml_adn(pacote) == XML_NFSE


def test_zip_com_protocolo_antes_da_nota_entrega_a_nota():
    pacote = _zip(("prot.xml", XML_PROTOCOLO), ("10072.xml", XML_NFSE))
    assert decodificar_xml_adn(pacote) == XML_NFSE


def test_zip_sem_documento_conhecido_mantem_o_primeiro():
    # Nada reconhecível: não é papel da decodicação decidir — devolve o
    # primeiro para o conversor apontar o erro com o NSU certo.
    pacote = _zip(("a.xml", XML_RECIBO), ("b.xml", XML_PROTOCOLO))
    assert decodificar_xml_adn(pacote) == XML_RECIBO


def test_zip_vazio_e_recusado_com_erro_claro():
    with pytest.raises(ValueError, match="ZIP vazio"):
        decodificar_xml_adn(_zip())


def test_lixo_que_nao_e_nada_conhecido_e_recusado():
    with pytest.raises(ValueError):
        decodificar_xml_adn(base64.b64encode(b"conteudo binario sem xml").decode("ascii"))


def test_zip_dentro_de_gzip_do_adn():
    # Formato composto: ADN embala em gzip+base64 um ZIP de vários membros.
    pacote = _gzip_b64(_zip(("recibo.xml", XML_RECIBO), ("10072.xml", XML_NFSE)))
    assert decodificar_xml_adn(pacote) == XML_NFSE
