"""
O modo automático: o tick do Beat, a retomada de quem estava dormindo e o
preenchimento dos XMLs que chegaram só em resumo.

Testado aqui porque é o trecho que ninguém vê funcionando: se ele falhar, o
sistema volta silenciosamente a ser "alguém tem que clicar em importar".
"""

from datetime import datetime, timedelta, timezone

import base64
import gzip

import httpx
import pytest
import respx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat, pkcs12
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
from app.services import fila, sincronizacao
from app.worker import tasks

URL_NFE = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
CNPJ = "12345678000199"
CHAVE = "35260812345678000199550010000001231111111111"[:44].ljust(44, "1")
SENHA = "senha-fake"


def _pfx(tmp_path, nome=CNPJ):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sufixo = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nome)])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(sufixo)
        .issuer_name(sufixo)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    caminho = tmp_path / f"{nome}.pfx"
    caminho.write_bytes(
        pkcs12.serialize_key_and_certificates(
            name=b"c", key=chave, cert=cert, cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(SENHA.encode()),
        )
    )
    return caminho


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))
    monkeypatch.setattr(config.settings, "sincronismo_automatico", True)
    monkeypatch.setattr(config.settings, "espera_entre_lotes_segundos", 0.0)
    monkeypatch.setattr(config.settings, "ambiente_fiscal", "producao")
    monkeypatch.setattr(
        "app.services.importadores._distribuicao_dfe.time.sleep", lambda _: None
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()
    escritorio = Escritorio(nome="E")
    sessao.add(escritorio)
    sessao.flush()

    def criar(razao: str, cnpj: str, **kwargs) -> Empresa:
        empresa = Empresa(
            escritorio_id=escritorio.id,
            razao_social=razao,
            cnpj_cpf=cnpj,
            uf="SP",
            **kwargs,
        )
        sessao.add(empresa)
        sessao.flush()
        return empresa

    disparos: list[dict] = []
    monkeypatch.setattr(
        fila,
        "_disparar",
        lambda empresa_id, tipo, execucao_id: disparos.append(
            {"empresa_id": empresa_id, "tipo": tipo, "execucao_id": execucao_id}
        ),
    )
    monkeypatch.setattr(
        tasks.importar_documentos,
        "apply_async",
        lambda *a, **k: disparos.append({"apply_async": k}),
    )
    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=engine))

    yield {"sessao": sessao, "criar": criar, "disparos": disparos, "tmp": tmp_path}
    sessao.close()


# ---------------------------------------------------------------------------
# seleção de quem deve ser varrido
# ---------------------------------------------------------------------------


def test_sincronizar_tudo_nao_faz_nada_quando_o_automatico_esta_desligado(base, monkeypatch):
    monkeypatch.setattr(config.settings, "sincronismo_automatico", False)
    base["criar"]("A", "11111111000111")
    base["sessao"].commit()

    assert tasks.sincronizar_tudo() == {"desativado": True}
    assert base["disparos"] == []


def test_round_robin_da_fila_de_sincronismo(base):
    """Empresa nunca varrida primeiro; depois, a que está há mais tempo sem varrer."""
    nunca = base["criar"]("Nunca varrida", "11111111000111")
    recente = base["criar"]("Recém-varrida", "22222222000112")
    antiga = base["criar"]("Esperando ha mais", "33333333000113")
    desligada = base["criar"]("Automático off", "44444444000114", sincronizar_automaticamente=False)
    base["sessao"].commit()

    agora = datetime.now(timezone.utc)
    for empresa, quando in ((recente, agora - timedelta(minutes=10)), (antiga, agora - timedelta(hours=3))):
        for tipo in TipoDocumentoFiscal:
            estado = sincronizacao.obter_estado(base["sessao"], empresa.id, tipo)
            estado.ultima_consulta_em = quando
    base["sessao"].commit()

    ordem = [empresa.razao_social for empresa, _ in fila.disponiveis_para_sincronismo_automatico(base["sessao"])]
    assert ordem == ["Nunca varrida", "Esperando ha mais", "Recém-varrida"]
    assert desligada.razao_social not in ordem


