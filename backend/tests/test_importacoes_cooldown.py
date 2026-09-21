"""
Janelas de consumo (o que evita o cStat 656).

Antes, o cooldown era deduzido do histórico de execuções ("a última concluiu
com 0 notas? então espera"). Isso tinha dois buracos que o teste de regressão
precisa cobrir:

1. uma execução que **terminou em erro por 656** não gerava cooldown nenhuma —
   então o próximo clique batia de novo no bloqueio e zerava o cronômetro;
2. o cálculo olhava a execução mais *recente*, não a maior; uma varredura
   incompleta no meio rebaixava o cursor e "consultar fora da sequência" é,
   ela própria, motivo de bloqueio.

Agora o estado mora em `sincronizacoes_dfe` (uma linha por empresa+tipo).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    Certificado,
    DocumentoFiscal,
    Empresa,
    Escritorio,
    ExecucaoImportacao,
    SincronizacaoDFe,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.services import sincronizacao
from app.services.sincronizacao import cooldown_oficial


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
        cnpj_cpf="12345678000199",
        uf="SP",
    )
    sessao.add(empresa)
    sessao.commit()
    yield sessao, empresa.id
    sessao.close()


def test_empresa_nova_pode_ser_consultada_imediatamente(db):
    sessao, empresa_id = db
    libertacao = sincronizacao.liberacao_para(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    assert libertacao.pode is True
    assert libertacao.esperar_segundos == 0


def test_depois_de_nada_novo_espera_a_janela_oficial(db):
    """Regra 137 ⇒ 1h: é o cooldown que a própria NT 2014.002 exige."""
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    agora = datetime.now(timezone.utc)
    quando = sincronizacao.marcar_sem_novidade(sessao, estado, agora=agora)
    sessao.commit()

    libertacao = sincronizacao.liberacao_para(sessao, empresa_id, TipoDocumentoFiscal.NFSE, agora=agora)
    assert libertacao.pode is False
    assert libertacao.bloqueado is False
    assert quando == agora + cooldown_oficial()
    # falta pouco mais de 59 minutos (1h + margem de segurança)
    assert 59 * 60 <= libertacao.esperar_segundos <= 67 * 60


def test_janela_expira_sozinha_com_o_tempo(db):
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    agora = datetime.now(timezone.utc)
    sincronizacao.marcar_sem_novidade(sessao, estado, agora=agora)
    sessao.commit()

    depois = sincronizacao.liberacao_para(
        sessao, empresa_id, TipoDocumentoFiscal.NFSE, agora=agora + cooldown_oficial() + timedelta(seconds=1)
    )
    assert depois.pode is True


def test_documento_novo_liquidando_a_espera(db):
    """Trouxe documento? Existe fila de distribuição: não faz sentido esperar."""
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    sincronizacao.marcar_sem_novidade(sessao, estado)
    sincronizacao.marcar_consulta_ok(sessao, estado)
    sessao.commit()

    assert sincronizacao.liberacao_para(sessao, empresa_id, TipoDocumentoFiscal.NFSE).pode is True


def test_bloqueio_656_e_agendado_para_depois_da_hora_inteira(db):
    """O caso do bug: erro por 656 precisa gerar ESPERA, não só mensagem vermelha."""
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFE)
    agora = datetime.now(timezone.utc)
    quando = sincronizacao.marcar_consumo_indevido(
        sessao, estado, motivo="Rejeicao: Consumo Indevido", agora=agora
    )
    sessao.commit()

    libertacao = sincronizacao.liberacao_para(sessao, empresa_id, TipoDocumentoFiscal.NFE, agora=agora)
    assert libertacao.pode is False
    assert libertacao.bloqueado is True
    assert quando > agora + timedelta(minutes=59)
    assert estado.bloqueios_seguidos == 1


def test_janela_e_por_tipo_nfe_bloqueada_nao_trava_nfse(db):
    sessao, empresa_id = db
    estado_nfse = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    sincronizacao.marcar_sem_novidade(sessao, estado_nfse)
    sessao.commit()

    assert sincronizacao.liberacao_para(sessao, empresa_id, TipoDocumentoFiscal.NFSE).pode is False
    assert sincronizacao.liberacao_para(sessao, empresa_id, TipoDocumentoFiscal.NFE).pode is True


def test_cursor_nunca_regride(db):
    """Rebaixar o cursor = consulta fora da sequência = 656. Está travado aqui."""
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFE)
    sincronizacao.avançar_cursor(sessao, estado, ultimo_nsu="1000", max_nsu="1200")
    sincronizacao.avançar_cursor(sessao, estado, ultimo_nsu="900")
    assert estado.ultimo_nsu == "1000"
    assert estado.max_nsu == "1200"
    assert sincronizacao.pendencia_de_documentos(estado) == 200
    assert sincronizacao.esta_em_dia(estado) is False

    sincronizacao.avançar_cursor(sessao, estado, ultimo_nsu="1200", max_nsu="1200")
    assert sincronizacao.esta_em_dia(estado) is True
    assert sincronizacao.pendencia_de_documentos(estado) == 0


def test_rebobinar_cursor_permite_revarrer_e_libera_a_consulta(db):
    """A recuperação manual volta o cursor e elimina janelas antigas."""
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    agora = datetime.now(timezone.utc)
    sincronizacao.avançar_cursor(sessao, estado, ultimo_nsu="35", max_nsu="35", agora=agora)
    sincronizacao.marcar_sem_novidade(sessao, estado, agora=agora)
    sincronizacao.marcar_consumo_indevido(sessao, estado, motivo="656", agora=agora)
    sessao.commit()

    # O avanço normal nunca regride; a recuperação manual é a exceção explícita.
    sincronizacao.avançar_cursor(sessao, estado, ultimo_nsu="0", agora=agora)
    assert estado.ultimo_nsu == "35"

    movimento = sincronizacao.rebobinar_cursor(sessao, estado, ultimo_nsu="0", agora=agora)
    assert movimento == {"de": "35", "para": "0"}
    assert estado.ultimo_nsu == "0"
    assert estado.proxima_consulta_em is None
    assert estado.bloqueado_ate is None
    assert sincronizacao.liberacao_para(
        sessao, empresa_id, TipoDocumentoFiscal.NFSE, agora=agora
    ).pode is True


def test_rebobinar_nunca_pula_o_cursor_para_frente(db):
    """Um endpoint de recuperação não pode virar uma forma de perder NSUs."""
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFE)
    sincronizacao.avançar_cursor(sessao, estado, ultimo_nsu="35", max_nsu="35")

    movimento = sincronizacao.rebobinar_cursor(sessao, estado, ultimo_nsu="999")
    assert movimento == {"de": "35", "para": "35"}
    assert estado.ultimo_nsu == "35"


def test_realinhe_aceita_o_nsu_que_a_sefaz_devolveu(db):
    """
    Quando outro sistema consome o CNPJ, o ambiente responde 656 informando o
    ultNSU que ele esperava. Adotar esse valor é o que destrava o loop.
    """
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFE)
    sincronizacao.avançar_cursor(sessao, estado, ultimo_nsu="500")
    assert estado.ultimo_nsu == "500"

    mudou = sincronizacao.realinhar_cursor(sessao, estado, ultimo_nsu="4200", max_nsu="4210")
    assert mudou is True
    assert estado.ultimo_nsu == "4200"
    assert estado.max_nsu == "4210"


def test_cota_pontual_de_20_consultas_por_hora(db):
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFE)
    agora = datetime.now(timezone.utc)
    assert sincronizacao.cota_pontual_disponivel(sessao, estado, agora=agora) == 20

    for _ in range(20):
        sincronizacao.consumir_cota_pontual(sessao, estado, agora=agora)
    assert sincronizacao.cota_pontual_disponivel(sessao, estado, agora=agora) == 0

    # uma hora depois a janela reinicia sozinha
    assert sincronizacao.cota_pontual_disponivel(
        sessao, estado, agora=agora + timedelta(hours=1, minutes=1)
    ) == 20


def test_lease_impede_duas_varreduras_no_mesmo_cnpj(db):
    """Duas tasks no mesmo CNPJ brigam pelo NSU — é a regra nº 2 de uso indevido."""
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    assert sincronizacao.travar(sessao, estado) is True
    sessao.commit()
    assert sincronizacao.travar(sessao, estado) is False

    sincronizacao.liberar(sessao, estado)
    sessao.commit()
    assert sincronizacao.travar(sessao, estado) is True


def test_lease_vence_se_o_worker_morrer(db):
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    muito_atras = datetime.now(timezone.utc) - sincronizacao.LEASE_MAXIMO - timedelta(minutes=1)
    estado.travado_em = muito_atras
    sessao.commit()
    assert sincronizacao.esta_travado(estado) is False
    assert sincronizacao.travar(sessao, estado) is True


def test_execucao_antiga_vira_estado_na_migracao(tmp_path):
    """
    Upgrade sem perder o checkpoint: empresas que já importavam não podem voltar
    ao NSU 0 — é a receita exata do "Consumo Indevido".
    """
    from app.db import migracoes
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="E")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(escritorio_id=escritorio.id, razao_social="R", cnpj_cpf="111", uf="SP")
    sessao.add(empresa)
    sessao.flush()
    for nsu in ("900", "1200"):
        sessao.add(
            ExecucaoImportacao(
                empresa_id=empresa.id,
                tipo=TipoDocumentoFiscal.NFE,
                status=StatusExecucao.CONCLUIDA,
                ultimo_nsu=nsu,
            )
        )
    sessao.commit()

    original = migracoes.engine
    migracoes.engine = engine
    try:
        migracoes._semear_sincronizacoes()
        estado = sessao.query(SincronizacaoDFe).one()
        assert estado.ultimo_nsu == "1200"  # o MAIOR, não o último registrado
    finally:
        migracoes.engine = original


def test_consumo_indevido_usa_tempo_exato_quando_informado(db):
    """Com `bloqueio` (ex.: Retry-After do ADN), a espera é a exata, não 1h."""
    from datetime import timedelta

    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    agora = datetime.now(timezone.utc)

    quando = sincronizacao.marcar_consumo_indevido(
        sessao, estado, motivo="429", bloqueio=timedelta(seconds=120), agora=agora
    )
    assert quando == agora + timedelta(seconds=120)  # exato, não o cooldown de 1h

    # Sem `bloqueio`, cai no cooldown oficial (1h + margem).
    quando_padrao = sincronizacao.marcar_consumo_indevido(
        sessao, estado, motivo="656", agora=agora
    )
    assert quando_padrao == agora + cooldown_oficial()


def test_liberacao_respeita_o_relogio_mais_tarde(db):
    """Se bloqueio e janela existem juntos, consultar antes do último vencer reinicia o bloqueio."""
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFE)
    agora = datetime.now(timezone.utc)
    estado.bloqueado_ate = agora + timedelta(minutes=20)
    estado.proxima_consulta_em = agora + timedelta(minutes=55)
    estado.motivo_bloqueio = "656 antigo"
    sessao.commit()

    libertacao = sincronizacao.liberacao_para(sessao, empresa_id, TipoDocumentoFiscal.NFE, agora=agora)
    assert libertacao.pode is False
    assert libertacao.quando.replace(tzinfo=None) == estado.proxima_consulta_em
    assert libertacao.bloqueado is False


def test_consulta_ok_e_sem_novidade_limpam_bloqueio_antigo(db):
    """Bloqueio vencido não pode ficar sujando painel/prévia depois de uma consulta válida."""
    sessao, empresa_id = db
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFE)
    agora = datetime.now(timezone.utc)
    estado.bloqueado_ate = agora - timedelta(minutes=5)
    estado.motivo_bloqueio = "656 vencido"
    estado.bloqueios_seguidos = 3

    sincronizacao.marcar_consulta_ok(sessao, estado, agora=agora)
    assert estado.bloqueado_ate is None
    assert estado.motivo_bloqueio is None
    assert estado.bloqueios_seguidos == 0

    estado.bloqueado_ate = agora - timedelta(minutes=5)
    estado.motivo_bloqueio = "656 vencido de novo"
    estado.bloqueios_seguidos = 2
    proxima = sincronizacao.marcar_sem_novidade(sessao, estado, agora=agora)
    assert estado.proxima_consulta_em == proxima
    assert estado.bloqueado_ate is None
    assert estado.motivo_bloqueio is None
    assert estado.bloqueios_seguidos == 0


def test_completar_xml_respeita_janela_antes_de_consultar(db, tmp_path, monkeypatch):
    """consChNFe também precisa respeitar a 1h; antes gastava cota e tomava 656."""
    from app.worker import tasks

    sessao, empresa_id = db
    caminho_xml = tmp_path / "resumo.xml"
    caminho_xml.write_text("<resNFe />", encoding="utf-8")
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
            tipo=TipoDocumentoFiscal.NFE,
            direcao="tomada",
            chave_acesso="35260812345678000199550010000000055555555555",
            nsu="55",
            data_emissao=datetime(2026, 8, 20, tzinfo=timezone.utc),
            competencia=datetime(2026, 8, 20, tzinfo=timezone.utc).date(),
            valor_total=0.0,
            xml_path=str(caminho_xml),
            leiaute="resumo",
            # Já manifestada: só assim a nota entra na fila do consChNFe.
            manifestado_em=datetime.now(timezone.utc),
        )
    )
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFE)
    sincronizacao.marcar_sem_novidade(sessao, estado, agora=datetime.now(timezone.utc))
    sessao.commit()

    chamado = {"valor": False}

    class ImportadorFake:
        def buscar_por_chave(self, **kwargs):  # pragma: no cover - deveria ficar sem chamada
            chamado["valor"] = True
            raise AssertionError("não deveria consultar dentro da janela")

    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=sessao.get_bind()))
    monkeypatch.setattr(tasks, "obter_importador", lambda tipo: ImportadorFake())

    resultado = tasks.completar_xmls_pendentes()
    sessao.expire_all()
    estado = sincronizacao.obter_estado(sessao, empresa_id, TipoDocumentoFiscal.NFE)
    assert resultado["aguardando_janela"] == 1
    assert chamado["valor"] is False
    assert (estado.consultas_pontuais or 0) == 0
