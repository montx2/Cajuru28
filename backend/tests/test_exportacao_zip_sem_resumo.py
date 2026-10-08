"""O pacote de exportação só leva NOTA — e diz o que ficou de fora.

## O problema que estes testes travam

O operador baixava o ZIP do período, mandava para o sistema contábil e o
importador respondia "isto é uma autorização de nota". O motivo: o pacote
levava `resNFe`/`protNFe` **na mesma pasta** das NF-e, todos com o nome
`<chave>.xml`, indistinguíveis a olho nu. E não dava para descobrir qual era o
culpado sem abrir arquivo por arquivo.

O cadastro não resolve: no legado há linha marcada `leiaute = "completo"` com
um `resNFe` no disco (herança do `consChNFe` que devolvia resumo). Por isso a
classificação é pelo CONTEÚDO do arquivo — a mesma autoridade de
`app.services.xml_integridade` que o resto do sistema usa.

## O contrato que vale daqui para frente

1. `Fluxa/<empresa>/<tipo>/` contém **só** XML com `infNFe`/`infCTe`/`infNFSe`;
2. o que ficou de fora vai para `Fluxa/pendencias.csv`, com motivo e "o que
   fazer" (inclusive cStat 596 → "Manifestar operação");
3. `relacao.csv` continua listando TUDO, com `xml_completo` dizendo a verdade;
4. `incluir_incompletos=true` manda os incompletos para
   `Fluxa/_sem-xml-completo/` — nunca misturados com as notas;
5. `EstimativaExportacao.sem_xml_completo` avisa a tela antes do clique.
"""

import io
import zipfile
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.core import config
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    DocumentoFiscal,
    Empresa,
    Escritorio,
    RegistroAuditoria,
    StatusDocumentoFiscal,
    TipoDocumentoFiscal,
    Usuario,
)

EMPRESA = "ARM LOGISTICA E TRANSPORTES LTD"
PASTA_EMPRESA = "Fluxa/ARM-LOGISTICA-E-TRANSPORTES-LTD"

# Chaves distintas para cada cenário — o teste identifica o documento pela
# cauda da chave, que é o que aparece no nome do arquivo e na CSV.
CHAVE_NOTA = "31260907485646000155550010000600011111111111"
CHAVE_MENTIRA = "31260907485646000155550010000600022222222222"
CHAVE_PROTOCOLO = "31260907485646000155550010000600033333333333"
CHAVE_EVENTO = "31260907485646000155550010000600044444444444"
CHAVE_RESUMO = "31260907485646000155550010000600055555555555"
CHAVE_596 = "31260907485646000155550010000600066666666666"
CHAVE_NFSE = "35260907485646000155550010000600077777777777"
CHAVE_METADADOS = "35260907485646000155550010000600088888888888"
CHAVE_SEM_ARQUIVO = "31260907485646000155550010000600099999999999"


# ---------------------------------------------------------------------------
# XMLs — o conteúdo é quem decide, nunca o nome do arquivo
# ---------------------------------------------------------------------------


def _proc_nfe(chave: str) -> bytes:
    """A NF-e inteira: tem `infNFe`, com item, total e protocolo de autorização."""
    return f"""<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe><infNFe Id="NFe{chave}" versao="4.00">
    <ide><cUF>31</cUF><nNF>6000</nNF><serie>1</serie><dhEmi>2026-09-15T00:00:00-03:00</dhEmi>
      <natOp>VENDA</natOp></ide>
    <emit><CNPJ>07485646000155</CNPJ><xNome>MADEIREIRA NORTE SUL LTDA</xNome></emit>
    <dest><CNPJ>12345678000199</CNPJ><xNome>EMPRESA CLIENTE</xNome></dest>
    <det nItem="1"><prod><cProd>1</cProd><xProd>SARRAFO</xProd><qCom>10</qCom>
      <vUnCom>226.184</vUnCom><vProd>2261.84</vProd></prod></det>
    <total><ICMSTot><vNF>2261.84</vNF></ICMSTot></total>
  </infNFe></NFe>
  <protNFe versao="4.00"><infProt><chNFe>{chave}</chNFe><cStat>100</cStat>
    <dhRecbto>2026-09-15T15:08:10-03:00</dhRecbto><nProt>131267911602091</nProt>
  </infProt></protNFe>
</nfeProc>""".encode()