def test_respeita_os_tipos_escolhidos_e_o_teto_por_tick(base):
    so_nfse = base["criar"]("Só NFS-e", "11111111000111", quais_tipos_sincronizar="nfse")
    base["criar"]("Todas", "22222222000112")
    base["sessao"].commit()

    lista = fila.disponiveis_para_sincronismo_automatico(base["sessao"])
    tipos = {empresa.id: [t.value for t in selecionados] for empresa, selecionados in lista}
    assert tipos[so_nfse.id] == ["nfse"]
    assert set(tipos[lista[1][0].id]) == {"nfse", "nfe", "cte"}

    assert len(fila.disponiveis_para_sincronismo_automatico(base["sessao"], limite=1)) == 1


def test_tick_enfileira_uma_task_por_empresa_e_pula_quem_esta_na_janela(base):
    livre = base["criar"]("Livre", "11111111000111")
    dormindo = base["criar"]("Dormindo", "22222222000112", quais_tipos_sincronizar="nfse")
    pfx = _pfx(base["tmp"], "Livre")
    base["sessao"].add(
        Certificado(
            empresa_id=livre.id,
            arquivo_path=str(pfx),
            senha_cifrada=cifrar_segredo(SENHA),
            validade=datetime.now(timezone.utc) + timedelta(days=30),
            ativo=True,
        )
    )
    base["sessao"].add(
        Certificado(
            empresa_id=dormindo.id,
            arquivo_path=str(pfx),
            senha_cifrada=cifrar_segredo(SENHA),
            validade=datetime.now(timezone.utc) + timedelta(days=30),
            ativo=True,
        )
    )
    estado = sincronizacao.obter_estado(base["sessao"], dormindo.id, TipoDocumentoFiscal.NFSE)
    estado.ultimo_nsu = "10"
    estado.max_nsu = "10"
    sincronizacao.marcar_sem_novidade(base["sessao"], estado)
    base["sessao"].commit()

    resumo = tasks.sincronizar_tudo()

    # só a empresa livre entrou na fila (3 tipos); a outra está na janela de 1h
    assert resumo["enfileiradas"] == 3
    assert resumo["aguardando"] == 1
    assert {d["empresa_id"] for d in base["disparos"]} == {livre.id}
    assert len({d["tipo"] for d in base["disparos"]}) == 3

    # e o tick seguinte não duplica nada: quem já está em andamento fica de fora
    antes = len(base["disparos"])
    resumo_de_novo = tasks.sincronizar_tudo()
    assert resumo_de_novo["enfileiradas"] == 0
    assert len(base["disparos"]) == antes


def test_reagendar_e_a_retomada_pela_mesma_execucao(base):
    """
    O reagendamento com countdown é o caminho rápido; a varredura do Beat é o
    backstop. Os dois têm de cair na MESMA execução — senão o histórico vira
    duas linhas e alguém "importa" a mesma janela duas vezes.
    """
    sessao = base["sessao"]
    empresa = base["criar"]("Acorda sozinha", "11111111000111")
    execucao = ExecucaoImportacao(
        empresa_id=empresa.id, tipo=TipoDocumentoFiscal.NFSE, status=StatusExecucao.EM_ANDAMENTO
    )
    sessao.add(execucao)
    sessao.commit()

    quando = datetime.now(timezone.utc) + timedelta(hours=1)
    assert fila.reagendar(sessao, execucao, quando, motivo="656") is True

    assert execucao.status == StatusExecucao.AGUARDANDO
    assert execucao.tentativas == 1
    assert "656" in (execucao.aviso or "")
    agendamento = base["disparos"][-1]["apply_async"]
    assert 59 * 60 <= agendamento["countdown"] <= 61 * 60
    assert agendamento["kwargs"]["execucao_id"] == execucao.id

    # a janela venceu: o tick acorda a mesma execução, sem criar outra
    execucao.bloqueado_ate = datetime.now(timezone.utc) - timedelta(minutes=1)
    sessao.commit()
    base["disparos"].clear()

    resumo = tasks.sincronizar_tudo()
    assert resumo["retomadas"] == 1
    sessao.expire_all()
    execucoes = sessao.query(ExecucaoImportacao).all()
    assert len(execucoes) == 1
    assert execucoes[0].id == execucao.id
    assert execucoes[0].status == StatusExecucao.EM_ANDAMENTO


