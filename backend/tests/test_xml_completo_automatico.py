"""
O caminho completo, sem ninguém tocar em nada: do `resNFe` ao `procNFe`.

Este é o teste do sintoma relatado em produção: o cliente tem a chave e o
certificado A1 no sistema, mas o que aparecia no acervo era o **resumo da
distribuição** (`resNFe` — chave, emitente, valor e protocolo; sem item,
imposto ou total), e a nota ainda era marcada como "completo", saindo da fila
para sempre.

O que o robô faz, e o que este teste trava:

1. o lote pode trazer só `resNFe`; ele é gravado como **resumo** — nunca como a
   nota — e a nota entra na fila de completar;
2. o worker registra a **Ciência da Operação** (210210) com o A1 da empresa — é
   o que a norma exige para o Ambiente Nacional liberar o documento inteiro;
3. com a Ciência registrada, o `consChNFe` devolve o `procNFe` e o arquivo do
   acervo é substituído, mantendo o mesmo caminho e a proveniência;
4. se a Ciência chegar tarde (cStat 596), a nota não fica tentando para sempre:
   o motivo e o código ficam gravados, e a saída passa a ser o evento conclusivo.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Certificado, DocumentoFiscal, Empresa, Escritorio, TipoDocumentoFiscal
from app.services import sincronizacao
from app.services.importadores.base import DocumentoBaixado
from app.services.importadores.manifestacao import ManifestacaoRecusada, ResultadoManifestacao

NFE = TipoDocumentoFiscal.NFE
CHAVE = "31260907485646000155550010000602201187626989"
CNPJ = "12345678000199"

RES_NFE = f"""<resNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
  <chNFe>{CHAVE}</chNFe><CNPJ>07485646000155</CNPJ>
  <xNome>MADEIREIRA NORTE SUL LTDA</xNome><vNF>2261.84</vNF>
  <dhRecbto>2026-09-15T15:08:10-03:00</dhRecbto><nProt>131267911602091</nProt>
</resNFe>""".encode()

PROC_NFE = f"""<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe><infNFe Id="NFe{CHAVE}" versao="4.00">
    <ide><nNF>6022</nNF><serie>1</serie><dhEmi>2026-09-15T00:00:00-03:00</dhEmi></ide>
    <emit><CNPJ>07485646000155</CNPJ><xNome>MADEIREIRA NORTE SUL LTDA</xNome></emit>
    <dest><CNPJ>{CNPJ}</CNPJ><xNome>EMPRESA CLIENTE</xNome></dest>
    <total><ICMSTot><vNF>2261.84</vNF></ICMSTot></total>
  </infNFe></NFe>
  <protNFe versao="4.00"><infProt><chNFe>{CHAVE}</chNFe><cStat>100</cStat>
  </infProt></protNFe>
</nfeProc>""".encode()


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()
    escritorio = Escritorio(nome="Escritório Teste")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="Empresa Teste",
        cnpj_cpf=CNPJ,
        uf="MG",
    )
    sessao.add(empresa)
    sessao.commit()
    yield sessao, empresa.id
    sessao.close()


def _documento_baixado(xml: bytes, leiaute: str) -> DocumentoBaixado:
    return DocumentoBaixado(
        chave_acesso=CHAVE,
        nsu="42",
        xml=xml,
        data_emissao="2026-09-15T00:00:00-03:00",
        valor_total=2261.84,
        direcao="tomada",
        competencia="2026-09-01",
        leiaute=leiaute,
        numero="6022",
        serie="1",
    )


@pytest.fixture
def ambiente(db, monkeypatch, tmp_path):
    """Empresa com A1 ativo e um resumo na fila, como sai da distribuição."""
    sessao, empresa_id = db
    caminho = tmp_path / "nota.xml"
    caminho.write_bytes(RES_NFE)
    sessao.add(
        Certificado(
            empresa_id=empresa_id,
            arquivo_path=str(tmp_path / "fake.pfx"),
            senha_cifrada="fake",
            validade=datetime.now(timezone.utc) + timedelta(days=30),
            ativo=True,
        )
    )
    sessao.add(
        DocumentoFiscal(
            empresa_id=empresa_id,
            tipo=NFE,
            direcao="tomada",
            chave_acesso=CHAVE,
            nsu="42",
            data_emissao=datetime.now(timezone.utc) - timedelta(days=1),
            competencia=datetime.now(timezone.utc).date(),
            valor_total=2261.84,
            xml_path=str(caminho),
            leiaute="resumo",
        )
    )
    sincronizacao.obter_estado(sessao, empresa_id, NFE)
    sessao.commit()

    from app.worker import tasks

    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=sessao.get_bind()))
    monkeypatch.setattr(tasks, "decifrar_segredo", lambda _: "senha")
    monkeypatch.setattr(tasks, "ler_pfx_protegido", lambda _: b"pfx")
    monkeypatch.setattr(tasks, "sessao_mtls", _sessao_falsa)
    monkeypatch.setattr(tasks, "ESPERA_ENTRE_LOTES", 0)
    return sessao, empresa_id, caminho, tasks


class _sessao_falsa:
    """mTLS real exigiria um A1; aqui só os caminhos que o importador usaria."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return "/tmp/cert.pem", "/tmp/key.pem"

    def __exit__(self, *args):
        return False