def _res_nfe(chave: str) -> bytes:
    """Só o resumo: chave, emitente, valor. Nada de item, ICMS ou total."""
    return f"""<resNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
  <chNFe>{chave}</chNFe>
  <CNPJ>07485646000155</CNPJ>
  <xNome>MADEIREIRA NORTE SUL LTDA</xNome>
  <dhEmi>2026-09-15T00:00:00-03:00</dhEmi>
  <vNF>2261.84</vNF>
  <nProt>131267911602091</nProt>
</resNFe>""".encode()


def _prot_nfe(chave: str) -> bytes:
    """Só a autorização: é exatamente o que o importador chamava de 'autorização de nota'."""
    return f"""<protNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <infProt><chNFe>{chave}</chNFe><cStat>100</cStat>
    <dhRecbto>2026-09-15T15:08:10-03:00</dhRecbto><nProt>131267911602091</nProt>
  </infProt>
</protNFe>""".encode()


def _evento_nfe(chave: str) -> bytes:
    """Um evento da nota (carta de correção, por exemplo) — não é a nota."""
    return f"""<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.00">
  <evento versao="1.00"><infEvento Id="ID110110{chave}01">
    <cOrgao>31</cOrgao><tpEvento>110110</tpEvento><chNFe>{chave}</chNFe>
  </infEvento></evento>
</procEventoNFe>""".encode()


def _nfse(chave: str) -> bytes:
    """NFS-e no leiaute NACIONAL — tem `infNFSe`, portanto é o documento inteiro."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <infNFSe Id="NFS{chave}">
    <DPS><infDPS>
      <dhEmi>2026-09-10T09:00:00-03:00</dhEmi>
      <dComp>2026-09-10</dComp>
      <prest><CNPJ>99999999000188</CNPJ><xNome>Prestador Teste</xNome></prest>
      <valores><vLiq>250.75</vLiq></valores>
    </infDPS></DPS>
  </infNFSe>
</NFSe>""".encode()


