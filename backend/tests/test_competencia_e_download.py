"""
Competência (o mês que o contador pede) e download em massa dos XMLs.

Cobre os três pedidos que motivaram esta versão:

- `?competencia=08/2026` na importação, na listagem, no resumo e no export —
  o recorte acontece no banco, em cima da competência *declarada no XML*, então
  trocar de mês não gasta uma requisição nenhuma na SEFAZ;
- `GET /documentos/exportar` devolve um ZIP com todos os XMLs do filtro +
  relação em CSV, para todas as empresas de uma vez;
- a janela de consumo é respeitada pela API: um `POST /importacoes` dentro da
  espera responde 429 explicando até quando (e `forcar=true` é registrado).
"""

import base64
import gzip
import io
import zipfile
from datetime import date, datetime, timedelta, timezone

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
    Certificado,
    DocumentoFiscal,
    Empresa,
    Escritorio,
    ExecucaoImportacao,
    SincronizacaoDFe,
    StatusDocumentoFiscal,
    StatusExecucao,
    TipoDocumentoFiscal,
    Usuario,
)
from app.services import sincronizacao
from app.services.periodo import PeriodoInvalido, interpretar_competencia


# ---------------------------------------------------------------------------
# competência: parsing puro (a regra que todo o resto usa)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("08/2026", (date(2026, 8, 1), date(2026, 8, 31))),
        ("8/2026", (date(2026, 8, 1), date(2026, 8, 31))),
        ("2026-08", (date(2026, 8, 1), date(2026, 8, 31))),
        ("082026", (date(2026, 8, 1), date(2026, 8, 31))),
        ("202608", (date(2026, 8, 1), date(2026, 8, 31))),
        ("2026/8", (date(2026, 8, 1), date(2026, 8, 31))),
        ("2026-08-20", (date(2026, 8, 1), date(2026, 8, 31))),
        ("fevereiro/2026", (date(2026, 2, 1), date(2026, 2, 28))),
        ("ago/2026", (date(2026, 8, 1), date(2026, 8, 31))),
        ("02/2024", (date(2024, 2, 1), date(2024, 2, 29))),  # bissexto
        ("02/2023", (date(2023, 2, 1), date(2023, 2, 28))),
        ("12/2025", (date(2025, 12, 1), date(2025, 12, 31))),
    ],
)
def test_competencia_vira_intervalo_exato_do_mes(entrada, esperado):
    periodo = interpretar_competencia(entrada)
    assert (periodo.inicio, periodo.fim) == esperado
    assert periodo.rotulo() == f"{esperado[0].month:02d}/{esperado[0].year:04d}"


@pytest.mark.parametrize("entrada", ["13/2026", "abc", "2026-0", "07/1800", "32/2026", "08/202"])
def test_competencia_invalida_da_erro_claro(entrada):
    with pytest.raises(PeriodoInvalido):
        interpretar_competencia(entrada)


def test_periodo_contem_usa_a_data_de_referencia():
    periodo = interpretar_competencia("08/2026")
    assert periodo.contem(date(2026, 8, 31)) is True
    assert periodo.contem(date(2026, 9, 1)) is False
    assert periodo.contem(None) is True  # documento sem competência não some


# ---------------------------------------------------------------------------
# fixture da API
# ---------------------------------------------------------------------------


def _xml_nfse(chave: str, dia: str, prestador: str = "99999999000188") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <infNFSe Id="NFS{chave}">
    <DPS><infDPS>
      <dhEmi>2026-{dia}T09:00:00-03:00</dhEmi>
      <dComp>2026-{dia}</dComp>
      <prest><CNPJ>{prestador}</CNPJ><xNome>Fornecedor Teste</xNome></prest>
      <valores><vLiq>250.75</vLiq></valores>
    </infDPS></DPS>
  </infNFSe>
