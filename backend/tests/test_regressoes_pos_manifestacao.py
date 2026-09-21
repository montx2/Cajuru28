"""Regressões encontradas na revisão do patch da manifestação.

Cada teste aqui falha no código anterior à revisão e passa depois. São bugs
reais de fluxo, não de estilo:

1. `_promover_resumo` promovia o resumo mas NÃO marcava `importou_alguma_coisa`,
   então uma varredura que só trouxe XMLs completos caía no ramo "em dia" e
   ganhava 1h de cooldown — o oposto do que a NT manda quando ainda há fila.
2. A promoção não consumia o evento: depois de promover, o worker continuava
   e o `_gravar_documento` era chamado à toa (hoje há `continue`, mas o
   contador `total_no_periodo` ficava dessincronizado do que foi realmente
   escrito no acervo).
3. Documento promovido não recebia `origem`/`status`, ficando fora dos
   filtros de proveniência da tela.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    DocumentoFiscal,
    DocumentoFiscalFonte,
    Empresa,
    Escritorio,
    TipoDocumentoFiscal,
)
from app.worker.tasks import _gravar_documento, _promover_resumo

NFE = TipoDocumentoFiscal.NFE
CHAVE = "35260812345678000199550010000001231234567890"


@pytest.fixture
def db(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()
    escritorio = Escritorio(nome="Escritório Teste")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(
        escritorio_id=escritorio.id, razao_social="EMPRESA", cnpj_cpf="12345678000199", uf="MG"
    )
    sessao.add(empresa)
    sessao.commit()
    yield sessao, empresa
    sessao.close()


def _doc(chave=CHAVE, nsu="1", xml=b"<resNFe/>", leiaute="resumo", valor=0.0):
    return SimpleNamespace(
        chave_acesso=chave, nsu=nsu, xml=xml, leiaute=leiaute, valor_total=valor,
        data_emissao="2026-08-20T09:00:00-03:00", direcao="tomada", competencia="2026-08-01",
        numero="123", serie="1", emitente_nome="FORNECEDOR LTDA",
    )


def test_promocao_registra_proveniencia_com_o_nsu_do_completo(db):
    """A promoção tem de deixar rastro: é uma segunda entrega da SEFAZ.

    Sem o registro, a tela de proveniência mostra o documento como se só
    tivesse chegado pelo NSU antigo (o do resumo) e a auditoria não consegue
    provar de onde veio o XML fiscal que o contador baixou.
    """
    sessao, empresa = db
    assert _gravar_documento(sessao, empresa.id, NFE, _doc(nsu="1"))
    sessao.commit()

    completo = _doc(nsu="777", xml=b"<nfeProc>X</nfeProc>", leiaute="completo")
    assert _promover_resumo(sessao, empresa.id, NFE, completo)
    sessao.commit()

    documento = sessao.query(DocumentoFiscal).one()
    fontes = (
        sessao.query(DocumentoFiscalFonte)
        .filter(DocumentoFiscalFonte.documento_id == documento.id)
        .all()
    )
    assert "777" in {f.identificador_externo for f in fontes}


def test_promocao_atualiza_o_nsu_do_documento(db):
    """O documento tem de apontar para o NSU do XML completo.

    O cursor da empresa avança para o NSU do completo. Se o documento continua
    gravado com o NSU do resumo, a reconciliação "qual NSU gerou este arquivo"
    aponta para um docZip que não contém o XML que está em disco.
    """
    sessao, empresa = db
    assert _gravar_documento(sessao, empresa.id, NFE, _doc(nsu="10"))
    sessao.commit()
    assert sessao.query(DocumentoFiscal).one().nsu == "10"

    assert _promover_resumo(
        sessao, empresa.id, NFE, _doc(nsu="4321", xml=b"<nfeProc/>", leiaute="completo")
    )
    sessao.commit()
    assert sessao.query(DocumentoFiscal).one().nsu == "4321"


def test_promocao_limpa_a_pendencia_de_manifestacao(db):
    """Chegou o XML completo: a nota não está mais 'aguardando manifestação'.

    Se `manifestacao_erro` continuar preenchido, `_pendentes_de_completar` a
    considera rejeitada para sempre — e, pior, o operador vê um erro antigo
    numa nota que já está completa no acervo.
    """
    sessao, empresa = db
    assert _gravar_documento(sessao, empresa.id, NFE, _doc())
    sessao.commit()
    documento = sessao.query(DocumentoFiscal).one()
    documento.manifestacao_erro = "cStat=573 duplicidade"
    sessao.commit()

    assert _promover_resumo(
        sessao, empresa.id, NFE, _doc(xml=b"<nfeProc/>", leiaute="completo")
    )
    sessao.commit()

    documento = sessao.query(DocumentoFiscal).one()
    assert documento.leiaute == "completo"
    assert documento.manifestacao_erro is None


def test_promocao_nao_apaga_dados_quando_o_completo_vem_sem_metadados(db):
    """XML completo com metadados vazios não pode zerar o que o resumo trouxe.

    O `resNFe` costuma trazer emitente e valor; alguns `procNFe` chegam sem os
    campos que o parser extrai. Sobrescrever com vazio faria a nota "perder"
    o fornecedor na tela.
    """
    sessao, empresa = db
    assert _gravar_documento(
        sessao, empresa.id, NFE, _doc(valor=1234.56)
    )
    sessao.commit()

    magro = SimpleNamespace(
        chave_acesso=CHAVE, nsu="99", xml=b"<nfeProc/>", leiaute="completo",
        valor_total=None, data_emissao="", direcao="tomada", competencia="",
        numero="", serie="", emitente_nome="",
    )
    assert _promover_resumo(sessao, empresa.id, NFE, magro)
    sessao.commit()

    documento = sessao.query(DocumentoFiscal).one()
    assert documento.leiaute == "completo"
    assert documento.emitente_nome == "FORNECEDOR LTDA"
    assert float(documento.valor_total) == 1234.56


# --------------------------------------------------------------------------
# O bug mais caro: cooldown de 1h numa rodada que SÓ trouxe XML completo
# --------------------------------------------------------------------------


def test_rodada_que_so_promove_resumos_nao_ganha_cooldown_de_uma_hora(
    tmp_path, monkeypatch
):
    """Promover XML completo é trabalho útil — não é "nada novo".

    Cenário real depois de ligar a Ciência: o Ambiente Nacional passa a
    entregar os `procNFe` das notas que já estavam em resumo. Nenhuma linha
    NOVA é inserida (a chave já existe), só promoções.

    Com `importou_alguma_coisa` ficando False, o worker concluía no ramo
    "em dia" e chamava `marcar_sem_novidade`, congelando a empresa por 1h
    mesmo com `ultNSU < maxNSU` — ou seja, com fila pendente no ambiente.
    Isso arrasta a recuperação do acervo por dias.
    """
    from app.models import Certificado, ExecucaoImportacao, StatusExecucao
    from app.services import sincronizacao
    from app.services.importadores.base import LoteImportado
    from app.worker import tasks as T
    from tests.test_worker_importacao_fluxo import _montar_cenario

    sessao, empresa = _montar_cenario(tmp_path, monkeypatch)

    # a nota já está no acervo, em resumo, dentro do período
    sessao.add(
        DocumentoFiscal(
            empresa_id=empresa.id,
            tipo=NFE,
            direcao="tomada",
            chave_acesso=CHAVE,
            nsu="10",
            data_emissao=datetime(2026, 8, 20, tzinfo=timezone.utc),
            valor_total=0.0,
            xml_path=str(tmp_path / "resumo.xml"),
            leiaute="resumo",
        )
    )
    (tmp_path / "resumo.xml").write_bytes(b"<resNFe/>")
    sessao.commit()

    execucao = ExecucaoImportacao(empresa_id=empresa.id, tipo=NFE)
    sessao.add(execucao)
    sessao.commit()

    # a SEFAZ devolve o procNFe da MESMA chave, e ainda há fila (ultNSU < maxNSU)
    completo = _doc(nsu="11", xml=b"<nfeProc>COMPLETO</nfeProc>", leiaute="completo")

    class ImportadorFake:
        def buscar_lote(self, **kwargs):
            return LoteImportado(
                documentos=[completo],
                proximo_nsu="11",
                ha_mais_documentos=False,
                max_nsu="90",  # ainda há muita coisa no ambiente
            )

    monkeypatch.setattr(T, "obter_importador", lambda tipo: ImportadorFake())
    monkeypatch.setattr(T, "sessao_mtls", _mtls_falso(tmp_path))

    T.importar_documentos(empresa.id, "nfe", execucao.id)

    sessao.refresh(execucao)
    assert execucao.status == StatusExecucao.CONCLUIDA

    documento = sessao.query(DocumentoFiscal).one()
    assert documento.leiaute == "completo", "o XML completo tinha de substituir o resumo"

    estado = sincronizacao.obter_estado(sessao, empresa.id, NFE)
    assert estado.proxima_consulta_em is None, (
        "a rodada promoveu XML e ainda há fila (ultNSU 11 < maxNSU 90): "
        "congelar a empresa por 1h atrasa a recuperação do acervo"
    )
    sessao.close()


def _mtls_falso(tmp_path):
    """`sessao_mtls` de mentira: devolve caminhos, não abre conexão."""
    import contextlib

    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    cert.write_text("x")
    key.write_text("x")

    @contextlib.contextmanager
    def _fake(pfx_bytes, senha):
        yield (str(cert), str(key))

    return _fake


# --------------------------------------------------------------------------
# Impasse da fila: quem precisa de Ciência nunca chega a ser manifestado
# --------------------------------------------------------------------------


def test_fila_de_completar_alcanca_notas_ainda_nao_manifestadas(db):
    """A fila não pode enxergar SÓ o que já está manifestado.

    `_pendentes_de_completar` filtra `manifestado_em IS NOT NULL` quando a
    empresa NÃO tem manifestação automática — correto, porque nesse caso o
    robô não pode agir. Mas quando a empresa OPTOU pela manifestação
    automática, a fila precisa justamente das notas ainda NÃO manifestadas:
    é dentro de `completar_xmls_pendentes` que a Ciência é enviada.

    Este teste fixa o contrato: empresa opt-in enxerga as não manifestadas.
    """
    sessao, empresa = db
    empresa.manifestar_automaticamente = True
    for n in range(1, 4):
        sessao.add(
            DocumentoFiscal(
                empresa_id=empresa.id, tipo=NFE, direcao="tomada",
                chave_acesso=f"{n:044d}", nsu=str(n),
                data_emissao=datetime(2026, 8, 20, tzinfo=timezone.utc),
                valor_total=0.0, xml_path=f"/tmp/{n}.xml", leiaute="resumo",
            )
        )
    sessao.commit()

    from app.worker.tasks import _pendentes_de_completar

    fila = _pendentes_de_completar(sessao, empresa, 20)
    assert len(fila) == 3, (
        "empresa com Ciência automática precisa ver as notas não manifestadas, "
        "senão a manifestação nunca é disparada e tudo fica em resumo"
    )