@pytest.fixture
def acervo(tmp_path, monkeypatch):
    """Um acervo de 09/2026 com UM caso de cada jeito de não ser nota.

    O caso central é o `CHAVE_MENTIRA`: o banco diz `leiaute = "completo"` e o
    arquivo no disco é um `resNFe`. É ele que fazia o pacote mentir, e é ele
    que prova que a classificação não pode confiar no cadastro.
    """
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    db.add(escritorio)
    db.flush()
    usuario = Usuario(
        escritorio_id=escritorio.id,
        nome="Administrador Teste",
        email="admin@teste.local",
        senha_hash="nao-usado-no-teste",
        papel="admin",
        ativo=True,
    )
    db.add(usuario)
    db.flush()

    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social=EMPRESA,
        cnpj_cpf="12345678000199",
        uf="MG",
    )
    db.add(empresa)
    db.flush()

    pasta_nfe = tmp_path / "xml" / str(empresa.id) / "nfe"
    pasta_nfse = tmp_path / "xml" / str(empresa.id) / "nfse"
    pasta_nfe.mkdir(parents=True)
    pasta_nfse.mkdir(parents=True)

    # (chave, tipo, pasta, conteúdo no disco, leiaute no cadastro)
    casos = [
        (CHAVE_NOTA, TipoDocumentoFiscal.NFE, pasta_nfe, _proc_nfe, "completo"),
        # o caso que originou tudo: cadastro "completo", arquivo resNFe
        (CHAVE_MENTIRA, TipoDocumentoFiscal.NFE, pasta_nfe, _res_nfe, "completo"),
        (CHAVE_PROTOCOLO, TipoDocumentoFiscal.NFE, pasta_nfe, _prot_nfe, "completo"),
        (CHAVE_EVENTO, TipoDocumentoFiscal.NFE, pasta_nfe, _evento_nfe, "completo"),
        (CHAVE_RESUMO, TipoDocumentoFiscal.NFE, pasta_nfe, _res_nfe, "resumo"),
        (CHAVE_596, TipoDocumentoFiscal.NFE, pasta_nfe, _res_nfe, "resumo"),
        (CHAVE_NFSE, TipoDocumentoFiscal.NFSE, pasta_nfse, _nfse, "completo"),
    ]
    for chave, tipo, pasta, gerar_xml, leiaute in casos:
        caminho = pasta / f"{chave}.xml"
        caminho.write_bytes(gerar_xml(chave))
        db.add(
            DocumentoFiscal(
                empresa_id=empresa.id,
                tipo=tipo,
                direcao="tomada",
                chave_acesso=chave,
                nsu="1",
                data_emissao=datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc),
                competencia=date(2026, 9, 1),
                valor_total=2261.84,
                xml_path=str(caminho),
                leiaute=leiaute,
                numero="6000",
                serie="1",
                emitente_nome="MADEIREIRA NORTE SUL LTDA",
                emitente_documento="07485646000155",
            )
        )

    # 596: a SEFAZ não aceita mais a Ciência — a saída é manifestação conclusiva.
    db.query(DocumentoFiscal).filter(
        DocumentoFiscal.chave_acesso == CHAVE_596
    ).update({"manifestacao_cstat": "596", "manifestacao_erro": "Evento fora do prazo"})

    # NFS-e recebida por metadados: a fonte nunca entregou XML.
    db.add(
        DocumentoFiscal(
            empresa_id=empresa.id,
            tipo=TipoDocumentoFiscal.NFSE,
            direcao="tomada",
            chave_acesso=CHAVE_METADADOS,
            nsu="2",
            data_emissao=datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc),
            competencia=date(2026, 9, 1),
            valor_total=120.0,
            xml_path="/tmp/fluxa-nao-existe.xml",
            leiaute="metadados",
            numero="6001",
            serie="1",
            emitente_nome="Prestador Nacional",
            emitente_documento="99999999000188",
        )
    )

    # Cadastro "completo", arquivo sumiu do disco (backup parcial, disco perdido).
    db.add(
        DocumentoFiscal(
            empresa_id=empresa.id,
            tipo=TipoDocumentoFiscal.NFE,
            direcao="tomada",
            chave_acesso=CHAVE_SEM_ARQUIVO,
            nsu="3",
            data_emissao=datetime(2026, 9, 13, 9, 0, tzinfo=timezone.utc),
            competencia=date(2026, 9, 1),
            valor_total=99.9,
            xml_path="/tmp/fluxa-tambem-nao-existe.xml",
            leiaute="completo",
            numero="6002",
            serie="1",
            emitente_nome="Fornecedor Fantasma",
            emitente_documento="07485646000155",
        )
    )
    db.commit()

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id

    client = TestClient(app)
    yield {"client": client, "db": db, "empresa_id": empresa.id}
    app.dependency_overrides.clear()
    db.close()


def _baixar(client, **extra) -> zipfile.ZipFile:
    resposta = client.get(
        "/documentos/exportar", params={"competencia": "09/2026", **extra}
    )
    assert resposta.status_code == 200, resposta.text
    return zipfile.ZipFile(io.BytesIO(resposta.content))


def _linhas_csv(pacote: zipfile.ZipFile, nome: str) -> list[str]:
    texto = pacote.read(f"Fluxa/{nome}").decode("utf-8-sig")
    return [linha for linha in texto.splitlines() if linha.strip()]


# ---------------------------------------------------------------------------
# 1. A árvore do pacote leva só XML de nota
# ---------------------------------------------------------------------------


def test_zip_nao_leva_resumo_para_a_pasta_da_empresa(acervo):
    """O caso que originou o defeito: cadastro 'completo', arquivo resNFe.

    Antes ele ia para `Fluxa/<empresa>/nfe/<chave>.xml` junto com as notas de
    verdade, e o importador da contabilidade respondia "isto é uma autorização
    de nota" sem dizer qual arquivo era.
    """
    pacote = _baixar(acervo["client"])
    xmls_da_empresa = [
        nome
        for nome in pacote.namelist()
        if nome.endswith(".xml") and nome.startswith(PASTA_EMPRESA)
    ]

    # só as duas notas inteiras (a NF-e e a NFS-e) estão na pasta da empresa
    assert len(xmls_da_empresa) == 2, xmls_da_empresa
    assert any(CHAVE_NOTA in nome for nome in xmls_da_empresa)
    assert any(CHAVE_NFSE in nome for nome in xmls_da_empresa)

    # resumo, protocolo e evento NÃO — nem o que o cadastro jurava ser completo
    for chave_proibida in (CHAVE_MENTIRA, CHAVE_PROTOCOLO, CHAVE_EVENTO, CHAVE_RESUMO, CHAVE_596):
        assert not any(chave_proibida in nome for nome in xmls_da_empresa), chave_proibida

    # e nenhum arquivo da pasta da empresa é resumo/protocolo/evento
    for nome in xmls_da_empresa:
        conteudo = pacote.read(nome).decode("utf-8")
        assert "<infNFe" in conteudo or "<infNFSe" in conteudo, nome