</NFSe>""".encode()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    outro = Escritorio(nome="Concorrente")
    db.add_all([escritorio, outro])
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
        razao_social="ARM LOGISTICA E TRANSPORTES LTD",
        cnpj_cpf="12345678000199",
        uf="SP",
    )
    estranha = Empresa(
        escritorio_id=outro.id, razao_social="OUTRO ESCRITORIO SA", cnpj_cpf="99999999000199", uf="RJ"
    )
    db.add_all([empresa, estranha])
    db.flush()

    # XMLs em disco, como o worker grava
    pasta = tmp_path / "xml" / str(empresa.id) / "nfse"
    pasta.mkdir(parents=True)
    chaves = {
        "35260812345678000199550010000000011111111111": "08-05",  # agosto
        "35260812345678000199550010000000022222222222": "08-20",  # agosto
        "35260912345678000199550010000000033333333333": "09-01",  # setembro
    }
    for chave, dia in chaves.items():
        (pasta / f"{chave}.xml").write_bytes(_xml_nfse(chave, dia))
        db.add(
            DocumentoFiscal(
                empresa_id=empresa.id,
                tipo=TipoDocumentoFiscal.NFSE,
                direcao="tomada",
                chave_acesso=chave,
                nsu="1",
                data_emissao=datetime(2026, int(dia[:2]), int(dia[3:]), 9, 0, tzinfo=timezone.utc),
                competencia=date(2026, int(dia[:2]), int(dia[3:])),
                valor_total=250.75,
                xml_path=str(pasta / f"{chave}.xml"),
                leiaute="completo",
                numero=str(100 + len(chave) % 7),
                serie="1",
                emitente_nome="Fornecedor Teste Ltda",
                emitente_documento="99999999000188",
            )
        )
    cancelada = list(chaves)[0]
    db.query(DocumentoFiscal).filter(
        DocumentoFiscal.chave_acesso == cancelada
    ).update({"status": StatusDocumentoFiscal.CANCELADA})

    db.add(
        DocumentoFiscal(
            empresa_id=estranha.id,
            tipo=TipoDocumentoFiscal.NFSE,
            direcao="tomada",
            chave_acesso="33333333333333333333333333333333333333333333",
            nsu="9",
            data_emissao=datetime(2026, 8, 1, tzinfo=timezone.utc),
            competencia=date(2026, 8, 1),
            valor_total=1.0,
            xml_path="/tmp/inexistente.xml",
        )
    )
    db.commit()

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id

    # sem Celery no teste: só registrar que a task foi disparada
    disparos: list[tuple] = []
    from app.worker import tasks as modulo_tasks

    monkeypatch.setattr(
        modulo_tasks.importar_documentos,
        "delay",
        lambda *args, **kwargs: disparos.append((args, kwargs)),
        raising=True,
    )

    client = TestClient(app)
    yield {
        "client": client,
        "db": db,
        "empresa_id": empresa.id,
        "estranha_id": estranha.id,
        "escritorio_id": escritorio.id,
        "pasta": pasta,
        "chaves": chaves,
        "disparos": disparos,
    }
    app.dependency_overrides.clear()
    db.close()


def test_listagem_filtra_por_competencia(cliente):
    client = cliente["client"]
    empresa_id = cliente["empresa_id"]

    todas = client.get("/documentos", params={"empresa_id": empresa_id}).json()
    agosto = client.get(
        "/documentos", params={"empresa_id": empresa_id, "competencia": "08/2026"}
    ).json()
    setembro = client.get(
        "/documentos", params={"empresa_id": empresa_id, "competencia": "09/2026"}
    ).json()

    assert len(todas) == 3
    assert len(agosto) == 2
    assert len(setembro) == 1
    assert {d["chave_acesso"] for d in agosto} == set(list(cliente["chaves"])[:2])
    assert all(d["competencia"].startswith("2026-08") for d in agosto)


def test_resumo_bate_com_a_lista_no_mesmo_filtro(cliente):
    client, empresa_id = cliente["client"], cliente["empresa_id"]
    resumo = client.get(
        "/documentos/resumo", params={"empresa_id": empresa_id, "competencia": "08/2026"}
    ).json()
    assert resumo == {
        "total": 2,
        "normais": 1,
        "canceladas": 1,
        "por_tipo": {"nfse": 2},
    }


def test_competencia_invalida_responde_422(cliente):
    resposta = cliente["client"].get(
        "/documentos", params={"empresa_id": cliente["empresa_id"], "competencia": "13/2026"}
    )
    assert resposta.status_code == 422
    assert "01 a 12" in resposta.json()["detail"]


def test_export_zip_contem_todos_os_xmls_do_periodo(cliente, tmp_path):
    client, empresa_id = cliente["client"], cliente["empresa_id"]

    resposta = client.get(
        "/documentos/exportar",
        params={"empresa_id": None, "competencia": "08/2026"},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.headers["content-type"].startswith("application/zip")

    pacote = zipfile.ZipFile(io.BytesIO(resposta.content))
    nomes = pacote.namelist()

    xmls = [n for n in nomes if n.endswith(".xml")]
    assert len(xmls) == 2
    assert all("ARM-LOGISTICA" in n.upper().replace("_", "-") or "NOTASFLOW/" in n for n in xmls)
    # pasta por empresa + tipo, arquivo = chave de acesso
    assert all(n.startswith("NotasFlow/") and n.endswith(".xml") for n in xmls)
    for nome in xmls:
        assert b"<NFSe" in pacote.read(nome)

    assert any(n.endswith("relacao.csv") for n in nomes)
    relacao = pacote.read("NotasFlow/relacao.csv").decode("utf-8-sig")
    linhas = [linha for linha in relacao.splitlines() if linha.strip()]
    assert linhas[0].split(";")[0] == "empresa"
    assert len(linhas) == 3  # cabeçalho + 2 notas
    assert "08/2026" in relacao
    assert any(n.endswith("LEIA-ME.txt") for n in nomes)

    # o arquivo temporário do ZIP não fica para trás no disco
    sobras = list(tmp_path.glob("notasflow-export-*"))
    assert sobras == []


def test_export_sem_empresa_especifica_puxa_todas_do_escritorio(cliente):
    """'baixar todos os xmls encontrados' = todas as empresas do escritório."""
    client, empresa_id, estranha_id = (
        cliente["client"],
        cliente["empresa_id"],
        cliente["estranha_id"],
    )
    resposta = client.get("/documentos/exportar", params={"empresa_ids": f"{empresa_id},{estranha_id}"})
    # a empresa de outro escritório não é do usuário: 403, não download vazio
    assert resposta.status_code == 403

    tudo = client.get("/documentos/exportar", params={"competencia": "08/2026"})
    assert tudo.status_code == 200
    nomes = zipfile.ZipFile(io.BytesIO(tudo.content)).namelist()
    xmls = [n for n in nomes if n.endswith(".xml")]
    assert len(xmls) == 2  # só as duas do escritório, ignorando a de fora


def test_download_so_da_selecao_da_tela(cliente):
    """'Baixar selecionados' usa os ids visíveis na tabela, sem depender do filtro."""
    client = cliente["client"]
    lista = client.get("/documentos", params={"empresa_id": cliente["empresa_id"]}).json()
    escolhidos = [d["id"] for d in lista[:1]]

    resposta = client.get(
        "/documentos/exportar", params={"documento_ids": ",".join(str(i) for i in escolhidos)}
    )
    assert resposta.status_code == 200, resposta.text
    nomes = [n for n in zipfile.ZipFile(io.BytesIO(resposta.content)).namelist() if n.endswith(".xml")]
    assert len(nomes) == 1

    estimativa = client.get(
        "/documentos/exportar/estimativa",
        params={"documento_ids": ",".join(str(i) for i in escolhidos)},
    ).json()
    assert estimativa["documentos"] == 1

    # ids de fora do escritório não viram download: viram seleção vazia
    estranho = cliente["db"].query(DocumentoFiscal).filter(
        DocumentoFiscal.empresa_id == cliente["estranha_id"]
    ).first().id
    vazio = client.get("/documentos/exportar", params={"documento_ids": str(estranho)})
    assert vazio.status_code == 404


def test_zip_obedece_a_mesma_busca_da_tela(cliente):
    """
    O princípio do filtro único: o número na tela tem de bater com o número de
    arquivos no ZIP — inclusive para busca e para o filtro de leiaute.
    """
    client = cliente["client"]
    empresa_id = cliente["empresa_id"]

    so_setembro = client.get(
        "/documentos/exportar",
        params={"empresa_id": empresa_id, "busca": "352609"},
    )
    assert so_setembro.status_code == 200
    xmls = [n for n in zipfile.ZipFile(io.BytesIO(so_setembro.content)).namelist() if n.endswith(".xml")]
    assert len(xmls) == 1

    # tudo que está na tela (3) == tudo que o ZIP entrega
    tela = client.get("/documentos", params={"empresa_id": empresa_id}).json()
    estimativa = client.get(
        "/documentos/exportar/estimativa", params={"empresa_id": empresa_id}
    ).json()
    assert estimativa["documentos"] == len(tela) == 3

    # 'completo' tira o que só veio em resumo
    completo = client.get(
        "/documentos/exportar/estimativa",
        params={"empresa_id": empresa_id, "leiaute": "completo"},
    ).json()
    assert completo["documentos"] == 3  # o fixture gravou todos como completo


def test_estimativa_antes_do_download(cliente):
    resposta = cliente["client"].get(
        "/documentos/exportar/estimativa", params={"competencia": "08/2026"}
    )
    corpo = resposta.json()
    assert resposta.status_code == 200
    assert corpo["documentos"] == 2
    assert corpo["periodo"] == "08/2026"
    assert corpo["estimado_bytes"] > 0
    assert corpo["limite"] > 0


def test_export_vazio_diz_para_rodar_a_importacao(cliente, monkeypatch):
    monkeypatch.setattr(config.settings, "limite_documentos_por_exportacao", 1)
    resposta = cliente["client"].get(
        "/documentos/exportar", params={"competencia": "08/2026"}
    )
    assert resposta.status_code == 413
    assert "teto de 1" in resposta.json()["detail"]

    vazio = cliente["client"].get("/documentos/exportar", params={"competencia": "01/2020"})
    assert vazio.status_code == 404
    assert "Nenhum documento no filtro" in vazio.json()["detail"]


def test_busca_por_chave_e_numero(cliente):
    uma = list(cliente["chaves"])[0]
    client, empresa_id = cliente["client"], cliente["empresa_id"]

    por_chave = client.get("/documentos", params={"empresa_id": empresa_id, "busca": uma[:12]}).json()
    assert {d["chave_acesso"] for d in por_chave} >= {uma}

    por_emitente = client.get(
        "/documentos", params={"empresa_id": empresa_id, "busca": "Fornecedor Teste"}
    ).json()
    assert len(por_emitente) == 3


def test_importacao_respeita_a_janela_de_consumo(cliente, tmp_path):
    client, db, empresa_id = cliente["client"], cliente["db"], cliente["empresa_id"]
    pfx = tmp_path / "a1.pfx"
    pfx.write_bytes(b"fake")
    db.add(
        Certificado(
            empresa_id=empresa_id,
            arquivo_path=str(pfx),
            senha_cifrada="x",
            validade=datetime.now(timezone.utc) + timedelta(days=10),
            ativo=True,
        )
    )
    db.commit()

    resposta = client.post("/importacoes", json={"empresa_id": empresa_id, "tipo": "nfse"})
    assert resposta.status_code == 202, resposta.text
    execucao_id = resposta.json()["id"]
    assert len(cliente["disparos"]) == 1

    # a execução em andamento bloqueia duplicata — e é idempotente: mesmo id
    duplicada = client.post("/importacoes", json={"empresa_id": empresa_id, "tipo": "nfse"})
    assert duplicada.status_code == 202
    assert duplicada.json()["id"] == execucao_id
    assert len(cliente["disparos"]) == 1  # nada foi enfileirado de novo

    # fecha a execução e simula "consultei agora e não havia nada novo"
    db.get(ExecucaoImportacao, execucao_id).status = StatusExecucao.CONCLUIDA
    estado = sincronizacao.obter_estado(db, empresa_id, TipoDocumentoFiscal.NFSE)
    sincronizacao.marcar_sem_novidade(db, estado)
    db.commit()

    bloqueado = client.post("/importacoes", json={"empresa_id": empresa_id, "tipo": "nfse"})
    assert bloqueado.status_code == 429
    detalhe = bloqueado.json()["detail"]
    # a mensagem tem de explicar a regra oficial (1h) e o risco de clicar de novo
    assert "1 hora" in detalhe
    assert "zera o cronômetro" in detalhe
    assert "forcar=true" in detalhe

    # a competência entra na execução e é devolvida na resposta
    com_periodo = client.post(
        "/importacoes",
        json={
            "empresa_id": empresa_id,
            "tipo": "nfe",
            "competencia": "08/2026",
        },
    )
    assert com_periodo.status_code == 202, com_periodo.text
    corpo = com_periodo.json()
    assert corpo["data_inicio"] == "2026-08-01"
    assert corpo["data_fim"] == "2026-08-31"

    # forcar=true atravessa a janela — e fica registrado na execução
    forcado = client.post(
        "/importacoes", json={"empresa_id": empresa_id, "tipo": "nfse", "forcar": True}
    )
    assert forcado.status_code == 202
    assert forcado.json()["forcar"] is True

    db.expire_all()
    nova = db.get(ExecucaoImportacao, forcado.json()["id"])
    assert nova is not None
    assert nova.id != execucao_id  # o forcar abriu uma execução nova, com histórico próprio
    assert nova.status == StatusExecucao.EM_ANDAMENTO
    assert nova.forcar is True
    # e o estado continua bloqueado: forçar a vez não apaga o histórico do bloqueio
    db.expire_all()
    estado = sincronizacao.obter_estado(db, empresa_id, TipoDocumentoFiscal.NFSE)
    assert estado.bloqueios_seguidos == 0  # 656 de verdade ainda não aconteceu


def test_lote_reporta_cooldown_e_sem_certificado(cliente):
    client, db = cliente["client"], cliente["db"]
    resultado = client.post("/importacoes/lote", params={"tipo": "nfse", "competencia": "08/2026"}).json()

    assert isinstance(resultado, list)
    assert len(resultado) == 1  # só a empresa do escritório
    item = resultado[0]
    # sem certificado ativo → não enfileira, mas explica
    assert item["status"] == "sem_certificado"
    assert "certificado" in item["mensagem"].lower() or "certificado" in item["status"]

    db.add(
        Certificado(
            empresa_id=cliente["empresa_id"],
            arquivo_path="/tmp/nao-precisa-ler.xml",
            senha_cifrada="x",
            validade=datetime.now(timezone.utc) + timedelta(days=10),
            ativo=True,
        )
    )
    db.commit()
    segundo = client.post("/importacoes/lote", params={"tipo": "nfse"}).json()
    assert segundo[0]["status"] in ("enfileirada", "em_cooldown")


def test_conferencia_competencia_comprova_mes_quando_cursor_esta_em_dia(cliente, tmp_path):
    client, db, empresa_id = cliente["client"], cliente["db"], cliente["empresa_id"]
    pfx = tmp_path / "a1.pfx"
    pfx.write_bytes(b"fake")
    db.add(
        Certificado(
            empresa_id=empresa_id,
            arquivo_path=str(pfx),
            senha_cifrada="x",
            validade=datetime.now(timezone.utc) + timedelta(days=10),
            ativo=True,
        )
    )
    estado = sincronizacao.obter_estado(db, empresa_id, TipoDocumentoFiscal.NFSE)
    estado.ultimo_nsu = "42"
    estado.max_nsu = "42"
    estado.ultima_consulta_em = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    estado.atualizado_em = estado.ultima_consulta_em
    db.commit()

    resposta = client.get(
        "/importacoes/conferencia", params={"competencia": "08/2026", "tipos": "nfse"}
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["ok"] is True
    assert corpo["status"] == "completa"
    assert corpo["documentos"] == 2
    assert corpo["canceladas"] == 1
    assert corpo["itens_ok"] == 1
    assert corpo["itens"][0]["status"] == "ok"
    assert corpo["itens"][0]["ultimo_nsu"] == "42"


def test_conferencia_competencia_exige_varredura_depois_do_fechamento(cliente, tmp_path):
    client, db, empresa_id = cliente["client"], cliente["db"], cliente["empresa_id"]
    pfx = tmp_path / "a1.pfx"
    pfx.write_bytes(b"fake")
    db.add(
        Certificado(
            empresa_id=empresa_id,
            arquivo_path=str(pfx),
            senha_cifrada="x",
            validade=datetime.now(timezone.utc) + timedelta(days=10),
            ativo=True,
        )
    )
    estado = sincronizacao.obter_estado(db, empresa_id, TipoDocumentoFiscal.NFSE)
    estado.ultimo_nsu = "42"
    estado.max_nsu = "42"
    estado.ultima_consulta_em = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)
    estado.atualizado_em = estado.ultima_consulta_em
    db.commit()

    corpo = client.get(
        "/importacoes/conferencia", params={"competencia": "08/2026", "tipos": "nfse"}
    ).json()
    assert corpo["ok"] is False
    assert corpo["status"] == "pendente"
    assert corpo["itens"][0]["status"] == "precisa_conferir"
    assert "antes do fechamento" in corpo["itens"][0]["mensagem"]


def test_endpoint_de_estado_mostra_cursor_e_bloqueio(cliente):
    client, db = cliente["client"], cliente["db"]
    estado = sincronizacao.obter_estado(db, cliente["empresa_id"], TipoDocumentoFiscal.NFE)
    estado.ultimo_nsu = "777"
    estado.max_nsu = "800"
    sincronizacao.marcar_consumo_indevido(db, estado, motivo="Rejeicao: Consumo Indevido")
    db.commit()

    corpo = client.get("/importacoes/estado").json()
    por_tipo = {item["tipo"]: item for item in corpo}
    nfe = por_tipo["nfe"]
    assert nfe["ultimo_nsu"] == "777"
    assert nfe["max_nsu"] == "800"
    assert nfe["pendencia"] == 23
    assert nfe["em_dia"] is False
    assert nfe["bloqueado_ate"]
    assert nfe["bloqueios_seguidos"] == 1
    assert nfe["razao_social"] == "ARM LOGISTICA E TRANSPORTES LTD"
    # tipos sem histórico aparecem como "começando do zero", não somem
    assert por_tipo["cte"]["ultimo_nsu"] == "0"

    resumo = client.get("/importacoes/resumo").json()
    assert resumo["bloqueadas_sefaz"] == 1
    assert resumo["documentos_no_banco"] == 3
    assert resumo["sincronismo_automatico"] is True


def test_cursor_parado_ha_meses_avisa_do_prazo_da_distribuicao(cliente):
    """
    A distribuição devolve ~3 meses. Cursor parado mais que isso *com
    pendência* significa que a janela de recuperação está fechando — é o único
    caso em que esperar não é a resposta certa, então a tela precisa dizer.
    """
    db = cliente["db"]
    estado = sincronizacao.obter_estado(db, cliente["empresa_id"], TipoDocumentoFiscal.NFE)
    estado.ultimo_nsu = "10"
    estado.max_nsu = "90"
    estado.ultima_consulta_em = datetime.now(timezone.utc) - timedelta(days=120)
    db.commit()

    corpo = cliente["client"].get("/importacoes/estado").json()
    nfe = next(item for item in corpo if item["tipo"] == "nfe")
    assert nfe["dias_sem_varrer"] >= 119
    assert nfe["risco_documento_fora_da_distribuicao"] is True

    # em dia = nada em risco, por mais parado que esteja
    estado.max_nsu = "10"
    db.commit()
    corpo = cliente["client"].get("/importacoes/estado").json()
    nfe = next(item for item in corpo if item["tipo"] == "nfe")
    assert nfe["risco_documento_fora_da_distribuicao"] is False


def test_sincronizacao_por_empresa_tem_os_mesmos_campos_do_painel(cliente):
    """A tela da empresa lê o mesmo schema do painel — sem tradução à parte."""
    db = cliente["db"]
    estado = sincronizacao.obter_estado(db, cliente["empresa_id"], TipoDocumentoFiscal.NFSE)
    estado.ultimo_nsu = "42"
    estado.max_nsu = "42"
    sincronizacao.marcar_sem_novidade(db, estado)
    db.commit()

    corpo = cliente["client"].get(f"/empresas/{cliente['empresa_id']}/sincronizacao").json()
    nfse = next(item for item in corpo if item["tipo"] == "nfse")
    assert nfse["em_dia"] is True
    assert nfse["pendencia"] == 0
    assert nfse["ultimo_nsu"] == "42"
    assert nfse["proxima_consulta_em"]  # a janela de 1h já está marcada


def test_patch_de_empresa_controla_autosync(cliente):
    client, empresa_id = cliente["client"], cliente["empresa_id"]
    resposta = client.patch(
        f"/empresas/{empresa_id}",
        json={"sincronizar_automaticamente": False, "quais_tipos_sincronizar": ["nfse"]},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["sincronizar_automaticamente"] is False
    assert corpo["quais_tipos_sincronizar"] == "nfse"

    sincronizacao_db = cliente["db"]
    sincronizacao_db.expire_all()
    empresa = sincronizacao_db.get(Empresa, empresa_id)
    assert empresa.sincronizar_automaticamente is False

    invalido = client.patch(f"/empresas/{empresa_id}", json={"uf": "XX"})
    assert invalido.status_code == 422
