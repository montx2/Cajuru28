"""
Teste de ponta a ponta do módulo Procurações RFB, via HTTP.

Percorre exatamente o caminho que o operador e a estação percorrem em
produção — painel, fila, protocolo do Agent, evidência, registro da outorga e
do aceite — sem tocar em nenhum serviço externo. O portal da Receita **não** é
chamado: o que o teste verifica é o contrato do nosso lado, e o ponto exato em
que o sistema para e devolve o volante para o humano.
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
from app.procuracoes import modelos as m  # noqa: F401
from app.procuracoes.servicos import agentes as srv_agentes

OUTORGADO = "11222333000181"
CLIENTE = "12345678000195"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128


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
    for indice, (razao, documento) in enumerate(
        [("CLIENTE UM LTDA", CLIENTE), ("CLIENTE DOIS LTDA", "98765432000110")]
    ):
        db.add(
            Empresa(
                escritorio_id=escritorio.id,
                razao_social=razao,
                cnpj_cpf=documento,
                uf="PR",
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
    yield {"cliente": cliente, "db": db, "escritorio": escritorio}
    app.dependency_overrides.clear()
    db.close()


class Estacao:
    """Cliente HTTP que fala o protocolo assinado do Agent."""

    def __init__(self, cliente: TestClient, identificador: str, segredo: str):
        self._http = cliente
        self.identificador = identificador
        resposta = cliente.post(
            "/procuracoes/agente/sessao",
            json={"identificador": identificador, "segredo": segredo},
        )
        resposta.raise_for_status()
        self.chave = resposta.json()["chave_sessao"]

    def binario(self, caminho: str, conteudo: bytes, *, lease: str, tipo: str, params=None):
        """Evidência vai como corpo binário puro; o lease viaja em cabeçalho."""
        agora = datetime.now(timezone.utc).isoformat()
        nonce = secrets.token_hex(16)
        return self._http.post(
            caminho,
            content=conteudo,
            params=params or {},
            headers={
                srv_agentes.CABECALHO_AGENTE: self.identificador,
                "X-Cajuru-Chave": self.chave,
                "X-Cajuru-Lease": lease,
                srv_agentes.CABECALHO_TIMESTAMP: agora,
                srv_agentes.CABECALHO_NONCE: nonce,
                srv_agentes.CABECALHO_ASSINATURA: srv_agentes.assinatura_esperada(
                    self.chave, "POST", caminho, agora, nonce, conteudo
                ),
                "Content-Type": tipo,
            },
        )

    def post(self, caminho: str, payload: dict):
        corpo = json.dumps(payload).encode("utf-8")
        agora = datetime.now(timezone.utc).isoformat()
        nonce = secrets.token_hex(16)
        return self._http.post(
            caminho,
            content=corpo,
            headers={
                srv_agentes.CABECALHO_AGENTE: self.identificador,
                "X-Cajuru-Chave": self.chave,
                srv_agentes.CABECALHO_TIMESTAMP: agora,
                srv_agentes.CABECALHO_NONCE: nonce,
                srv_agentes.CABECALHO_ASSINATURA: srv_agentes.assinatura_esperada(
                    self.chave, "POST", caminho, agora, nonce, corpo
                ),
                "Content-Type": "application/json",
            },
        )


DIAGNOSTICO_OK = {
    "instalado": True,
    "em_execucao": True,
    "hosts_mapeado": True,
    "porta_local": True,
    "certificado_visivel": True,
    "permissao_navegador": True,
    "versao": "4.3.3",
}


def _inventario(documento: str, thumbprint: str, dias: int = 300, tipo: str = "cliente"):
    from datetime import timedelta

    agora = datetime.now(timezone.utc)
    return {
        "thumbprint": thumbprint,
        "documento": documento,
        "subject": f"CN=TITULAR:{documento}",
        "issuer": "AC Teste",
        "numero_serie": thumbprint[:16],
        "titular_nome": f"TITULAR {documento}",
        "valido_de": (agora - timedelta(days=30)).isoformat(),
        "valido_ate": (agora + timedelta(days=dias)).isoformat(),
        "referencia_local": f"win:{thumbprint[:8]}",
        "tipo": tipo,
        "tem_chave_privada": True,
    }


def _preparar(api, *, assinador=DIAGNOSTICO_OK, certificados=None):
    cliente = api["cliente"]
    cliente.put(
        "/procuracoes/configuracao",
        json={
            "outorgado_documento": OUTORGADO,
            "outorgado_nome": "CONTABILIDADE CAJURU LTDA",
            "processamento_automatico": True,
        },
    ).raise_for_status()

    credencial = cliente.post(
        "/procuracoes/agentes", json={"nome": "PC Fiscal 01", "identificador": "a" * 32}
    )
    credencial.raise_for_status()
    estacao = Estacao(cliente, "a" * 32, credencial.json()["segredo"])
    estacao.post(
        "/procuracoes/agente/heartbeat",
        {"versao_agente": "1.0.0", "assinador": assinador},
    ).raise_for_status()
    estacao.post(
        "/procuracoes/agente/inventario",
        {
            "certificados": certificados
            if certificados is not None
            else [
                _inventario(CLIENTE, "a" * 64),
                _inventario(OUTORGADO, "c" * 64, tipo="contabilidade"),
            ]
        },
    ).raise_for_status()
    return estacao


# ---------------------------------------------------------------------------


def test_painel_mostra_empresas_sem_autorizacao(api):
    resposta = api["cliente"].get("/procuracoes/resumo")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total_empresas"] == 2
    assert corpo["sem_autorizacao"] == 2


def test_processar_pendencias_cria_a_fila(api):
    _preparar(api)
    resposta = api["cliente"].post("/procuracoes/processar-pendencias", json={})
    assert resposta.status_code == 200
    assert resposta.json()["criados"] == 2

    repetido = api["cliente"].post("/procuracoes/processar-pendencias", json={})
    assert repetido.json()["criados"] == 0
    assert repetido.json()["ja_na_fila"] == 2


def test_ciclo_ponta_a_ponta_pelo_protocolo_do_agent(api):
    """Critérios A, B e F pela API: nada é concluído sem confirmação real."""
    cliente = api["cliente"]
    estacao = _preparar(api)
    cliente.post("/procuracoes/processar-pendencias", json={}).raise_for_status()

    entrega = estacao.post("/procuracoes/agente/reivindicar", {"capacidade": 1})
    assert entrega.status_code == 200, entrega.text
    ordens = entrega.json()["ordens"]
    assert len(ordens) == 1
    ordem = ordens[0]

    # A ordem de trabalho descreve o que fazer — e nenhum segredo.
    texto = json.dumps(ordem)
    assert "senha" not in texto.lower() or '"senha"' not in texto
    assert "pfx" not in texto.lower()
    assert ordem["certificado_thumbprint"] == "a" * 64
    assert ordem["certificado_referencia"], "a estação precisa saber qual A1 abrir"
    assert ordem["certificado_documento"] == CLIENTE
    assert ordem["certificado_tipo"] == "cliente"
    assert ordem["roteiro"], "a estação precisa do roteiro para guiar o operador"
    assert all(
        passo["url"].startswith("https://") for passo in ordem["roteiro"] if passo["url"]
    )

    job_id, lease = ordem["job_id"], ordem["lease_token"]

    for etapa in ["pre_requisitos", "minhas_autorizacoes", "acesso_portal"]:
        progresso = estacao.post(
            f"/procuracoes/agente/jobs/{job_id}/progresso",
            {"lease_token": lease, "etapa": etapa},
        )
        assert progresso.status_code == 200, progresso.text

    evidencia = estacao.binario(
        f"/procuracoes/agente/jobs/{job_id}/evidencia",
        PNG,
        lease=lease,
        tipo="image/png",
        params={"etapa": "nova_autorizacao_revisao"},
    )
    assert evidencia.status_code == 201, evidencia.text

    estacao.post(
        f"/procuracoes/agente/jobs/{job_id}/progresso",
        {"lease_token": lease, "etapa": "nova_autorizacao_servicos"},
    ).raise_for_status()
    estacao.post(
        f"/procuracoes/agente/jobs/{job_id}/progresso",
        {"lease_token": lease, "etapa": "assinatura"},
    ).raise_for_status()

    concluir = estacao.post(
        f"/procuracoes/agente/jobs/{job_id}/resultado",
        {
            "lease_token": lease,
            "resultado": "outorga_registrada",
            "protocolo": "2026.0009887766",
            "confirmacao_portal": "Autorização de acesso registrada. Situação: Em Análise.",
        },
    )
    assert concluir.status_code == 200, concluir.text
    assert concluir.json()["status"] == "aguardando_validacao"

    detalhe = cliente.get(f"/procuracoes/jobs/{job_id}").json()
    assert detalhe["protocolo"] == "2026.0009887766"
    assert detalhe["evidencias"], "a evidência precisa aparecer no detalhe"

    # Fase 2: aceite com a identidade da contabilidade.
    segunda = estacao.post("/procuracoes/agente/reivindicar", {"capacidade": 1})
    assert segunda.status_code == 200, segunda.text
    ordens2 = segunda.json()["ordens"]
    assert ordens2, f"fase 2 não foi entregue: {cliente.get(f'/procuracoes/jobs/{job_id}').text}"
    ordem2 = next(o for o in ordens2 if o["job_id"] == job_id)
    assert ordem2["fase"] == "aceite"
    assert ordem2["certificado_documento"] == OUTORGADO
    assert ordem2["certificado_tipo"] == "contabilidade"

    estacao.post(
        f"/procuracoes/agente/jobs/{job_id}/progresso",
        {"lease_token": ordem2["lease_token"], "etapa": "validacao"},
    ).raise_for_status()
    aceite = estacao.post(
        f"/procuracoes/agente/jobs/{job_id}/resultado",
        {
            "lease_token": ordem2["lease_token"],
            "resultado": "aceite_registrado",
            "confirmacao_portal": "Autorização validada. Situação: Ativa.",
        },
    )
    assert aceite.status_code == 200, aceite.text
    assert aceite.json()["status"] == "concluido"

    resumo = cliente.get("/procuracoes/resumo").json()
    assert resumo["ativas"] == 1
    assert resumo["sem_autorizacao"] == 1


def test_sem_assinador_o_agent_nao_recebe_trabalho(api):
    """Critério D pela API: recusa explícita e alerta, não silêncio."""
    cliente = api["cliente"]
    estacao = _preparar(
        api, assinador={"instalado": True, "em_execucao": False, "versao": "4.3.3"}
    )
    cliente.post("/procuracoes/processar-pendencias", json={}).raise_for_status()

    resposta = estacao.post("/procuracoes/agente/reivindicar", {"capacidade": 1})
    assert resposta.status_code == 409
    corpo = resposta.json()["detail"]
    assert corpo["codigo"] == "ASSINADOR_NAO_INSTALADO"
    assert corpo.get("pendencias")

    notificacoes = cliente.get("/procuracoes/notificacoes").json()
    assert any(item["tipo"] == "assinador_indisponivel" for item in notificacoes)


def test_certificado_expirado_trava_antes_de_abrir_o_portal(api):
    """Critério C pela API."""
    cliente = api["cliente"]
    estacao = _preparar(api, certificados=[_inventario(CLIENTE, "a" * 64, dias=-1)])
    cliente.post("/procuracoes/processar-pendencias", json={}).raise_for_status()

    resposta = estacao.post("/procuracoes/agente/reivindicar", {"capacidade": 5})
    assert resposta.status_code == 200
    assert resposta.json()["ordens"] == [], "job com A1 vencido não pode ser entregue"

    lista = cliente.get("/procuracoes/jobs").json()
    travados = [
        job
        for job in lista
        if job["codigo_erro"]
        in {"CERTIFICADO_EXPIRADO", "CERTIFICADO_INDISPONIVEL", "CERTIFICADO_NAO_ENCONTRADO"}
    ]
    assert travados, "o motivo precisa estar visível na fila"
    assert travados[0]["status"] in {"intervencao_manual", "falhou"}


def test_certificado_ambiguo_vira_intervencao_manual(api):
    """Critério G pela API: duas opções válidas param o fluxo."""
    cliente = api["cliente"]
    estacao = _preparar(
        api,
        certificados=[
            _inventario(CLIENTE, "a" * 64, dias=100),
            _inventario(CLIENTE, "b" * 64, dias=200),
        ],
    )
    cliente.post("/procuracoes/processar-pendencias", json={}).raise_for_status()
    estacao.post("/procuracoes/agente/reivindicar", {"capacidade": 5})

    lista = cliente.get("/procuracoes/jobs", params={"status": "intervencao_manual"}).json()
    assert any(job["codigo_erro"] == "CERTIFICADO_AMBIGUO" for job in lista)


def test_portal_alterado_interrompe_pela_api(api):
    """Critério E pela API: a estação avisa, o sistema para e explica."""
    cliente = api["cliente"]
    estacao = _preparar(api)
    cliente.post("/procuracoes/processar-pendencias", json={}).raise_for_status()
    ordem = estacao.post("/procuracoes/agente/reivindicar", {"capacidade": 1}).json()[
        "ordens"
    ][0]

    resposta = estacao.post(
        f"/procuracoes/agente/jobs/{ordem['job_id']}/portal-alterado",
        {
            "lease_token": ordem["lease_token"],
            "etapa": "nova_autorizacao_pessoa",
            "ancoras_ausentes": ["Nova Autorização"],
            "url": "https://servicos.receitafederal.gov.br/autorizacoes",
        },
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["status"] == "intervencao_manual"

    detalhe = cliente.get(f"/procuracoes/jobs/{ordem['job_id']}").json()
    assert detalhe["codigo_erro"] == "PORTAL_ALTERADO"

    notificacoes = cliente.get("/procuracoes/notificacoes").json()
    assert any(item["tipo"] == "portal_alterado" for item in notificacoes)


def test_intervencao_manual_e_retomada_preservam_o_ponto(api):
    """Critério F pela API."""
    cliente = api["cliente"]
    estacao = _preparar(api)
    cliente.post("/procuracoes/processar-pendencias", json={}).raise_for_status()
    ordem = estacao.post("/procuracoes/agente/reivindicar", {"capacidade": 1}).json()[
        "ordens"
    ][0]
    job_id, lease = ordem["job_id"], ordem["lease_token"]

    estacao.post(
        f"/procuracoes/agente/jobs/{job_id}/progresso",
        {"lease_token": lease, "etapa": "acesso_portal"},
    ).raise_for_status()
    parada = estacao.post(
        f"/procuracoes/agente/jobs/{job_id}/resultado",
        {
            "lease_token": lease,
            "resultado": "intervencao",
            "codigo_erro": "DESAFIO_DE_SEGURANCA",
            "mensagem": "O portal apresentou verificação adicional.",
        },
    )
    assert parada.status_code == 200
    assert parada.json()["status"] == "intervencao_manual"

    retomada = cliente.post(f"/procuracoes/jobs/{job_id}/retomar", json={})
    assert retomada.status_code == 200
    detalhe = cliente.get(f"/procuracoes/jobs/{job_id}").json()
    assert detalhe["etapa_atual"] == "acesso_portal"
    assert detalhe["status"] != "concluido"


def test_roteiro_publicado_usa_apenas_dominios_oficiais(api):
    itens = api["cliente"].get("/procuracoes/roteiro").json()["passos"]
    assert itens
    from app.procuracoes.portal import url_permitida

    for passo in itens:
        if passo["url"]:
            assert url_permitida(passo["url"]), passo["url"]


def test_importacao_de_planilha_alimenta_o_painel(api):
    api["cliente"].put(
        "/procuracoes/configuracao", json={"outorgado_documento": OUTORGADO}
    ).raise_for_status()
    csv = (
        "cnpj;razao_social;situacao;data_validade\n"
        f"{CLIENTE};CLIENTE UM LTDA;ativa;31/12/2030\n"
    ).encode("utf-8")
    resposta = api["cliente"].post(
        "/procuracoes/importar-planilha",
        files={"arquivo": ("procuracoes.csv", csv, "text/csv")},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["criados"] == 1
    assert api["cliente"].get("/procuracoes/resumo").json()["ativas"] == 1


def test_planilha_sem_outorgado_configurado_explica_o_motivo(api):
    """Ignorar em silêncio é o pior resultado possível numa importação."""
    csv = f"cnpj;situacao\n{CLIENTE};ativa\n".encode("utf-8")
    resposta = api["cliente"].post(
        "/procuracoes/importar-planilha",
        files={"arquivo": ("p.csv", csv, "text/csv")},
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["criados"] == 0 and corpo["ignorados"] == 1
    assert any(erro["codigo"] == "OUTORGADO_NAO_CONFIGURADO" for erro in corpo["erros"])


def test_situacoes_expostas_batem_com_o_dominio(api):
    from app.procuracoes.estados import StatusAutorizacao

    itens = api["cliente"].get("/procuracoes/situacoes").json()
    assert {item["valor"] for item in itens} == {s.value for s in StatusAutorizacao}
    # A aparência (cor/ícone) é decidida no frontend, em lib/estados.ts: a API
    # entrega vocabulário, não estilo.
    assert all(item["rotulo"] for item in itens)


# ---------------------------------------------------------------------------
# Intervenção pedida por PESSOA (não pela estação) e ciclo manual sem Agent
#
# Regressão da trilha real da R10 NOGUEIRA: o endpoint de intervenção caía na
# rede de segurança porque `pendente`/`aguardando_agente` não aceitavam
# intervenção — e gravava evento sem estado anterior, ator "sistema" e código
# de desafio de portal que nunca aconteceu.
# ---------------------------------------------------------------------------


def _job_da_fila(cliente, indice: int = 0) -> int:
    """Job em `aguardando_agente` **sem estação nenhuma** — o cenário do
    escritório que nunca instalou o Agent.

    Nasce por POST /jobs (e não por 'Processar pendências') porque o botão em
    massa já roda a triagem de certificado: sem frota, o job nasceria travado
    em intervenção por `CERTIFICADO_NAO_ENCONTRADO`. Aqui interessa o estado
    de fila puro, esperando estação que não existe."""
    cliente.put(
        "/procuracoes/configuracao",
        json={"outorgado_documento": OUTORGADO, "outorgado_nome": "CONTABILIDADE CAJURU LTDA"},
    ).raise_for_status()
    itens = cliente.get("/procuracoes?tamanho=10").json()["itens"]
    resposta = cliente.post(
        "/procuracoes/jobs", json={"empresa_id": itens[indice]["empresa_id"]}
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()["id"]


def test_operador_assume_job_que_nenhuma_estacao_pegou(api):
    cliente = api["cliente"]
    job_id = _job_da_fila(cliente)
    assert cliente.get(f"/procuracoes/jobs/{job_id}").json()["status"] == (
        "aguardando_agente"
    )

    resposta = cliente.post(
        f"/procuracoes/jobs/{job_id}/intervencao",
        json={"motivo": "Vou fazer no portal agora."},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["status"] == "intervencao_manual"

    detalhe = cliente.get(f"/procuracoes/jobs/{job_id}").json()
    evento = next(
        item for item in detalhe["eventos"] if item["status_novo"] == "intervencao_manual"
    )
    # Trilha honesta: estado anterior preservado, autor humano, código que
    # descreve o que aconteceu — nenhum desafio de portal inventado.
    assert evento["status_anterior"] == "aguardando_agente"
    assert evento["ator"] == "operador:1"
    assert evento["usuario_id"] == 1
    assert evento["ator_rotulo"] == "Admin"
    assert evento["codigo_erro"] == "INTERVENCAO_SOLICITADA"
    assert evento["tipo"] != "intervencao_forcada"
    assert "PORTAL_DESAFIO_ADICIONAL" not in json.dumps(detalhe["eventos"])


def test_intervencao_aceita_codigo_do_catalogo_quando_o_motivo_e_outro(api):
    cliente = api["cliente"]
    job_id = _job_da_fila(cliente)

    resposta = cliente.post(
        f"/procuracoes/jobs/{job_id}/intervencao",
        json={
            "motivo": "Há dois certificados desta empresa na frota.",
            "codigo_erro": "CERTIFICADO_AMBIGUO",
        },
    )
    assert resposta.status_code == 200, resposta.text
    evento = next(
        item
        for item in cliente.get(f"/procuracoes/jobs/{job_id}").json()["eventos"]
        if item["status_novo"] == "intervencao_manual"
    )
    assert evento["codigo_erro"] == "CERTIFICADO_AMBIGUO"

    # Código inventado não vira métrica: 422 na borda.
    outro = _job_da_fila(cliente, indice=1)
    inventado = cliente.post(
        f"/procuracoes/jobs/{outro}/intervencao",
        json={"motivo": "x", "codigo_erro": "CODIGO_QUE_NAO_EXISTE"},
    )
    assert inventado.status_code == 422


def test_registro_manual_do_ciclo_inteiro_sem_nenhuma_estacao(api):
    """O escritório que nunca instalou o Agent precisa conseguir registrar a
    outorga feita à mão e fechar o job — com protocolo, sem estação nenhuma."""
    cliente = api["cliente"]
    job_id = _job_da_fila(cliente)
    cliente.post(f"/procuracoes/jobs/{job_id}/intervencao", json={}).raise_for_status()

    # Sem confirmação do portal, nenhum marco é gravado.
    recusa = cliente.post(f"/procuracoes/jobs/{job_id}/registrar-outorga", json={})
    assert recusa.status_code == 422

    outorga = cliente.post(
        f"/procuracoes/jobs/{job_id}/registrar-outorga",
        json={
            "protocolo": "2026.000123456",
            "confirmacao_portal": "Autorização registrada. Situação: Em Análise.",
        },
    )
    assert outorga.status_code == 200, outorga.text
    assert outorga.json()["status"] == "aguardando_validacao"
    assert outorga.json()["protocolo"] == "2026.000123456"

    detalhe = cliente.get(f"/procuracoes/jobs/{job_id}").json()
    assinado = next(
        item for item in detalhe["eventos"] if item["status_novo"] == "assinado"
    )
    assert assinado["status_anterior"] == "intervencao_manual"
    assert assinado["ator"] == "operador:1"

    def _linha(job_id):
        itens = cliente.get("/procuracoes?tamanho=200").json()["itens"]
        return next(item for item in itens if item["job_id"] == job_id)

    assert _linha(job_id)["situacao"] == "em_analise"

    aceite = cliente.post(
        f"/procuracoes/jobs/{job_id}/registrar-aceite",
        json={"confirmacao_portal": "Autorização validada. Situação: Ativa."},
    )
    assert aceite.status_code == 200, aceite.text
    assert aceite.json()["status"] == "concluido"
    assert _linha(job_id)["situacao"] == "ativa"
    assert _linha(job_id)["protocolo"] == "2026.000123456"


def test_registro_manual_em_job_encerrado_e_recusado(api):
    cliente = api["cliente"]
    job_id = _job_da_fila(cliente)
    cliente.post(
        f"/procuracoes/jobs/{job_id}/cancelar", json={"motivo": "Desistência."}
    ).raise_for_status()

    resposta = cliente.post(
        f"/procuracoes/jobs/{job_id}/registrar-outorga",
        json={"protocolo": "2026.1", "confirmacao_portal": "texto"},
    )
    assert resposta.status_code == 409