def test_pendencias_lista_o_que_ficou_de_fora_com_motivo_e_acao(acervo):
    """`pendencias.csv` responde "cadê a nota X?" sem abrir arquivo nenhum."""
    pacote = _baixar(acervo["client"])
    assert "Fluxa/pendencias.csv" in pacote.namelist()

    linhas = _linhas_csv(pacote, "pendencias.csv")
    cabecalho = linhas[0].split(";")
    assert "motivo" in cabecalho and "o_que_fazer" in cabecalho

    texto = pacote.read("Fluxa/pendencias.csv").decode("utf-8-sig")
    for chave in (
        CHAVE_MENTIRA,
        CHAVE_PROTOCOLO,
        CHAVE_EVENTO,
        CHAVE_RESUMO,
        CHAVE_596,
        CHAVE_METADADOS,
        CHAVE_SEM_ARQUIVO,
    ):
        assert chave in texto, f"{chave} sumiu da pendencias.csv"

    # as notas que entraram no pacote não são pendência
    assert CHAVE_NOTA not in texto
    assert CHAVE_NFSE not in texto

    # 7 documentos ficaram de fora; as 2 notas, não
    assert len(linhas) == 8  # cabeçalho + 7 pendências


def test_pendencias_diz_manifestar_operacao_quando_o_cstat_e_596(acervo):
    """Fora do prazo da Ciência não se resolve com "buscar XML": é manifestar."""
    pacote = _baixar(acervo["client"])
    texto = pacote.read("Fluxa/pendencias.csv").decode("utf-8-sig")

    linha_596 = next(linha for linha in texto.splitlines() if CHAVE_596 in linha)
    assert "596" in linha_596
    assert "Manifestar operação" in linha_596

    linha_resumo = next(linha for linha in texto.splitlines() if CHAVE_RESUMO in linha)
    assert "Manifestar operação" in linha_resumo  # a Ciência ainda cabe
    assert "Buscar XML completo" in linha_resumo


def test_pendencias_distingue_protocolo_e_arquivo_ausente(acervo):
    """Motivos diferentes pedem saídas diferentes — uma frase só não serve."""
    pacote = _baixar(acervo["client"])
    texto = pacote.read("Fluxa/pendencias.csv").decode("utf-8-sig")
    linhas = texto.splitlines()

    protocolo = next(linha for linha in linhas if CHAVE_PROTOCOLO in linha)
    assert "protocolo de autorização" in protocolo

    evento = next(linha for linha in linhas if CHAVE_EVENTO in linha)
    assert "evento da nota" in evento

    ausente = next(linha for linha in linhas if CHAVE_SEM_ARQUIVO in linha)
    assert "arquivo-ausente-no-disco" in ausente
    assert "Recapturar" in ausente

    metadados = next(linha for linha in linhas if CHAVE_METADADOS in linha)
    assert "metadados-sem-xml" in metadados


# ---------------------------------------------------------------------------
# 2. incluir_incompletos: leva, mas nunca misturado com as notas
# ---------------------------------------------------------------------------


def test_incluir_incompletos_manda_para_pasta_a_parte(acervo):
    """O checkbox existe para quem precisa do resumo — desde que separado."""
    pacote = _baixar(acervo["client"], incluir_incompletos=True)
    nomes = pacote.namelist()

    incompletos = [nome for nome in nomes if nome.startswith("Fluxa/_sem-xml-completo/")]
    assert incompletos, "incluir_incompletos não gravou nada"
    assert any(CHAVE_MENTIRA in nome for nome in incompletos)
    assert any(CHAVE_RESUMO in nome for nome in incompletos)

    # a pasta da empresa continua intocada: nada de incompleto nela
    da_empresa = [
        nome
        for nome in nomes
        if nome.endswith(".xml") and nome.startswith(PASTA_EMPRESA)
    ]
    assert len(da_empresa) == 2, da_empresa
    assert all(not chave in " ".join(da_empresa) for chave in (CHAVE_MENTIRA, CHAVE_RESUMO))

    # por padrão (sem o checkbox) a pasta à parte não existe
    padrao = _baixar(acervo["client"])
    assert not [n for n in padrao.namelist() if n.startswith("Fluxa/_sem-xml-completo/")]


