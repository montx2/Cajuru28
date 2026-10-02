"""Regressões de captura incompleta, cursor, replay durável e agendamento.

As respostas oficiais são simuladas; estes testes nunca consultam SEFAZ/ADN.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core import config
from app.models import Certificado, DocumentoFiscal, Empresa, ExecucaoImportacao, StatusExecucao, TipoDocumentoFiscal
from app.services import fila, lotes_recebidos, sincronizacao
from app.services.importadores._distribuicao_dfe import competencia_de_texto
from app.services.importadores.base import LoteImportado
from app.services.importadores.nfse_adn import ImportadorNFSeADN
from app.worker import tasks
from test_worker_importacao_fluxo import _item_adn, _montar_cenario

NFSE = TipoDocumentoFiscal.NFSE
CNPJ = "12345678000199"
CHAVE1 = "35260112345678000199550010000000011234567890"
CHAVE2 = "35260112345678000199550010000000021234567891"


def _payload(nsu=1, max_nsu=1, chave=CHAVE1):
    return {"LoteDFe": [_item_adn(nsu, chave, "2026-01-05T09:00:00-03:00")], "UltNSU": nsu, "MaxNSU": max_nsu}


@pytest.fixture
def cenario(tmp_path, monkeypatch):
    db, empresa = _montar_cenario(tmp_path, monkeypatch)
    empresa.quais_tipos_sincronizar = "nfse"
    db.commit()
    monkeypatch.setattr(tasks, "ESPERA_ENTRE_LOTES", 0)
    monkeypatch.setattr(config.settings, "sincronismo_automatico", True)
    disparos = []
    monkeypatch.setattr(fila, "_disparar", lambda *args, **kwargs: disparos.append((args, kwargs)))
    monkeypatch.setattr(tasks.importar_documentos, "delay", lambda *args, **kwargs: disparos.append((args, kwargs)))
    monkeypatch.setattr(tasks.importar_documentos, "apply_async", lambda *args, **kwargs: disparos.append((args, kwargs)))
    yield db, empresa, disparos
    db.close()


def _nova_execucao(db, empresa, **kwargs):
    execucao = ExecucaoImportacao(empresa_id=empresa.id, tipo=NFSE, **kwargs)
    db.add(execucao)
    db.commit()
    return execucao.id


def _rodar(db, empresa, execucao_id):
    tasks.importar_documentos(empresa.id, "nfse", execucao_id)
    db.expire_all()
    return db.get(ExecucaoImportacao, execucao_id)


def test_adn_nao_para_na_pagina_curta_se_maxnsu_indica_mais():
    lote = ImportadorNFSeADN()._interpretar(_payload(1, 3), CNPJ, "0")
    assert len(lote.documentos) == 1
    assert lote.ha_mais_documentos is True
    assert lote.max_nsu == "3"


def test_adn_sem_maxnsu_continua_ate_resposta_sem_novidade():
    payload = _payload()
    payload.pop("MaxNSU")
    lote = ImportadorNFSeADN()._interpretar(payload, CNPJ, "0")
    assert lote.ha_mais_documentos is True
    assert lote.max_nsu is None


def test_adn_cursor_inclui_o_maior_item_recebido():
    payload = _payload(8, 9)
    payload["UltNSU"] = 7
    assert ImportadorNFSeADN()._interpretar(payload, CNPJ, "0").proximo_nsu == "8"


def test_adn_json_inesperado_nao_e_acervo_vazio():
    lote = ImportadorNFSeADN()._interpretar({"texto": "gateway indisponível"}, CNPJ, "100")
    assert lote.sem_novidade is False
    assert lote.erros
    assert lote.proximo_nsu == "100"
    assert lote.resposta_bruta


def test_competencia_mensal_nao_causa_indexerror():
    assert competencia_de_texto("2026-08", "2026-09-02") == "2026-08-01"
    assert competencia_de_texto("", "2026-09-02T12:30:00-03:00") == "2026-09-02"


def test_adn_xml_malformado_nao_vira_nota_vazia_com_data_atual():
    payload = _payload()
    payload["LoteDFe"][0]["ArquivoXml"] = "<NFSe><infNFSe>"
    lote = ImportadorNFSeADN()._interpretar(payload, CNPJ, "0")
    assert lote.documentos == []
    assert lote.erros
    assert lote.resposta_bruta


def test_worker_pagina_curta_importa_proximas_notas(cenario, monkeypatch):
    db, empresa, _ = cenario
    chamadas = []

    def resposta(self, url, *args, **kwargs):
        chamadas.append(url)
        return 200, _payload(1, 2) if url.endswith("/0") else _payload(2, 2, CHAVE2)

    monkeypatch.setattr(ImportadorNFSeADN, "_chamar_com_retentativa", resposta)
    execucao = _rodar(db, empresa, _nova_execucao(db, empresa))
    assert execucao.status == StatusExecucao.CONCLUIDA
    assert execucao.documentos_importados == 2
    assert len(chamadas) == 2
    assert execucao.ultimo_nsu == "2"
    assert db.query(DocumentoFiscal).count() == 2
    assert lotes_recebidos.quantidade_pendente(empresa.id, NFSE) == 0


def test_lote_parcial_fica_preservado_e_nao_finge_sucesso(cenario, monkeypatch):
    db, empresa, _ = cenario
    payload = _payload(1, 2)
    ruim = _payload(2, 2, CHAVE2)["LoteDFe"][0]
    ruim["ArquivoXml"] = "nao-e-xml"
    payload["LoteDFe"].append(ruim)
    payload["UltNSU"] = 2
    monkeypatch.setattr(ImportadorNFSeADN, "_chamar_com_retentativa", lambda *args, **kwargs: (200, payload))
    execucao = _rodar(db, empresa, _nova_execucao(db, empresa))
    assert execucao.status == StatusExecucao.ERRO
    assert "Importação parcial" in execucao.mensagem_erro
    assert db.query(DocumentoFiscal).count() == 1
    assert execucao.documentos_importados == 1
    assert execucao.ultimo_nsu == "2"
    arquivo = lotes_recebidos.arquivos_pendentes(empresa.id, NFSE)[0]
    recebido = lotes_recebidos.ler(arquivo, empresa.id, NFSE)
    assert json.loads(recebido.conteudo) == payload
    assert recebido.nsu_anterior == "0"
    from app.api.routers.importacoes import estados_do_escritorio
    estado = next(item for item in estados_do_escritorio(db, escritorio_id=empresa.escritorio_id) if item.tipo == "nfse")
    assert estado.lotes_pendentes == 1
    assert estado.em_dia is False


def test_reprocessamento_local_recupera_item_sem_certificado_nem_http(cenario, monkeypatch):
    db, empresa, _ = cenario
    payload = _payload(1, 2)
    payload["LoteDFe"].append(_payload(2, 2, CHAVE2)["LoteDFe"][0])
    payload["UltNSU"] = 2
    chamadas = []
    monkeypatch.setattr(ImportadorNFSeADN, "_chamar_com_retentativa", lambda *args, **kwargs: (chamadas.append(1) or (200, payload)))
    original = ImportadorNFSeADN._converter_documento

    def parser_antigo(self, item, *args, **kwargs):
        if item["NSU"] == 2:
            raise ValueError("Leiaute antigo não reconheceu este documento")
        return original(self, item, *args, **kwargs)

    monkeypatch.setattr(ImportadorNFSeADN, "_converter_documento", parser_antigo)
    inicial = _rodar(db, empresa, _nova_execucao(db, empresa))
    assert inicial.status == StatusExecucao.ERRO
    assert db.query(DocumentoFiscal).count() == 1
    monkeypatch.setattr(ImportadorNFSeADN, "_converter_documento", original)
    db.query(Certificado).delete()
    db.commit()
    enfileirada = fila.enfileirar(db, empresa, NFSE)
    assert enfileirada.status == "enfileirada"
    assert db.get(ExecucaoImportacao, enfileirada.execucao_id).origem == "reprocessamento"
    recuperada = _rodar(db, empresa, enfileirada.execucao_id)
    assert recuperada.status == StatusExecucao.CONCLUIDA
    assert recuperada.documentos_importados == 1  # a já gravada não duplica
    assert db.query(DocumentoFiscal).count() == 2
    assert chamadas == [1]
    assert lotes_recebidos.quantidade_pendente(empresa.id, NFSE) == 0


def test_falha_de_disco_mantem_recebimento_para_retomada_sem_reconsulta(cenario, monkeypatch):
    db, empresa, _ = cenario
    chamadas = []
    monkeypatch.setattr(ImportadorNFSeADN, "_chamar_com_retentativa", lambda *args, **kwargs: (chamadas.append(1) or (200, _payload())))
    original = tasks._gravar_documento
    monkeypatch.setattr(tasks, "_gravar_documento", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("Disco indisponível")))
    primeira = _rodar(db, empresa, _nova_execucao(db, empresa))
    assert primeira.status == StatusExecucao.ERRO
    assert db.query(DocumentoFiscal).count() == 0
    assert sincronizacao.obter_estado(db, empresa.id, NFSE).ultimo_nsu == "0"
    assert lotes_recebidos.quantidade_pendente(empresa.id, NFSE) == 1
    monkeypatch.setattr(tasks, "_gravar_documento", original)
    retomada = fila.enfileirar(db, empresa, NFSE)
    execucao = _rodar(db, empresa, retomada.execucao_id)
    assert execucao.status == StatusExecucao.CONCLUIDA
    assert db.query(DocumentoFiscal).count() == 1
    assert execucao.ultimo_nsu == "1"
    assert chamadas == [1]


def test_cursor_global_prevalece_sobre_checkpoint_antigo(cenario):
    db, empresa, _ = cenario
    estado = sincronizacao.obter_estado(db, empresa.id, NFSE)
    estado.ultimo_nsu = "200"
    execucao = db.get(ExecucaoImportacao, _nova_execucao(db, empresa, ultimo_nsu="100"))
    assert tasks._resolver_nsu_inicial(db, empresa.id, NFSE, execucao, estado) == "200"
    # Nem um log antigo pode desfazer o rebobinamento explícito e auditado.
    estado.ultimo_nsu = "0"
    assert tasks._resolver_nsu_inicial(db, empresa.id, NFSE, execucao, estado) == "0"


def test_redelivery_com_lease_ocupado_nao_conclui_execucao_do_outro_worker(cenario, monkeypatch):
    db, empresa, disparos = cenario
    execucao_id = _nova_execucao(db, empresa)
    estado = sincronizacao.obter_estado(db, empresa.id, NFSE)
    assert sincronizacao.travar(db, estado)
    db.commit()
    monkeypatch.setattr(ImportadorNFSeADN, "_chamar_com_retentativa", lambda *args, **kwargs: pytest.fail("Não deve consultar"))
    execucao = _rodar(db, empresa, execucao_id)
    assert execucao.status == StatusExecucao.EM_ANDAMENTO
    assert execucao.finalizado_em is None
    assert disparos  # reforço para quando o lease for liberado


def test_lease_nao_expira_antes_do_hard_timeout():
    assert sincronizacao.LEASE_MAXIMO.total_seconds() > config.settings.limite_tempo_task_segundos + 60


def test_tick_nao_deixa_empresas_sem_a1_consumirem_o_teto(cenario, monkeypatch):
    db, primeira, disparos = cenario
    monkeypatch.setattr(config.settings, "sincronismo_lote_empresas", 1)
    certificado = db.query(Certificado).one()
    for i in range(2):
        db.add(Empresa(escritorio_id=primeira.escritorio_id, cnpj_cpf=f"23456789000{i:03d}", razao_social=f"Sem A1 {i}", uf="MG", quais_tipos_sincronizar="nfse"))
    ultima = Empresa(escritorio_id=primeira.escritorio_id, cnpj_cpf="34567890000191", razao_social="Com certificado", uf="MG", quais_tipos_sincronizar="nfse")
    db.add(ultima)
    db.flush()
    certificado.empresa_id = ultima.id
    db.commit()
    resumo = tasks.sincronizar_tudo()
    assert resumo["enfileiradas"] == 1
    assert resumo["ignoradas"] == 3
    assert db.query(ExecucaoImportacao).one().empresa_id == ultima.id
    assert disparos


def test_certificado_vencido_e_recusado_antes_de_gastar_consulta(cenario):
    db, empresa, disparos = cenario
    db.query(Certificado).one().validade = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    assert fila.enfileirar(db, empresa, NFSE).status == "sem_certificado"
    assert disparos == []


def test_worker_morto_e_retomado_sem_perder_checkpoint(cenario):
    db, empresa, disparos = cenario
    antigo = datetime.now(timezone.utc) - sincronizacao.LEASE_MAXIMO * 3
    estado = sincronizacao.obter_estado(db, empresa.id, NFSE)
    estado.travado_em = antigo
    estado.ultimo_nsu = "42"
    estado.max_nsu = "43"
    execucao_id = _nova_execucao(db, empresa, iniciado_em=antigo, ultimo_nsu="42")
    resumo = tasks.sincronizar_tudo()
    db.expire_all()
    assert resumo["retomadas"] == 1
    assert db.get(ExecucaoImportacao, execucao_id).ultimo_nsu == "42"
    assert disparos


def test_tipo_configurado_invalido_nao_aborta_escritorio(cenario):
    db, empresa, _ = cenario
    empresa.quais_tipos_sincronizar = "tipo-legado,nfse"
    db.commit()
    selecionadas = fila.disponiveis_para_sincronismo_automatico(db)
    assert selecionadas[0][1] == [NFSE]


def test_lote_sem_progresso_fica_visivel_e_nao_queima_consultas(cenario, monkeypatch):
    db, empresa, _ = cenario
    consultas = []
    class AmbienteTravado:
        def buscar_lote(self, **kwargs):
            consultas.append(kwargs["ultimo_nsu"])
            return LoteImportado([], "0", True, max_nsu="10", resposta_bruta=b"resposta sem progresso")
    monkeypatch.setattr(tasks, "obter_importador", lambda tipo: AmbienteTravado())
    execucao = _rodar(db, empresa, _nova_execucao(db, empresa))
    assert execucao.status == StatusExecucao.ERRO
    assert "sem avançar" in execucao.mensagem_erro
    assert consultas == ["0"]
    assert lotes_recebidos.quantidade_pendente(empresa.id, NFSE) == 1


def test_lote_nao_cruza_ambiente_fiscal(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))
    monkeypatch.setattr(config.settings, "ambiente_fiscal", "homologacao")
    arquivo = lotes_recebidos.salvar(1, NFSE, CNPJ, "0", b"resposta")
    monkeypatch.setattr(config.settings, "ambiente_fiscal", "producao")
    with pytest.raises(ValueError, match="outro ambiente"):
        lotes_recebidos.ler(arquivo, 1, NFSE)


def test_lote_ruim_antigo_nao_impede_captura_de_notas_novas(cenario, monkeypatch):
    db, empresa, _ = cenario
    payload = _payload(1, 2)
    ruim = _payload(2, 2, CHAVE2)["LoteDFe"][0]
    ruim["ArquivoXml"] = "payload-corrompido"
    payload["LoteDFe"].append(ruim)
    payload["UltNSU"] = 2
    monkeypatch.setattr(ImportadorNFSeADN, "_chamar_com_retentativa", lambda *args, **kwargs: (200, payload))
    assert _rodar(db, empresa, _nova_execucao(db, empresa)).status == StatusExecucao.ERRO
    arquivo = lotes_recebidos.arquivos_pendentes(empresa.id, NFSE)[0]
    registro = json.loads(arquivo.read_text())
    registro["recebido_em"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    arquivo.write_text(json.dumps(registro))
    estado = sincronizacao.obter_estado(db, empresa.id, NFSE)
    estado.proxima_consulta_em = None
    db.commit()
    chamada_nova = []
    monkeypatch.setattr(ImportadorNFSeADN, "_chamar_com_retentativa", lambda *args, **kwargs: (chamada_nova.append(1) or (200, _payload(3, 3, CHAVE1[:-1] + "9"))))
    nova = fila.enfileirar(db, empresa, NFSE)
    assert db.get(ExecucaoImportacao, nova.execucao_id).origem != "reprocessamento"
    resultado = _rodar(db, empresa, nova.execucao_id)
    assert resultado.documentos_importados == 1
    assert resultado.status == StatusExecucao.ERRO  # antigo continua pendente, não é descartado
    assert db.query(DocumentoFiscal).count() == 2  # mas a nova nota foi capturada
    assert chamada_nova == [1]
    assert lotes_recebidos.quantidade_pendente(empresa.id, NFSE) == 1


def test_conferencia_nao_libera_fechamento_com_lote_ilegivel(cenario):
    from app.api.routers.importacoes import _status_conferencia

    db, empresa, _ = cenario
    estado = sincronizacao.obter_estado(db, empresa.id, NFSE)
    estado.ultimo_nsu = estado.max_nsu = "42"
    estado.ultima_consulta_em = datetime.now(timezone.utc)
    db.commit()
    lotes_recebidos.salvar(empresa.id, NFSE, empresa.cnpj_cpf, "0", b"lote", escritorio_id=empresa.escritorio_id)
    resultado = _status_conferencia(db, empresa, NFSE, competencia_fechada=True,
        precisa_ter_consulta_apos=datetime(2026, 1, 1, tzinfo=timezone.utc), agora=datetime.now(timezone.utc))
    assert resultado[0] == "erro"
    assert "falha de leitura" in resultado[1]


def test_checkpoint_fica_dentro_do_volume_persistente_de_xml(cenario):
    db, empresa, _ = cenario
    arquivo = lotes_recebidos.salvar(empresa.id, NFSE, empresa.cnpj_cpf, "0", b"conteudo", escritorio_id=empresa.escritorio_id)
    from pathlib import Path
    assert arquivo.is_relative_to(Path(config.settings.dados_dir) / "xml")
    # Containers de produção compartilham /data/xml e têm /data somente-leitura.
    assert arquivo.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="escritório"):
        lotes_recebidos.ler(arquivo, empresa.id, NFSE, escritorio_id=empresa.escritorio_id + 1)


def test_reprocessamento_automatico_ilegivel_tem_backoff_sem_consulta(cenario):
    db, empresa, disparos = cenario
    lote = lotes_recebidos.salvar(empresa.id, NFSE, empresa.cnpj_cpf, "0", b"ilegivel", escritorio_id=empresa.escritorio_id)
    db.query(Certificado).delete()
    anterior = ExecucaoImportacao(empresa_id=empresa.id, tipo=NFSE, origem="reprocessamento", status=StatusExecucao.ERRO,
        finalizado_em=datetime.now(timezone.utc))
    db.add(anterior)
    db.commit()
    resposta = fila.enfileirar(db, empresa, NFSE, origem="auto")
    assert resposta.status == "em_cooldown"
    assert "local" in resposta.mensagem
    assert disparos == []
    assert lote.exists()


def test_xml_bem_formado_mas_sem_nota_nao_gera_documento_fiscal_falso():
    payload = _payload()
    payload["LoteDFe"][0]["ArquivoXml"] = "<retorno><mensagem>XML indisponível</mensagem></retorno>"
    lote = ImportadorNFSeADN()._interpretar(payload, CNPJ, "0")
    assert lote.documentos == []
    assert lote.erros
    assert "data de emissão" in lote.erros[0]


def test_limpeza_do_escritorio_remove_apenas_lotes_do_proprio_tenant(cenario, monkeypatch):
    from app.api.routers.sistema import reset_geral
    from app.models import Escritorio, Usuario

    db, empresa, _ = cenario
    outro = Escritorio(nome="Outro escritório")
    db.add(outro)
    db.flush()
    outra_empresa = Empresa(escritorio_id=outro.id, cnpj_cpf=empresa.cnpj_cpf, razao_social="Outra empresa", uf="MG")
    db.add(outra_empresa)
    db.commit()
    local = lotes_recebidos.salvar(empresa.id, NFSE, empresa.cnpj_cpf, "0", b"local", escritorio_id=empresa.escritorio_id)
    protegido = lotes_recebidos.salvar(outra_empresa.id, NFSE, outra_empresa.cnpj_cpf, "0", b"outro", escritorio_id=outro.id)
    usuario = Usuario(escritorio_id=empresa.escritorio_id, nome="Administrador", email="admin@teste.local", senha_hash="teste", papel="admin", ativo=True)
    db.add(usuario)
    db.commit()
    resposta = reset_geral(confirmar="APAGAR TUDO", db=db, usuario=usuario)
    assert resposta.empresas == 1
    assert not local.exists()
    assert protegido.exists()