def test_sem_broker_o_beat_assume_sem_perder_o_checkpoint(base):
    sessao = base["sessao"]
    empresa = base["criar"]("Sem Redis", "11111111000111")
    execucao = ExecucaoImportacao(
        empresa_id=empresa.id, tipo=TipoDocumentoFiscal.NFSE, status=StatusExecucao.EM_ANDAMENTO
    )
    sessao.add(execucao)
    sessao.commit()

    def _sem_broker(*a, **k):
        raise ConnectionError("Redis está fora do ar")

    monkey = getattr(base, "monkeypatch", None)  # não usado; substituído abaixo
    del monkey
    import app.worker.tasks as modulo

    original = modulo.importar_documentos.apply_async
    original_delay = modulo.importar_documentos.delay
    modulo.importar_documentos.apply_async = lambda *a, **k: (_ for _ in ()).throw(
        ConnectionError("sem broker")
    )
    modulo.importar_documentos.delay = lambda *a, **k: (_ for _ in ()).throw(
        ConnectionError("sem broker")
    )
    try:
        ok = fila.reagendar(
            sessao,
            base["sessao"].get(ExecucaoImportacao, execucao.id),
            datetime.now(timezone.utc) + timedelta(hours=1),
            motivo="ambiente indisponível",
        )
        assert ok is False
        sessao.expire_all()
        dormente = sessao.get(ExecucaoImportacao, execucao.id)
        assert dormente.status == StatusExecucao.AGUARDANDO  # o estado persistiu

        # Beat: acorda quando a janela passou, mas continua sem broker → volta a dormir
        dormente.bloqueado_ate = datetime.now(timezone.utc) - timedelta(minutes=1)
        sessao.commit()
        tasks.sincronizar_tudo()
        sessao.expire_all()
        assert sessao.get(ExecucaoImportacao, execucao.id).status == StatusExecucao.AGUARDANDO
    finally:
        modulo.importar_documentos.apply_async = original
        modulo.importar_documentos.delay = original_delay


def test_beat_respeita_a_janela_mesmo_acordando_cedo(base):
    """
    Bloqueio "vencido" na execução, mas o estado da empresa ainda dentro da
    janela: o tick empurra o horário em vez de queimar a consulta.
    """
    sessao = base["sessao"]
    empresa = base["criar"]("Janela viva", "11111111000111")
    execucao = ExecucaoImportacao(
        empresa_id=empresa.id, tipo=TipoDocumentoFiscal.NFSE, status=StatusExecucao.AGUARDANDO
    )
    sessao.add(execucao)
    sessao.commit()

    estado = sincronizacao.obter_estado(sessao, empresa.id, TipoDocumentoFiscal.NFSE)
    sincronizacao.marcar_consumo_indevido(sessao, estado, motivo="656")
    execucao.bloqueado_ate = datetime.now(timezone.utc) - timedelta(minutes=1)
    sessao.commit()

    tasks.sincronizar_tudo()

    sessao.expire_all()
    acordada = sessao.get(ExecucaoImportacao, execucao.id)
    assert acordada.status == StatusExecucao.AGUARDANDO
    assert _na_futuro(acordada.bloqueado_ate) is True
    assert base["disparos"] == []


# ---------------------------------------------------------------------------
# gap-fill: nota que veio só em resumo vira XML completo
# ---------------------------------------------------------------------------


def _soap(cstat: str, motivo: str, docs: str = "", ult: str = "500", maxn: str = "500") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body>
    <nfeDistDFeInteresseResponse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">
      <nfeDistDFeInteresseResult>
        <retDistDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">
          <cStat>{cstat}</cStat><xMotivo>{motivo}</xMotivo>
          <ultNSU>{ult}</ultNSU><maxNSU>{maxn}</maxNSU>
          {f"<loteDistDFeInt>{docs}</loteDistDFeInt>" if docs else ""}
        </retDistDFeInt>
      </nfeDistDFeInteresseResult>
    </nfeDistDFeInteresseResponse>
  </soap:Body>