def test_selecao_de_cancelada_nao_leva_evento_para_o_pacote(acervo):
    """O evento de uma cancelada fica fora até da pasta de incompletos."""
    db = acervo["db"]
    cancelada = db.query(DocumentoFiscal).filter(DocumentoFiscal.chave_acesso == CHAVE_EVENTO).one()
    cancelada.status = StatusDocumentoFiscal.CANCELADA
    db.commit()

    resposta = acervo["client"].get(
        "/documentos/exportar",
        params={
            "documento_ids": str(cancelada.id),
            "incluir_canceladas": False,
            "incluir_incompletos": True,
        },
    )

    assert resposta.status_code == 404


# ---------------------------------------------------------------------------
# 3. relacao.csv continua a visão completa, e a tela avisa antes do clique
# ---------------------------------------------------------------------------


def test_relacao_csv_lista_tudo_e_xml_completo_diz_a_verdade(acervo):
    """A relação é o inventário: ninguém pode sumir dela por ter ficado de fora."""
    pacote = _baixar(acervo["client"])
    linhas = _linhas_csv(pacote, "relacao.csv")
    assert len(linhas) == 10  # cabeçalho + 9 documentos do filtro

    texto = pacote.read("Fluxa/relacao.csv").decode("utf-8-sig")
    for chave in (
        CHAVE_NOTA,
        CHAVE_MENTIRA,
        CHAVE_PROTOCOLO,
        CHAVE_EVENTO,
        CHAVE_RESUMO,
        CHAVE_596,
        CHAVE_NFSE,
        CHAVE_METADADOS,
        CHAVE_SEM_ARQUIVO,
    ):
        assert chave in texto, f"{chave} sumiu da relacao.csv"

    nota = next(linha for linha in texto.splitlines() if CHAVE_NOTA in linha)
    assert ";sim;" in nota

    mentira = next(linha for linha in texto.splitlines() if CHAVE_MENTIRA in linha)
    assert "so-resumo" in mentira

    ausente = next(linha for linha in texto.splitlines() if CHAVE_SEM_ARQUIVO in linha)
    assert "arquivo-ausente-no-disco" in ausente


def test_estimativa_conta_quem_nao_vai_entrar_no_pacote(acervo):
    """A tela avisa antes do clique — não depois de baixar 900 arquivos."""
    resposta = acervo["client"].get(
        "/documentos/exportar/estimativa", params={"competencia": "09/2026"}
    )
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()

    assert dados["documentos"] == 9
    # Conta pelo cadastro (a estimativa não lê arquivos): 2 resumo + 1 metadados.
    # As três linhas "completo" que mentem só aparecem na pendencias.csv —
    # trocável por exatidão total, mas não por uma estimativa que lê o acervo.
    assert dados["sem_xml_completo"] == 3


def test_leia_me_e_auditoria_contam_o_que_ficou_de_fora(acervo):
    """Quem recebe o pacote por e-mail não tem a tela: o LEIA-ME é o recado."""
    pacote = _baixar(acervo["client"])
    leia_me = pacote.read("Fluxa/LEIA-ME.txt").decode("utf-8")

    assert "XMLs de nota no pacote: 2" in leia_me
    assert "7 documentos do filtro NÃO entraram no pacote de notas" in leia_me
    assert "pendencias.csv" in leia_me
    assert "Manifestar operação" in leia_me

    # e o rastro no sistema diz a mesma coisa — é o que responde depois a
    # pergunta "por que o lote de 09 faltou nota?"
    registros = (
        acervo["db"]
        .query(RegistroAuditoria)
        .filter(RegistroAuditoria.acao == "exportacao_zip")
        .all()
    )
    assert registros, "a exportação não foi registrada na auditoria"
    detalhe = registros[-1].detalhe
    assert "2 XMLs de nota no pacote" in detalhe
    assert "7 pendências" in detalhe
