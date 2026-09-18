"""Fluxo completo do worker de importação (sem Celery/Redis): pfx → mTLS → ADN → banco."""

import base64
import gzip
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import respx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import config
from app.core.vault import cifrar_segredo
from app.db.base import Base
from app.models import (
    Certificado,
    DocumentoFiscal,
    Empresa,
    Escritorio,
    ExecucaoImportacao,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.worker import tasks

SENHA = "senha-do-certificado-fake"
CNPJ = "12345678000199"


def _gerar_pfx() -> bytes:
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
    return pkcs12.serialize_key_and_certificates(
        name=b"empresa-teste",
        key=chave,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(SENHA.encode()),
    )


def _xml_nfse(
    chave: str = "35260112345678000199550010000000011234567890",
    emissao: str = "2026-01-05T09:00:00-03:00",
) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <infNFSe Id="NFS{chave}">
    <DPS><infDPS>
      <dhEmi>{emissao}</dhEmi>
      <prest><CNPJ>99999999000188</CNPJ></prest>
      <valores><vLiq>100.50</vLiq></valores>
    </infDPS></DPS>
  </infNFSe>
</NFSe>"""


@respx.mock
def test_worker_importa_nota_do_adn_e_grava_xml(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="KR SERVICOS MEDICOS LTDA",
        cnpj_cpf=CNPJ,
        uf="SP",
    )
    sessao.add(empresa)
    sessao.flush()

    pfx = _gerar_pfx()
    caminho_pfx = tmp_path / "certificado.pfx"
    caminho_pfx.write_bytes(pfx)

    certificado = Certificado(
        empresa_id=empresa.id,
        arquivo_path=str(caminho_pfx),
        senha_cifrada=cifrar_segredo(SENHA),
        validade=datetime.now(timezone.utc) + timedelta(days=365),
        ativo=True,
    )
    sessao.add(certificado)
    sessao.flush()

    execucao = ExecucaoImportacao(
        empresa_id=empresa.id, tipo=TipoDocumentoFiscal.NFSE
    )
    sessao.add(execucao)
    sessao.commit()

    # Worker usa SessionLocal global — aponta para o banco de teste
    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=engine))

    item = {
        "NSU": 42,
        "ChaveAcesso": "35260112345678000199550010000000011234567890",
        "ArquivoXml": base64.b64encode(gzip.compress(_xml_nfse().encode())).decode(),
        "TipoDocumento": "NFSE",
    }
    respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(
            200, json={"LoteDFe": [item], "UltNSU": 42, "MaxNSU": 42}
        )
    )

    tasks.importar_documentos(empresa.id, "nfse", execucao.id)

    sessao.refresh(execucao)
    assert execucao.status == StatusExecucao.CONCLUIDA
    assert execucao.documentos_importados == 1
    assert execucao.ultimo_nsu == "42"

    documento = sessao.query(DocumentoFiscal).one()
    assert documento.chave_acesso == "35260112345678000199550010000000011234567890"
    assert (tmp_path / "xml" / str(empresa.id) / "nfse" / f"{documento.chave_acesso}.xml").exists()
    sessao.close()


def _montar_cenario(tmp_path, monkeypatch, sessao_engine=None):
    """Empresa + certificado + worker apontando para um banco de teste."""
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))
    engine = sessao_engine or create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="KR SERVICOS MEDICOS LTDA",
        cnpj_cpf=CNPJ,
        uf="SP",
    )
    sessao.add(empresa)
    sessao.flush()

    caminho_pfx = tmp_path / "certificado.pfx"
    caminho_pfx.write_bytes(_gerar_pfx())
    sessao.add(
        Certificado(
            empresa_id=empresa.id,
            arquivo_path=str(caminho_pfx),
            senha_cifrada=cifrar_segredo(SENHA),
            validade=datetime.now(timezone.utc) + timedelta(days=365),
            ativo=True,
        )
    )
    sessao.commit()
    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=engine))
    return sessao, empresa


def _item_adn(nsu: int, chave: str, emissao: str) -> dict:
    return {
        "NSU": nsu,
        "ChaveAcesso": chave,
        "ArquivoXml": base64.b64encode(
            gzip.compress(_xml_nfse(chave, emissao).encode())
        ).decode(),
        "TipoDocumento": "NFSE",
    }


@respx.mock
def test_worker_descarta_o_que_esta_fora_do_periodo_pedido(tmp_path, monkeypatch):
    """
    O pedido foi 01/08/2026 a 31/08/2026; a distribuição, que só anda por NSU,
    devolve junho, julho e agosto no mesmo lote.

    Só agosto pode virar linha no banco e arquivo em disco — esse é o ponto
    inteiro do filtro. Os outros dois são contados em
    `documentos_fora_do_periodo` para a execução conseguir explicar a diferença
    entre "a SEFAZ mandou 3" e "guardei 1".
    """
    sessao, empresa = _montar_cenario(tmp_path, monkeypatch)

    execucao = ExecucaoImportacao(
        empresa_id=empresa.id,
        tipo=TipoDocumentoFiscal.NFSE,
        data_inicio=date(2026, 8, 1),
        data_fim=date(2026, 8, 31),
    )
    sessao.add(execucao)
    sessao.commit()

    chave_junho = "35260612345678000199550010000000066666666666"
    chave_julho = "35260712345678000199550010000000077777777777"
    chave_agosto = "35260812345678000199550010000000088888888888"
    lote = [
        _item_adn(40, chave_junho, "2026-06-10T09:00:00-03:00"),
        _item_adn(41, chave_julho, "2026-07-20T09:00:00-03:00"),
        _item_adn(42, chave_agosto, "2026-08-15T09:00:00-03:00"),
    ]
    respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(200, json={"LoteDFe": lote, "UltNSU": 42, "MaxNSU": 42})
    )

    tasks.importar_documentos(empresa.id, "nfse", execucao.id)

    sessao.refresh(execucao)
    assert execucao.status == StatusExecucao.CONCLUIDA
    assert execucao.documentos_importados == 1
    assert execucao.documentos_fora_do_periodo == 2
    assert "2 documento(s) fora do período 08/2026" in (execucao.aviso or "")

    guardados = sessao.query(DocumentoFiscal).all()
    assert [documento.chave_acesso for documento in guardados] == [chave_agosto]

    # nada de XML órfão em disco para as notas descartadas
    pasta = tmp_path / "xml" / str(empresa.id) / "nfse"
    assert sorted(arquivo.name for arquivo in pasta.iterdir()) == [f"{chave_agosto}.xml"]

    # o cursor avança até o fim do lote: descartar conteúdo nunca faz o sistema
    # reconsultar os mesmos NSUs (e gastar a janela de 1h) na próxima rodada
    assert execucao.ultimo_nsu == "42"
    sessao.close()


@respx.mock
def test_execucao_sem_periodo_continua_guardando_tudo(tmp_path, monkeypatch):
    """
    Compatibilidade: execuções antigas (e as do agendador) não têm período
    gravado. Sem período não há o que recortar — filtrar "por via das dúvidas"
    apagaria notas de quem já usava o sistema antes desta versão.
    """
    sessao, empresa = _montar_cenario(tmp_path, monkeypatch)
    execucao = ExecucaoImportacao(empresa_id=empresa.id, tipo=TipoDocumentoFiscal.NFSE)
    sessao.add(execucao)
    sessao.commit()

    lote = [
        _item_adn(41, "35260712345678000199550010000000077777777777", "2026-07-20T09:00:00-03:00"),
        _item_adn(42, "35260812345678000199550010000000088888888888", "2026-08-15T09:00:00-03:00"),
    ]
    respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(200, json={"LoteDFe": lote, "UltNSU": 42, "MaxNSU": 42})
    )

    tasks.importar_documentos(empresa.id, "nfse", execucao.id)

    sessao.refresh(execucao)
    assert execucao.documentos_importados == 2
    assert execucao.documentos_fora_do_periodo == 0
    sessao.close()