</soap:Envelope>""".encode()


def _proc_nfe(chave: str) -> str:
    interno = (
        '<nfeProc versao="4.00" xmlns="http://www.portalfiscal.inf.br/nfe">'
        f'<NFe><infNFe Id="NFe{chave}" versao="4.00"><ide><natOp>Venda</natOp>'
        f"<chNFe>{chave}</chNFe><dhEmi>2026-08-11T09:00:00-03:00</dhEmi>"
        "<nNF>123</nNF><serie>1</serie></ide>"
        '<emit><CNPJ>99999999000188</CNPJ><xNome>Fornecedor X</xNome></emit>'
        '<dest><CNPJ>12345678000199</CNPJ><xNome>ARM LOGISTICA</xNome></dest>'
        "<total><ICMSTot><vNF>4321.10</vNF></ICMSTot></total>"
        "</infNFe></NFe><protNFe><infProt><cStat>100</cStat><xMotivo>Autorizado o uso da NF-e</xMotivo>"
        f"<chNFe>{chave}</chNFe></infProt></protNFe></nfeProc>"
    )
    doc = base64.b64encode(gzip.compress(interno.encode())).decode()
    return f'<docZip NSU="500" schema="procNFe_v4.00.xsd">{doc}</docZip>'


def _prepara_documento_resumo(base, tmp_suffix="r1"):
    sessao = base["sessao"]
    empresa = base["criar"](f"Empresa {tmp_suffix}", "11111111000111")
    pfx = _pfx(base["tmp"], f"empresa-{tmp_suffix}")
    sessao.add(
        Certificado(
            empresa_id=empresa.id,
            arquivo_path=str(pfx),
            senha_cifrada=cifrar_segredo(SENHA),
            validade=datetime.now(timezone.utc) + timedelta(days=30),
            ativo=True,
        )
    )
    pasta = base["tmp"] / "xml" / str(empresa.id) / "nfe"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{CHAVE}.xml"
    caminho.write_text("<resNFe>apenas resumo</resNFe>", encoding="utf-8")
    documento = DocumentoFiscal(
        empresa_id=empresa.id,
        tipo=TipoDocumentoFiscal.NFE,
        direcao="tomada",
        chave_acesso=CHAVE,
        nsu="500",
        data_emissao=datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc),
        valor_total=0,
        xml_path=str(caminho),
        leiaute="resumo",
    )
    sessao.add(documento)
    sessao.commit()
    return empresa, documento, caminho


def _na_futuro(valor) -> bool:
    """O SQLite devolve datetime naive; normaliza antes de comparar."""
    if valor is None:
        return False
    return (valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)) > datetime.now(
        timezone.utc
    )


@respx.mock
def test_gap_fill_preenche_o_xml_e_a_cota(base):
    empresa, documento, caminho = _prepara_documento_resumo(base)
    rota = respx.post(URL_NFE).mock(
        return_value=httpx.Response(200, content=_soap("138", "Documento(s) localizado(s)", _proc_nfe(CHAVE)))
    )

    resultado = tasks.completar_xmls_pendentes(empresa_id=empresa.id, limite=5)

    assert resultado["completos"] == 1
    assert rota.call_count == 1
    corpo = rota.calls[0].request.content.decode()
    assert "<consChNFe>" in corpo and CHAVE in corpo  # consulta pontual pela chave
    assert "resumo" not in caminho.read_text(encoding="utf-8")
    assert "<nfeProc" in caminho.read_text(encoding="utf-8")

    base["sessao"].expire_all()
    recarregado = base["sessao"].get(DocumentoFiscal, documento.id)
    assert recarregado.leiaute == "completo"
    assert recarregado.valor_total == pytest.approx(4321.10)
    assert recarregado.numero == "123"
    assert recarregado.competencia is not None

    estado = sincronizacao.obter_estado(base["sessao"], empresa.id, TipoDocumentoFiscal.NFE)
    assert estado.consultas_pontuais == 1


@respx.mock
def test_gap_fill_para_ao_tomar_656_e_nao_insiste(base):
    empresa, _, _ = _prepara_documento_resumo(base, "r2")
    rota = respx.post(URL_NFE).mock(
        return_value=httpx.Response(
            200, content=_soap("656", "Rejeicao: Consumo Indevido", ult="0", maxn="0")
        )
    )

    resultado = tasks.completar_xmls_pendentes(empresa_id=empresa.id, limite=5)
    assert resultado["completos"] == 0
    assert rota.call_count == 1  # uma tentativa só: insistir em 656 renova o bloqueio

    sessao = base["sessao"]
    estado = sincronizacao.obter_estado(sessao, empresa.id, TipoDocumentoFiscal.NFE)
    sessao.expire_all()
    assert estado.bloqueado_ate is not None
    # uma tentativa só: insistir em 656 é o que renova o bloqueio
