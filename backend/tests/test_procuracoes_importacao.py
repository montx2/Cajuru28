"""
Regressões dos três defeitos que impediam o módulo de operar em produção.

1. **Matrícula de estação pela interface.** A tela manda só o nome; o servidor
   gera o identificador. O teste vai até o fim: matricula, abre sessão com o
   segredo devolvido e bate um heartbeat — se o identificador gerado não
   servisse para o Agent, o heartbeat falharia.
2. **Credencial de integração.** Entrada válida entra; entrada inválida é
   recusada com 422 dizendo **qual campo** e **por quê** (era o que faltava:
   o operador via "parâmetros inválidos" e não sabia se o erro era na URL ou
   no token).
3. **Importação da lista do painel do Jettax.** Formato real da tela (nome
   numa linha, documento na seguinte, cabeçalho e paginação no meio), rodando
   duas vezes sem duplicar, com pendência registrada para documento fora da
   carteira e precedência respeitada entre fontes.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.core import config as core_config
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Empresa, Escritorio, Usuario
from app.procuracoes import modelos as m
from app.procuracoes.servicos import agentes as srv_agentes

OUTORGADO = "11222333000181"
CLIENTE_UM = "12345678000195"
CLIENTE_DOIS = "98765432000110"
FORA_DA_CARTEIRA = "04252011000110"

#: Texto como sai da tela `admin.jettax360.com.br/prevention/ecac/procurations`:
#: título, totalizadores, cabeçalho de coluna, nome numa linha e documento na
#: seguinte, rodapé de paginação. Nada aqui é formato inventado — é a
#: disposição descrita na documentação pública do menu Procurações do Jettax
#: (colunas EMPRESA, CLIENTE, INÍCIO, VENCIMENTO, SITUAÇÃO).
COLAGEM_PAGINA_1 = """Prevenção / e-CAC / Procurações
Ativas de Clientes 120    Expiradas de Clientes 8
EMPRESA\tCLIENTE\tINÍCIO\tVENCIMENTO\tSITUAÇÃO
CLIENTE UM LTDA
12.345.678/0001-95
Sim
01/02/2024
31/12/2030
Válida
CLIENTE DOIS LTDA
98.765.432/0001-10
Sim
15/03/2021
10/01/2025
Expirado
Mostrando 1 a 2 de 3 registros
1 2 … Próximo
"""

#: Segunda página, já com uma linha repetida da primeira (acontece toda vez
#: que a lista é reordenada entre um clique e outro) e um CNPJ que não é
#: cliente do escritório — o painel do Jettax lista também "não clientes".
COLAGEM_PAGINA_2 = """EMPRESA\tCLIENTE\tINÍCIO\tVENCIMENTO\tSITUAÇÃO
CLIENTE UM LTDA
12.345.678/0001-95
Sim
01/02/2024
31/12/2030
Válida
EMPRESA DE FORA SA
04.252.011/0001-10
Não
02/01/2023
02/01/2028
Válida
Página 2 de 2
"""


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(core_config.settings, "dados_dir", str(tmp_path))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Sessao = sessionmaker(bind=engine)
    db = Sessao()

    escritorio = Escritorio(nome="Cajuru")
    db.add(escritorio)
    db.commit()
    db.refresh(escritorio)

    admin = Usuario(
        escritorio_id=escritorio.id,
        nome="Admin",
        email="admin@cajuru.local",
        senha_hash="x",
        papel="admin",
        ativo=True,
    )
    db.add(admin)
    for razao, documento in (
        ("CLIENTE UM LTDA", CLIENTE_UM),
        ("CLIENTE DOIS LTDA", CLIENTE_DOIS),
    ):
        db.add(
            Empresa(
                escritorio_id=escritorio.id,
                razao_social=razao,
                cnpj_cpf=documento,
                uf="MG",
            )
        )
    db.commit()
    db.refresh(admin)

    def _get_db():
        sessao = Sessao()
        try:
            yield sessao
        finally:
            sessao.close()

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: admin
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id
    cliente = TestClient(app)
    cliente.put(
        "/procuracoes/configuracao",
        json={"outorgado_documento": OUTORGADO, "outorgado_nome": "CONTABILIDADE CAJURU"},
    ).raise_for_status()
    yield {"cliente": cliente, "db": db, "escritorio": escritorio}
    app.dependency_overrides.clear()
    db.close()


# ---------------------------------------------------------------------------
# 1. Matrícula de estação pela interface
# ---------------------------------------------------------------------------


def test_matricula_pela_tela_manda_so_o_nome(api):
    """Era o 422 do log de produção: a tela não tem campo de identificador."""
    resposta = api["cliente"].post("/procuracoes/agentes", json={"nome": "PC Fiscal 01"})

    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    identificador = corpo["agente"]["identificador"]
    assert len(identificador) == 32
    assert all(caractere in "0123456789abcdef" for caractere in identificador)
    assert corpo["agente"]["nome"] == "PC Fiscal 01"
    assert len(corpo["segredo"]) >= 32


def test_estacao_matriculada_pela_tela_consegue_operar(api):
    """Identificador gerado pelo servidor precisa servir ao Agent de verdade."""
    cliente = api["cliente"]
    credencial = cliente.post("/procuracoes/agentes", json={"nome": "PC Fiscal 01"}).json()
    identificador = credencial["agente"]["identificador"]

    sessao = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": identificador, "segredo": credencial["segredo"]},
    )
    assert sessao.status_code == 200, sessao.text
    chave = sessao.json()["chave_sessao"]

    corpo = json.dumps({"versao_agente": "1.0.0"}).encode("utf-8")
    agora = datetime.now(timezone.utc).isoformat()
    nonce = secrets.token_hex(16)
    caminho = "/procuracoes/agente/heartbeat"
    heartbeat = cliente.post(
        caminho,
        content=corpo,
        headers={
            "Content-Type": "application/json",
            srv_agentes.CABECALHO_AGENTE: identificador,
            "X-Cajuru-Chave": chave,
            srv_agentes.CABECALHO_TIMESTAMP: agora,
            srv_agentes.CABECALHO_NONCE: nonce,
            srv_agentes.CABECALHO_ASSINATURA: srv_agentes.assinatura_esperada(
                chave, "POST", caminho, agora, nonce, corpo
            ),
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text


def test_duas_matriculas_geram_estacoes_diferentes(api):
    cliente = api["cliente"]
    uma = cliente.post("/procuracoes/agentes", json={"nome": "PC Fiscal 01"}).json()
    outra = cliente.post("/procuracoes/agentes", json={"nome": "PC Fiscal 02"}).json()

    assert uma["agente"]["identificador"] != outra["agente"]["identificador"]
    assert uma["segredo"] != outra["segredo"]
    assert len(cliente.get("/procuracoes/agentes").json()) == 2


def test_recredenciar_mesma_estacao_roda_o_segredo_sem_duplicar(api):
    """Informar o identificador continua valendo: é o caminho de rotação."""
    cliente = api["cliente"]
    primeira = cliente.post("/procuracoes/agentes", json={"nome": "PC Fiscal 01"}).json()
    identificador = primeira["agente"]["identificador"]

    segunda = cliente.post(
        "/procuracoes/agentes",
        json={"nome": "PC Fiscal 01", "identificador": identificador},
    )
    assert segunda.status_code == 201
    assert segunda.json()["agente"]["identificador"] == identificador
    assert segunda.json()["segredo"] != primeira["segredo"]
    assert len(cliente.get("/procuracoes/agentes").json()) == 1

    # O segredo antigo morre no mesmo instante.
    recusa = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": identificador, "segredo": primeira["segredo"]},
    )
    assert recusa.status_code == 401


def test_identificador_com_formato_invalido_continua_recusado(api):
    resposta = api["cliente"].post(
        "/procuracoes/agentes", json={"nome": "PC Fiscal 01", "identificador": "zzz"}
    )
    assert resposta.status_code == 422
    detalhe = resposta.json()["detail"]
    assert detalhe[0]["loc"][-1] == "identificador"
    assert "hexadecimal" in detalhe[0]["msg"]


# ---------------------------------------------------------------------------
# 2. Credencial de integração
# ---------------------------------------------------------------------------


def test_credencial_valida_e_gravada_sem_devolver_o_segredo(api):
    resposta = api["cliente"].put(
        "/procuracoes/integracoes",
        json={
            "fonte": "jettax360",
            "base_url": "https://admin.jettax360.com.br/",
            "segredo": "token-de-integracao-longo",
        },
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["configurado"] is True
    assert corpo["base_url"] == "https://admin.jettax360.com.br"
    assert "token-de-integracao-longo" not in json.dumps(corpo)
    assert "segredo" not in corpo


def test_url_sem_https_diz_qual_campo_e_como_corrigir(api):
    """Exatamente o que o operador digitou em produção."""
    resposta = api["cliente"].put(
        "/procuracoes/integracoes",
        json={
            "fonte": "jettax360",
            "base_url": "admin.jettax360.com.br",
            "segredo": "token-de-integracao-longo",
        },
    )
    assert resposta.status_code == 422
    erro = resposta.json()["detail"][0]
    assert erro["loc"][-1] == "base_url"
    assert "https://" in erro["msg"]


def test_http_puro_e_recusado_com_motivo(api):
    resposta = api["cliente"].put(
        "/procuracoes/integracoes",
        json={
            "fonte": "jettax360",
            "base_url": "http://admin.jettax360.com.br",
            "segredo": "token-de-integracao-longo",
        },
    )
    assert resposta.status_code == 422
    erro = resposta.json()["detail"][0]
    assert erro["loc"][-1] == "base_url"
    assert "texto claro" in erro["msg"]


def test_segredo_curto_diz_o_tamanho_esperado(api):
    resposta = api["cliente"].put(
        "/procuracoes/integracoes",
        json={"fonte": "jettax360", "base_url": "https://admin.jettax360.com.br", "segredo": "curto"},
    )
    assert resposta.status_code == 422
    erro = resposta.json()["detail"][0]
    assert erro["loc"][-1] == "segredo"
    assert "8 caracteres" in erro["msg"]


def test_segredo_em_branco_nao_apaga_a_credencial_existente(api):
    cliente = api["cliente"]
    cliente.put(
        "/procuracoes/integracoes",
        json={
            "fonte": "jettax360",
            "base_url": "https://admin.jettax360.com.br",
            "segredo": "token-de-integracao-longo",
        },
    ).raise_for_status()

    resposta = cliente.put(
        "/procuracoes/integracoes",
        json={"fonte": "jettax360", "base_url": "https://admin.jettax360.com.br", "segredo": "   "},
    )
    assert resposta.status_code == 422
    assert resposta.json()["detail"][0]["loc"][-1] == "segredo"
    assert cliente.get("/procuracoes/integracoes").json()[0]["configurado"] is True


# ---------------------------------------------------------------------------
# 3. Importação da lista colada do painel
# ---------------------------------------------------------------------------


def _importar(cliente: TestClient, texto: str, **extra):
    corpo = {"texto": texto, "fonte": "jettax360"}
    corpo.update(extra)
    resposta = cliente.post("/procuracoes/importar-lista", json=corpo)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def test_colagem_da_tela_vira_autorizacao(api):
    resultado = _importar(api["cliente"], COLAGEM_PAGINA_1)

    assert resultado["recebidos"] == 2
    assert resultado["criados"] == 2
    assert resultado["ignorados"] == 0

    linhas = {
        item["documento"]: item
        for item in api["cliente"].get("/procuracoes").json()["itens"]
    }
    assert linhas[CLIENTE_UM]["situacao"] == "ativa"
    assert linhas[CLIENTE_UM]["data_validade"] == "2030-12-31"
    assert linhas[CLIENTE_UM]["origem_dado"] == "jettax360"
    # "Expirado" na tela + vencimento no passado: continua expirada.
    assert linhas[CLIENTE_DOIS]["situacao"] == "expirada"


def test_importar_duas_vezes_nao_duplica(api):
    cliente = api["cliente"]
    primeira = _importar(cliente, COLAGEM_PAGINA_1)
    segunda = _importar(cliente, COLAGEM_PAGINA_1)

    assert primeira["criados"] == 2
    assert segunda["criados"] == 0
    assert segunda["atualizados"] == 0
    assert segunda["inalterados"] == 2

    autorizacoes = api["db"].query(m.Autorizacao).all()
    assert len(autorizacoes) == 2
    assert len({(a.empresa_id, a.outorgado_documento) for a in autorizacoes}) == 2


def test_paginas_com_sobreposicao_nao_duplicam(api):
    """Colar página 1 e depois página 2 é o fluxo real — e elas se repetem."""
    cliente = api["cliente"]
    _importar(cliente, COLAGEM_PAGINA_1)
    segunda = _importar(cliente, COLAGEM_PAGINA_2)

    assert segunda["criados"] == 0
    assert segunda["inalterados"] == 1  # CLIENTE UM veio de novo, igual
    assert segunda["ignorados"] == 1  # a empresa de fora da carteira
    assert len(api["db"].query(m.Autorizacao).all()) == 2


def test_documento_fora_da_carteira_vira_pendencia_e_nao_empresa(api):
    cliente = api["cliente"]
    resultado = _importar(cliente, COLAGEM_PAGINA_2)

    pendencias = [e for e in resultado["erros"] if e["codigo"] == "EMPRESA_NAO_CADASTRADA"]
    assert len(pendencias) == 1
    assert pendencias[0]["documento"] == FORA_DA_CARTEIRA
    assert pendencias[0]["nome"] == "EMPRESA DE FORA SA"
    assert "Cadastre a empresa" in pendencias[0]["mensagem"]

    # Nenhuma empresa fantasma foi criada.
    documentos = {e.cnpj_cpf for e in api["db"].query(Empresa).all()}
    assert documentos == {CLIENTE_UM, CLIENTE_DOIS}

    # E a pendência ficou gravada no histórico, não só na resposta.
    registrado = (
        api["db"]
        .query(m.IntegracaoErro)
        .filter(m.IntegracaoErro.codigo == "EMPRESA_NAO_CADASTRADA")
        .all()
    )
    assert [erro.nome for erro in registrado] == ["EMPRESA DE FORA SA"]


def test_job_de_integracao_registra_o_que_entrou(api):
    cliente = api["cliente"]
    _importar(cliente, COLAGEM_PAGINA_1)

    job = api["db"].query(m.IntegracaoJob).order_by(m.IntegracaoJob.id.desc()).first()
    assert job is not None
    assert job.fonte == "jettax360"
    assert job.origem == "colagem"
    assert job.status == "concluido"
    assert job.registros_recebidos == 2
    assert job.registros_criados == 2
    assert job.finalizado_em is not None


def test_colagem_so_com_nome_e_documento_vira_pendencia_explicativa(api):
    """Sem situação e sem data, o módulo não inventa: devolve o que fazer."""
    resultado = _importar(
        api["cliente"],
        "CLIENTE UM LTDA\n12.345.678/0001-95\nCLIENTE DOIS LTDA\n98.765.432/0001-10\n",
    )
    assert resultado["criados"] == 0
    codigos = {erro["codigo"] for erro in resultado["erros"]}
    assert codigos == {"SITUACAO_INDETERMINADA"}
    assert "Situação da aba" in resultado["erros"][0]["mensagem"]
    assert api["db"].query(m.Autorizacao).count() == 0


def test_aba_declarada_resolve_a_colagem_sem_situacao(api):
    resultado = _importar(
        api["cliente"],
        "CLIENTE UM LTDA\n12.345.678/0001-95\nCLIENTE DOIS LTDA\n98.765.432/0001-10\n",
        situacao_padrao="ativa",
    )
    assert resultado["criados"] == 2
    situacoes = {a.situacao for a in api["db"].query(m.Autorizacao).all()}
    assert situacoes == {"ativa"}


def test_planilha_nao_sobrescreve_o_que_veio_do_jettax(api):
    """Precedência: integra_contador > jettax360 > planilha > manual."""
    cliente = api["cliente"]
    _importar(cliente, COLAGEM_PAGINA_1)

    csv = (
        "cnpj;razao_social;situacao;data_validade\n"
        "12.345.678/0001-95;CLIENTE UM LTDA;cancelada;\n"
    ).encode()
    resposta = cliente.post(
        "/procuracoes/importar-planilha",
        files={"arquivo": ("carteira.csv", csv, "text/csv")},
        data={"fonte_declarada": "planilha"},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["ignorados"] == 1

    autorizacao = (
        api["db"]
        .query(m.Autorizacao)
        .filter(m.Autorizacao.outorgante_documento == CLIENTE_UM)
        .first()
    )
    assert autorizacao.situacao == "ativa"
    assert autorizacao.origem_dado == "jettax360"


def test_arquivo_exportado_do_painel_pode_ser_declarado_como_jettax(api):
    """Export do painel é dado do Jettax — quem declara a origem é o operador."""
    cliente = api["cliente"]
    exportado = (
        "EMPRESA;CLIENTE;CNPJ;INÍCIO;VENCIMENTO;SITUAÇÃO\n"
        "CLIENTE UM LTDA;Sim;12.345.678/0001-95;01/02/2024;31/12/2030;Válida\n"
    ).encode()
    resposta = cliente.post(
        "/procuracoes/importar-planilha",
        files={"arquivo": ("procuracoes.csv", exportado, "text/csv")},
        data={"fonte_declarada": "jettax360"},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["criados"] == 1

    autorizacao = api["db"].query(m.Autorizacao).first()
    assert autorizacao.origem_dado == "jettax360"
    # A coluna CLIENTE ("Sim") não pode virar razão social.
    assert autorizacao.outorgante_nome == "CLIENTE UM LTDA"


def test_arquivo_sem_cabecalho_cai_no_leitor_de_colagem(api):
    """Nem todo export tem cabeçalho; o conteúdo decide o leitor, não a extensão."""
    cliente = api["cliente"]
    bruto = "CLIENTE UM LTDA\t12.345.678/0001-95\tSim\t01/02/2024\t31/12/2030\tVálida\n".encode()
    resposta = cliente.post(
        "/procuracoes/importar-planilha",
        files={"arquivo": ("lista.txt", bruto, "text/plain")},
        data={"fonte_declarada": "jettax360"},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["criados"] == 1


def test_documento_sem_mascara_com_dv_quebrado_vira_pendencia_visivel(api):
    """Some da importação, mas não do relatório: é erro de cópia."""
    resultado = _importar(
        api["cliente"],
        "EMPRESA\tCLIENTE\tVENCIMENTO\tSITUAÇÃO\n"
        "CLIENTE UM LTDA\n11111111111199\nSim\n31/12/2030\nVálida\n",
    )
    assert resultado["criados"] == 0
    invalidos = [e for e in resultado["erros"] if e["codigo"] == "DOCUMENTO_INVALIDO"]
    assert len(invalidos) == 1
    assert invalidos[0]["documento"] == "11111111111199"
    assert invalidos[0]["nome"] == "CLIENTE UM LTDA"


def test_cnpj_sem_mascara_valido_e_aceito(api):
    resultado = _importar(
        api["cliente"],
        "CLIENTE UM LTDA\n12345678000195\nSim\n01/02/2024\n31/12/2030\nVálida\n",
    )
    assert resultado["criados"] == 1


def test_texto_sem_nenhum_documento_e_recusado_com_clareza(api):
    resposta = api["cliente"].post(
        "/procuracoes/importar-lista",
        json={"texto": "EMPRESA CLIENTE INÍCIO VENCIMENTO SITUAÇÃO", "fonte": "jettax360"},
    )
    assert resposta.status_code == 200
    assert resposta.json()["recebidos"] == 0
    assert resposta.json()["criados"] == 0


def test_colagem_vazia_e_recusada(api):
    resposta = api["cliente"].post(
        "/procuracoes/importar-lista", json={"texto": "   ", "fonte": "jettax360"}
    )
    assert resposta.status_code == 422