def test_resumo_nao_vira_completo_e_e_promovido_pelo_worker(ambiente):
    """O fluxo feliz: manifesta (Ciência), consulta pela chave, promove a nota."""
    sessao, empresa_id, caminho, tasks = ambiente
    chamadas = {"manifestou": 0, "chaves": []}

    def manifestar_falso(**kwargs):
        chamadas["manifestou"] += 1
        assert kwargs["cnpj"] == CNPJ
        return ResultadoManifestacao(True, "135", "Evento registrado", "143120001872811")

    class ImportadorFalso:
        def buscar_por_chave(self, **kwargs):
            chamadas["chaves"].append(kwargs["chave_acesso"])
            return _documento_baixado(PROC_NFE, "completo")

    monkeypatch_manifestar = manifestar_falso
    tasks.manifestar_ciencia = monkeypatch_manifestar
    tasks.obter_importador = lambda tipo: ImportadorFalso()

    resultado = tasks.completar_xmls_pendentes()

    assert resultado["completos"] == 1
    assert chamadas["manifestou"] == 1, "sem Ciência a SEFAZ nunca libera o XML completo"
    assert chamadas["chaves"] == [CHAVE]

    sessao.expire_all()
    documento = sessao.query(DocumentoFiscal).one()
    assert documento.leiaute == "completo"
    assert documento.manifestado_em is not None
    assert documento.manifestacao_erro is None
    assert b"infNFe" in caminho.read_bytes()
    assert b"resNFe" not in caminho.read_bytes()


def test_segunda_rodada_nao_manifesta_de_novo(ambiente):
    """Ciência é irreversível e duplicidade (573) só deve acontecer por atraso."""
    sessao, empresa_id, caminho, tasks = ambiente
    manifestacoes = {"total": 0}

    def manifestar_falso(**kwargs):
        manifestacoes["total"] += 1
        return ResultadoManifestacao(True, "135", "Evento registrado", "1")

    class ImportadorFalso:
        def buscar_por_chave(self, **kwargs):
            return _documento_baixado(PROC_NFE, "completo")

    tasks.manifestar_ciencia = manifestar_falso
    tasks.obter_importador = lambda tipo: ImportadorFalso()
    tasks.completar_xmls_pendentes()
    # Já está completa: sai da fila e nem manifesta nem consulta de novo.
    resultado = tasks.completar_xmls_pendentes()

    assert manifestacoes["total"] == 1
    assert resultado["completos"] == 0
    assert resultado["empresas"] == 0


def test_sefaz_devolveu_resumo_na_consulta_nao_estraga_o_acervo(ambiente):
    """Última linha de defesa: `consChNFe` só libera resumo até a manifestação."""
    sessao, empresa_id, caminho, tasks = ambiente
    tasks.manifestar_ciencia = lambda **kwargs: ResultadoManifestacao(True, "135", "ok", "1")

    class ImportadorFalso:
        def buscar_por_chave(self, **kwargs):
            # Rotulado como completo de propósito: é o cenário que corrompia o
            # acervo (o resumo era gravado por cima da nota e saía da fila).
            return _documento_baixado(RES_NFE, "completo")

    tasks.obter_importador = lambda tipo: ImportadorFalso()
    resultado = tasks.completar_xmls_pendentes()

    assert resultado["completos"] == 0
    assert resultado["indisponiveis"] == 1
    sessao.expire_all()
    documento = sessao.query(DocumentoFiscal).one()
    assert documento.leiaute == "resumo"  # continua na fila para a próxima rodada
    assert caminho.read_bytes() == RES_NFE  # o arquivo não foi tocado
    assert documento.tentativas_completar == 1  # e a cota foi contabilizada


def test_ciencia_fora_do_prazo_596_para_de_tentar_e_explica_a_saida(ambiente):
    """Passados os 10 dias, repetir a Ciência é inútil: só o evento conclusivo."""
    sessao, empresa_id, caminho, tasks = ambiente
    consultas = {"total": 0}

    def manifestar_recusado(**kwargs):
        raise ManifestacaoRecusada("Rejeicao: Evento apresentado fora do prazo", cstat="596")

    class ImportadorFalso:
        def buscar_por_chave(self, **kwargs):  # pragma: no cover - não deve ser chamado
            consultas["total"] += 1
            return None

    tasks.manifestar_ciencia = manifestar_recusado
    tasks.obter_importador = lambda tipo: ImportadorFalso()
    resultado = tasks.completar_xmls_pendentes()

    assert resultado["manifestacao_recusada"] == 1
    assert consultas["total"] == 0, "nota sem Ciência não tem o que buscar pela chave"

    sessao.expire_all()
    documento = sessao.query(DocumentoFiscal).one()
    assert documento.manifestacao_cstat == "596"
    assert "conclusiva" in documento.manifestacao_erro
    assert documento.leiaute == "resumo"
    # Não volta para a fila: o robô não tem o que fazer aqui — quem decide o
    # evento conclusivo é o operador (é ato de negócio).
    assert tasks.completar_xmls_pendentes()["empresas"] == 0
