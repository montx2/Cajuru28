"""
Segurança do módulo Procurações RFB.

O que está sendo protegido aqui, em ordem de gravidade:

1. **Nenhum segredo vaza** — nem em log, nem em evento, nem em resposta de API.
2. **Nenhuma estação se passa por outra** — HMAC, nonce e revogação.
3. **Nenhum tenant enxerga outro** — o `escritorio_id` vem do token, não do corpo.
4. **Nenhum arquivo escapa da pasta de evidências** — anti path traversal.
5. **Nenhum perfil de leitura executa ação operacional** — RBAC.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

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
from app.procuracoes.modelos import Agente, JobEvidencia, JobProcuracao
from app.procuracoes.servicos import agentes as srv_agentes
from app.procuracoes.servicos import certificados as srv_cert
from app.procuracoes.servicos import configuracao as srv_config
from app.procuracoes.servicos import eventos as srv_eventos
from app.procuracoes.servicos import evidencias as srv_evid
from app.procuracoes.servicos import fila as srv_fila

OUTORGADO = "11222333000181"
CLIENTE = "12345678000195"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(core_config.settings, "dados_dir", str(tmp_path))
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Sessao = sessionmaker(bind=engine)
    db = Sessao()

    escritorio = Escritorio(nome="Cajuru")
    outro = Escritorio(nome="Concorrente")
    db.add_all([escritorio, outro])
    db.commit()
    db.refresh(escritorio)
    db.refresh(outro)

    admin = Usuario(
        escritorio_id=escritorio.id,
        nome="Admin",
        email="admin@cajuru.local",
        senha_hash="x",
        papel="admin",
        ativo=True,
    )
    leitor = Usuario(
        escritorio_id=escritorio.id,
        nome="Leitor",
        email="leitor@cajuru.local",
        senha_hash="x",
        papel="leitura",
        ativo=True,
    )
    db.add_all([admin, leitor])

    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="CLIENTE LTDA",
        cnpj_cpf=CLIENTE,
        uf="PR",
    )
    db.add(empresa)
    db.commit()
    db.refresh(admin)
    db.refresh(leitor)
    db.refresh(empresa)

    cfg = srv_config.obter_configuracao(db, escritorio.id)
    cfg.outorgado_documento = OUTORGADO
    cfg.processamento_automatico = True
    db.commit()

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
    yield {
        "db": db,
        "Sessao": Sessao,
        "cliente": cliente,
        "escritorio": escritorio,
        "outro": outro,
        "admin": admin,
        "leitor": leitor,
        "empresa": empresa,
    }
    app.dependency_overrides.clear()
    db.close()


def _matricular(db, escritorio_id: int, ident: str = "a" * 32):
    credencial = srv_agentes.registrar_agente(
        db, escritorio_id, nome="Estação Teste", identificador=ident
    )
    db.commit()
    return credencial.agente, credencial.segredo


def _assinar(chave: str, metodo: str, caminho: str, corpo: bytes):
    agora = datetime.now(timezone.utc).isoformat()
    nonce = secrets.token_hex(16)
    assinatura = srv_agentes.assinatura_esperada(chave, metodo, caminho, agora, nonce, corpo)
    return {
        srv_agentes.CABECALHO_TIMESTAMP: agora,
        srv_agentes.CABECALHO_NONCE: nonce,
        srv_agentes.CABECALHO_ASSINATURA: assinatura,
    }


def _cabecalhos(agente: Agente, chave: str, metodo: str, caminho: str, corpo: bytes):
    return {
        srv_agentes.CABECALHO_AGENTE: agente.identificador,
        "X-Cajuru-Chave": chave,
        **_assinar(chave, metodo, caminho, corpo),
    }


# ---------------------------------------------------------------------------
# Segredos
# ---------------------------------------------------------------------------


def test_segredo_do_agent_nunca_e_recuperavel(ambiente):
    db = ambiente["db"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)
    assert segredo not in (agente.segredo_hash or "")
    assert agente.segredo_hash.startswith("$argon2") or agente.segredo_hash.startswith("$2")


def test_evento_redige_campos_sensiveis():
    """Senha, PFX e token não entram na trilha nem por acidente."""
    sujo = {
        "senha": "SenhaSuperSecreta",
        "certificado_pfx": "MIIK...",
        "detalhe": {"password": "x", "cookie_sessao": "abc", "ok": "visivel"},
        "authorization": "Bearer xyz",
    }
    limpo = srv_eventos.sanitizar(sujo)
    texto = json.dumps(limpo, ensure_ascii=False)
    assert "SenhaSuperSecreta" not in texto
    assert "MIIK" not in texto
    assert "Bearer xyz" not in texto
    assert "visivel" in texto, "redação não pode engolir o que é útil"


def test_evidencia_html_tem_senha_redigida(ambiente):
    db = ambiente["db"]
    job = srv_fila.criar_job(db, ambiente["escritorio"].id, ambiente["empresa"]).job
    db.commit()
    html = (
        b"<html><body>senha: MinhaSenha123 "
        b'<input type="password" value="segredo"> </body></html>'
    )
    gravada = srv_evid.gravar(db, job, conteudo=html, tipo_declarado="text/html")
    db.commit()
    conteudo = srv_evid.ler(gravada.registro)
    assert b"MinhaSenha123" not in conteudo
    assert b"segredo" not in conteudo
    assert b"[redigido]" in conteudo


def test_credencial_de_integracao_nunca_volta_na_api(ambiente):
    cliente = ambiente["cliente"]
    resposta = cliente.put(
        "/procuracoes/integracoes",
        json={
            "fonte": "integra_contador",
            "base_url": "https://servicos-online.serpro.gov.br",
            "identificador": "consumer-key",
            "segredo": "token-secreto-do-cliente",
        },
    )
    assert resposta.status_code == 200
    corpo = resposta.text
    assert "token-secreto-do-cliente" not in corpo
    assert resposta.json()["configurado"] is True

    listagem = cliente.get("/procuracoes/integracoes")
    assert "token-secreto-do-cliente" not in listagem.text


# ---------------------------------------------------------------------------
# Autenticação do Agent
# ---------------------------------------------------------------------------


def test_agent_autentica_e_bate_heartbeat(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)

    sessao = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": segredo},
    )
    assert sessao.status_code == 200, sessao.text
    chave = sessao.json()["chave_sessao"]

    corpo = json.dumps(
        {
            "versao_agente": "1.0.0",
            "assinador": {
                "instalado": True,
                "em_execucao": True,
                "hosts_mapeado": True,
                "porta_local": True,
                "certificado_visivel": True,
                "permissao_navegador": True,
                "versao": "4.3.3",
            },
        }
    ).encode("utf-8")
    resposta = cliente.post(
        "/procuracoes/agente/heartbeat",
        content=corpo,
        headers={
            **_cabecalhos(agente, chave, "POST", "/procuracoes/agente/heartbeat", corpo),
            "Content-Type": "application/json",
        },
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["assinador_apto"] is True


def test_assinatura_invalida_e_recusada(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)
    sessao = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": segredo},
    )
    chave = sessao.json()["chave_sessao"]

    corpo = b"{}"
    cabecalhos = _cabecalhos(agente, chave, "POST", "/procuracoes/agente/heartbeat", corpo)
    cabecalhos[srv_agentes.CABECALHO_ASSINATURA] = "0" * 64
    resposta = cliente.post(
        "/procuracoes/agente/heartbeat", content=corpo, headers=cabecalhos
    )
    assert resposta.status_code == 401


def test_corpo_adulterado_invalida_a_assinatura(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)
    chave = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": segredo},
    ).json()["chave_sessao"]

    original = json.dumps({"versao_agente": "1.0.0"}).encode()
    cabecalhos = _cabecalhos(agente, chave, "POST", "/procuracoes/agente/heartbeat", original)
    adulterado = json.dumps({"versao_agente": "9.9.9"}).encode()
    resposta = cliente.post(
        "/procuracoes/agente/heartbeat", content=adulterado, headers=cabecalhos
    )
    assert resposta.status_code == 401


def test_replay_da_mesma_requisicao_e_bloqueado(ambiente):
    """Nonce usado duas vezes = replay. Vale mesmo com assinatura correta."""
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)
    chave = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": segredo},
    ).json()["chave_sessao"]

    corpo = json.dumps({"versao_agente": "1.0.0"}).encode()
    cabecalhos = {
        **_cabecalhos(agente, chave, "POST", "/procuracoes/agente/heartbeat", corpo),
        "Content-Type": "application/json",
    }
    primeira = cliente.post("/procuracoes/agente/heartbeat", content=corpo, headers=cabecalhos)
    segunda = cliente.post("/procuracoes/agente/heartbeat", content=corpo, headers=cabecalhos)
    assert primeira.status_code == 200
    assert segunda.status_code == 409


def test_timestamp_antigo_e_recusado(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)
    chave = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": segredo},
    ).json()["chave_sessao"]

    corpo = b"{}"
    antigo = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    nonce = secrets.token_hex(16)
    resposta = cliente.post(
        "/procuracoes/agente/heartbeat",
        content=corpo,
        headers={
            srv_agentes.CABECALHO_AGENTE: agente.identificador,
            "X-Cajuru-Chave": chave,
            srv_agentes.CABECALHO_TIMESTAMP: antigo,
            srv_agentes.CABECALHO_NONCE: nonce,
            srv_agentes.CABECALHO_ASSINATURA: srv_agentes.assinatura_esperada(
                chave, "POST", "/procuracoes/agente/heartbeat", antigo, nonce, corpo
            ),
        },
    )
    assert resposta.status_code == 401


def test_revogacao_invalida_a_sessao_na_hora(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)
    chave = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": segredo},
    ).json()["chave_sessao"]

    resposta = cliente.post(
        f"/procuracoes/agentes/{agente.id}/revogar", json={"motivo": "notebook roubado"}
    )
    assert resposta.status_code == 200

    corpo = b"{}"
    seguinte = cliente.post(
        "/procuracoes/agente/heartbeat",
        content=corpo,
        headers=_cabecalhos(agente, chave, "POST", "/procuracoes/agente/heartbeat", corpo),
    )
    assert seguinte.status_code == 401


def test_segredo_errado_nao_abre_sessao(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, _ = _matricular(db, ambiente["escritorio"].id)
    resposta = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": "x" * 40},
    )
    assert resposta.status_code == 401
    assert "inválida" in resposta.json()["detail"].lower()


def test_rotacao_de_credencial_derruba_a_sessao_anterior(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)
    chave = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": segredo},
    ).json()["chave_sessao"]

    nova = cliente.post(
        "/procuracoes/agentes",
        json={"nome": "Estação Teste", "identificador": agente.identificador},
    )
    assert nova.status_code == 201
    assert nova.json()["segredo"] != segredo

    corpo = b"{}"
    resposta = cliente.post(
        "/procuracoes/agente/heartbeat",
        content=corpo,
        headers=_cabecalhos(agente, chave, "POST", "/procuracoes/agente/heartbeat", corpo),
    )
    assert resposta.status_code == 401


# ---------------------------------------------------------------------------
# Isolamento entre escritórios
# ---------------------------------------------------------------------------


def test_job_de_outro_escritorio_nao_e_visivel(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    alheio = Empresa(
        escritorio_id=ambiente["outro"].id,
        razao_social="EMPRESA ALHEIA",
        cnpj_cpf="98765432000110",
        uf="SP",
    )
    db.add(alheio)
    db.commit()
    cfg = srv_config.obter_configuracao(db, ambiente["outro"].id)
    cfg.outorgado_documento = "22333444000155"
    db.commit()
    job = srv_fila.criar_job(db, ambiente["outro"].id, alheio).job
    db.commit()

    resposta = cliente.get(f"/procuracoes/jobs/{job.id}")
    assert resposta.status_code == 404


def test_agent_nao_manipula_job_de_outro_escritorio(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)
    chave = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": segredo},
    ).json()["chave_sessao"]

    alheio = Empresa(
        escritorio_id=ambiente["outro"].id,
        razao_social="EMPRESA ALHEIA",
        cnpj_cpf="98765432000110",
        uf="SP",
    )
    db.add(alheio)
    db.commit()
    cfg = srv_config.obter_configuracao(db, ambiente["outro"].id)
    cfg.outorgado_documento = "22333444000155"
    db.commit()
    job = srv_fila.criar_job(db, ambiente["outro"].id, alheio).job
    db.commit()

    caminho = f"/procuracoes/agente/jobs/{job.id}/progresso"
    corpo = json.dumps(
        {"lease_token": "qualquercoisa", "etapa": "pre_requisitos"}
    ).encode()
    resposta = cliente.post(
        caminho,
        content=corpo,
        headers={
            **_cabecalhos(agente, chave, "POST", caminho, corpo),
            "Content-Type": "application/json",
        },
    )
    assert resposta.status_code == 404


def test_agent_sem_lease_nao_mexe_no_job(ambiente):
    db = ambiente["db"]
    cliente = ambiente["cliente"]
    agente, segredo = _matricular(db, ambiente["escritorio"].id)
    chave = cliente.post(
        "/procuracoes/agente/sessao",
        json={"identificador": agente.identificador, "segredo": segredo},
    ).json()["chave_sessao"]
    job = srv_fila.criar_job(db, ambiente["escritorio"].id, ambiente["empresa"]).job
    db.commit()

    caminho = f"/procuracoes/agente/jobs/{job.id}/progresso"
    corpo = json.dumps({"lease_token": "x" * 16, "etapa": "pre_requisitos"}).encode()
    resposta = cliente.post(
        caminho,
        content=corpo,
        headers={
            **_cabecalhos(agente, chave, "POST", caminho, corpo),
            "Content-Type": "application/json",
        },
    )
    assert resposta.status_code == 409


# ---------------------------------------------------------------------------
# Evidências
# ---------------------------------------------------------------------------


def test_evidencia_nao_escapa_da_pasta(ambiente):
    db = ambiente["db"]
    job = srv_fila.criar_job(db, ambiente["escritorio"].id, ambiente["empresa"]).job
    db.commit()
    gravada = srv_evid.gravar(db, job, conteudo=PNG, tipo_declarado="image/png")
    db.commit()

    gravada.registro.caminho_relativo = "../../../etc/passwd"
    with pytest.raises(srv_evid.EvidenciaError):
        srv_evid.ler(gravada.registro)


def test_evidencia_corrompida_e_recusada(ambiente):
    db = ambiente["db"]
    job = srv_fila.criar_job(db, ambiente["escritorio"].id, ambiente["empresa"]).job
    db.commit()
    gravada = srv_evid.gravar(db, job, conteudo=PNG, tipo_declarado="image/png")
    db.commit()
    gravada.registro.sha256 = "0" * 64
    with pytest.raises(srv_evid.EvidenciaError):
        srv_evid.ler(gravada.registro)


def test_evidencia_de_tipo_executavel_e_recusada(ambiente):
    db = ambiente["db"]
    job = srv_fila.criar_job(db, ambiente["escritorio"].id, ambiente["empresa"]).job
    db.commit()
    with pytest.raises(srv_evid.EvidenciaError):
        srv_evid.gravar(
            db, job, conteudo=b"MZ\x90\x00executavel", tipo_declarado="application/x-msdownload"
        )


def test_evidencia_e_cifrada_em_disco(ambiente):
    db = ambiente["db"]
    job = srv_fila.criar_job(db, ambiente["escritorio"].id, ambiente["empresa"]).job
    db.commit()
    gravada = srv_evid.gravar(
        db, job, conteudo=b"conteudo em claro do portal", tipo_declarado="text/plain"
    )
    db.commit()
    bruto = gravada.caminho.read_bytes()
    assert b"conteudo em claro" not in bruto
    assert srv_evid.ler(gravada.registro) == b"conteudo em claro do portal"


# ---------------------------------------------------------------------------
# RBAC e validação de entrada
# ---------------------------------------------------------------------------


def test_perfil_leitura_nao_processa_pendencias(ambiente):
    app.dependency_overrides[usuario_atual] = lambda: ambiente["leitor"]
    resposta = ambiente["cliente"].post("/procuracoes/processar-pendencias", json={})
    assert resposta.status_code == 403
    app.dependency_overrides[usuario_atual] = lambda: ambiente["admin"]


def test_modo_nao_assistido_e_recusado_na_borda(ambiente):
    """A conformidade não depende de o operador ler a documentação."""
    resposta = ambiente["cliente"].put(
        "/procuracoes/configuracao",
        json={
            "outorgado_documento": OUTORGADO,
            "modo_padrao": "nao_assistido",
            "autorizacao_formal_rfb": False,
        },
    )
    assert resposta.status_code == 422
    assert "2.320" in resposta.text


def test_url_de_integracao_precisa_ser_https(ambiente):
    resposta = ambiente["cliente"].put(
        "/procuracoes/integracoes",
        json={
            "fonte": "integra_contador",
            "base_url": "http://api.exemplo.com.br",
            "segredo": "token-de-teste",
        },
    )
    assert resposta.status_code == 422


def test_jettax_nao_tem_mais_adaptador_nem_credencial(ambiente):
    """A integração por API do Jettax foi removida por decisão do produto:
    não existe endpoint público documentado para a tela de procurações.
    Nenhuma rota pode instanciar, testar ou guardar credencial dele."""
    from app.procuracoes.integracoes import registro

    cliente = ambiente["cliente"]

    # Gravar credencial jettax360 é recusado na borda, com o caminho correto.
    resposta = cliente.put(
        "/procuracoes/integracoes",
        json={
            "fonte": "jettax360",
            "base_url": "https://admin.jettax360.com.br",
            "segredo": "token-de-integracao-longo",
        },
    )
    assert resposta.status_code == 422
    assert "Importar lista" in json.dumps(resposta.json()["detail"], ensure_ascii=False)

    # …e o registro de adaptadores não conhece mais a fonte.
    assert "jettax360" not in registro.FONTES_REMOTAS
    with pytest.raises(registro.FonteNaoConfiguradaError):
        registro.construir(ambiente["db"], ambiente["escritorio"].id, "jettax360")

    # Endereço interno continua recusado na integração que existe (SERPRO) —
    # a barreira anti-SSRF não foi embora com o adaptador Jettax.
    from app.procuracoes.integracoes.base import FonteError
    from app.procuracoes.integracoes.integra_contador import ClienteIntegraContador

    with pytest.raises(FonteError):
        ClienteIntegraContador(
            consumer_key="k",
            consumer_secret="s",
            contratante=OUTORGADO,
            autor_pedido=OUTORGADO,
            base_url="https://127.0.0.1/integra-contador",
        )


def test_integra_contador_so_aceita_host_oficial():
    from app.procuracoes.integracoes.base import FonteError
    from app.procuracoes.integracoes.integra_contador import ClienteIntegraContador

    with pytest.raises(FonteError):
        ClienteIntegraContador(
            consumer_key="k",
            consumer_secret="s",
            contratante=OUTORGADO,
            autor_pedido=OUTORGADO,
            base_url="https://gateway.malicioso.com/integra-contador",
        )


def test_trilha_de_auditoria_nao_tem_rota_de_exclusao(ambiente):
    """Não existe endpoint que apague evento de job — nem para admin."""
    caminhos = [
        rota
        for rota in app.openapi()["paths"]
        if "procuracoes" in rota and "evento" in rota
    ]
    for caminho in caminhos:
        assert "delete" not in app.openapi()["paths"][caminho]
