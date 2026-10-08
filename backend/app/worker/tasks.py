"""
Tasks de importação.

Todo o desenho desta fila gira em torno de uma coisa: o Ambiente Nacional
(SEFAZ) e o ADN (NFS-e) limitam *quem consulta o CNPJ*, não *quantas notas
você baixa*. Ignorar isso trava o CNPJ por 1 hora e é exatamente o erro que
derruba importadores comerciais. Aqui, portanto:

- um **lease** por empresa+tipo: nunca duas varreduras no mesmo CNPJ ao mesmo
  tempo (dois cursores avançando = consulta fora da sequência = cStat 656);
- o **cursor mora em `sincronizacoes_dfe`**, uma linha por empresa+tipo, e só
  anda para frente;
- **137/"nada novo"** ⇒ agenda a próxima consulta para depois da janela
  oficial (1h + margem);
- **656** ⇒ não é "erro": a execução vira `aguardando`, o bloqueio é
  registrado e a continuação é reagendada sozinha — com o `ultNSU` que o
  ambiente devolveu adotado, para voltar alinhado;
- **queda de ambiente (5xx/rede)** ⇒ retenta cedo, porque aí nenhuma cota foi
  gasta;
- intervalo de **2s entre páginas** e teto de páginas por varredura, como
  recomenda o sped-nfe;
- checkpoint a cada lote: o que já baixou está no banco, mesmo se o worker
  cair no meio da hora de bloqueio.

**Período (desde a v3.2).** A varredura na origem é por NSU — a SEFAZ/ADN não
aceita "me dê só agosto" —, e **tudo o que a distribuição entrega é gravado**.
O intervalo que o operador pediu continua registrado na execução e continua
contando quanto veio de dentro e de fora dele
(`documentos_no_periodo` / `documentos_fora_do_periodo`), mas agora como
*relatório*, não como filtro de gravação.

Por que mudou: até a v3.1 a nota fora do intervalo era descartada **e o cursor
de NSU avançava assim mesmo**. Como o cursor nunca regride, aquele documento
ficava inalcançável para sempre — a SEFAZ considera o NSU consumido e não o
reapresenta. Numa empresa recém-cadastrada, em que o acervo disponível é
inteiro anterior ao período pedido, o resultado prático era: a captura
respondia 200, o cursor ia de 0 ao máximo e o acervo terminava vazio, sem nada
na tela explicando o porquê.

Entre "guardar um mês que ninguém pediu" e "perder nota fiscal de forma
irreversível", guardar é o erro barato: disco é recuperável, NSU consumido não
é. O recorte por período continua existindo onde ele é reversível — nos filtros
de exibição das telas.
"""

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

from cryptography.hazmat.primitives.serialization import pkcs12
from dateutil import parser as date_parser
from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.plural import contagem, plural
from app.core.arquivos import gravar_bytes_atomicamente
from app.core.config import settings
from app.core.money import valor_monetario
from app.core.tempo import tornar_data_hora_fiscal_consciente
from app.core.vault import decifrar_segredo
from app.db.session import SessionLocal
from app.models import (
    Certificado,
    DirecaoDocumento,
    DocumentoFiscal,
    Empresa,
    EventoFiscalPendente,
    ExecucaoImportacao,
    StatusDocumentoFiscal,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.services import batimento, fila, lotes_recebidos, sincronizacao, xml_integridade
from app.services.proveniencia import registrar_proveniencia
from app.services.importadores._distribuicao_dfe import (
    classificar_documento_dfe,
    eh_documento_integral,
)
from app.services.importadores.manifestacao import (
    CSTAT_EVENTO_FORA_DO_PRAZO,
    EVENTOS_CONCLUSIVOS,
    PRAZO_CIENCIA_DIAS,
    TIPO_EVENTO_DESCONHECIMENTO,
    ManifestacaoRecusada,
    manifestar_ciencia,
    manifestar_conclusiva,
)
from app.services.certificados import ler_pfx_protegido
from app.services.importadores.base import (
    AmbienteIndisponivel,
    ConsumoIndevido,
    DocumentoBaixado,
)
from app.services.importadores.eventos import EventoFiscal
from app.services.importadores import obter_importador
from app.services.mtls import sessao_mtls
from app.worker.celery_app import celery_app

log = logging.getLogger("notasflow.worker")

# Trava de segurança: no máximo N lotes (de até 50 documentos) por varredura.
# Vem do sped-nfe: "o LOOP deve ter um limite de iterações, por exemplo 50".
TAMANHO_MAXIMO_LOTE_POR_EXECUCAO = max(1, int(settings.max_lotes_por_execucao))

# Intervalo entre páginas. Recomendado explicitamente: "o tempo entre cada busca
# no LOOP deve ser de pelo menos 2 segundos".
ESPERA_ENTRE_LOTES = max(0.0, float(settings.espera_entre_lotes_segundos))


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _parse_data_emissao(valor: str | datetime | None) -> datetime:
    """
    Converte a data de emissão (string ISO do XML fiscal, datetime, ou vazio)
    para datetime timezone-aware. Fallback: agora em UTC — nunca deixa a
    gravação quebrar por um campo opcional malformado.
    """
    if isinstance(valor, datetime):
        return tornar_data_hora_fiscal_consciente(valor)
    if not valor or not str(valor).strip():
        return datetime.now(timezone.utc)
    try:
        dt = date_parser.isoparse(str(valor).strip())
        return tornar_data_hora_fiscal_consciente(dt)
    except (ValueError, TypeError, OverflowError):
        try:
            dt = date_parser.parse(str(valor).strip())
            return tornar_data_hora_fiscal_consciente(dt)
        except (ValueError, TypeError, OverflowError):
            return datetime.now(timezone.utc)


def _parse_data(valor: str | None) -> date | None:
    """Competência do XML para `date`. Nada de fuso: o que importa é o mês."""
    if not valor or not str(valor).strip():
        return None
    try:
        return date_parser.parse(str(valor).strip()).date()
    except (ValueError, TypeError, OverflowError):
        return None


@celery_app.task(name="importar_documentos", bind=True, max_retries=0)
def importar_documentos(
    self, empresa_id: int, tipo: str, execucao_id: int, tentativa: int = 0
) -> None:
    """
    Varredura completa de uma empresa+tipo, do último NSU conhecido até o
    maxNSU do ambiente, com checkpoint a cada lote.

    `tentativa` conta apenas retentativas de *queda de ambiente* (5xx/rede).
    Bloqueio por consumo indevido não usa contador: a regra oficial é esperar,
    então cada hora é uma tentativa nova e o processo continua sozinho até
    conseguir.
    """
    db = SessionLocal()
    estado = None
    travado = False
    tipo_doc = TipoDocumentoFiscal(tipo)

    try:
        execucao = db.get(ExecucaoImportacao, execucao_id)
        empresa = db.get(Empresa, empresa_id)
        if execucao is None or empresa is None:
            return
        if execucao.status == StatusExecucao.CONCLUIDA:
            # Redelivery do broker (acks_late) numa varredura que já terminou:
            # sair daqui é o que evita reconsultar a SEFAZ de graça.
            return
        if execucao.empresa_id != empresa_id or execucao.tipo != tipo_doc:
            raise ValueError("Execução não corresponde à empresa/tipo da tarefa.")
        if not empresa.ativa:
            _marcar_erro(db, execucao, "Empresa inativa: captura não realizada.", falha="cadastro")
            return

        estado = sincronizacao.obter_estado(db, empresa_id, tipo_doc)
        if estado is None:
            _marcar_erro(db, execucao, "Estado de sincronização indisponível (banco?)", falha="sistema")
            return
        travado = sincronizacao.travar(db, estado)
        db.commit()
        if not travado:
            log.info(
                "Empresa %s/%s já está sendo varrida por outra task; sem duplicar consulta.",
                empresa_id, tipo,
            )
            # Redelivery pode ser da MESMA execução que está rodando. Não
            # altere seu status nem finja sucesso sem ter consultado nada.
            try:
                importar_documentos.apply_async(
                    kwargs={"empresa_id": empresa_id, "tipo": tipo, "execucao_id": execucao_id, "tentativa": tentativa},
                    countdown=60,
                )
            except Exception:
                log.warning("Retomada do lease ocupado dependerá do agendador.")
            return

        execucao.status = StatusExecucao.EM_ANDAMENTO
        execucao.bloqueado_ate = None
        execucao.mensagem_erro = None
        execucao.finalizado_em = None
        db.commit()

        # Batimento: a API usa isto (e o ping do broker) para dizer ao
        # operador se "tem alguém trabalhando" na primeira tela.
        batimento.registrar(db, "worker", f"importar_documentos {empresa_id}/{tipo}")

        ultimo_nsu = _resolver_nsu_inicial(db, empresa_id, tipo_doc, execucao, estado)
        importador = obter_importador(tipo_doc)
        total_importado = execucao.documentos_importados or 0
        total_cancelados = execucao.documentos_cancelados or 0
        total_nao_reconhecidos = execucao.eventos_nao_reconhecidos or 0
        total_no_periodo = execucao.documentos_no_periodo or 0
        total_fora_do_periodo = execucao.documentos_fora_do_periodo or 0
        total_completados = 0
        periodo = fila_periodo(execucao)
        importou_alguma_coisa = False

        def gravar_lote(lote, arquivo, *, consulta_local: bool = False, recebido_em: datetime | None = None):
            nonlocal total_importado, total_cancelados, total_nao_reconhecidos
            nonlocal total_no_periodo, total_fora_do_periodo, total_completados, importou_alguma_coisa
            for doc in lote.documentos:
                # XML completo de uma nota que estava só em resumo: promove
                # sem olhar o período (a nota já é nossa). Uma promoção é
                # trabalho útil; marcá-la impede um cooldown indevido quando
                # ainda existem NSUs pendentes no ambiente.
                if _promover_resumo(db, empresa_id, tipo_doc, doc):
                    total_completados += 1
                    importou_alguma_coisa = True
                    continue

                # Grava SEMPRE. O período virou relatório, não filtro de
                # gravação: o NSU deste documento está sendo consumido agora
                # e o cursor nunca regride sozinho. Descartar aqui perderia
                # a nota em definitivo, pois a SEFAZ não reapresenta NSU já
                # entregue. Ainda contamos de que lado do intervalo ela caiu
                # para a execução explicar o resultado ao operador.
                dentro_do_periodo = _documento_no_periodo(doc, periodo)
                if _gravar_documento(db, empresa_id, tipo_doc, doc):
                    total_importado += 1
                    if dentro_do_periodo:
                        total_no_periodo += 1
                    else:
                        total_fora_do_periodo += 1
                    importou_alguma_coisa = True
                    if _aplicar_eventos_pendentes(db, empresa_id, tipo_doc, doc.chave_acesso):
                        total_cancelados += 1

            for evento in lote.eventos:
                resultado = _processar_evento(db, empresa_id, tipo_doc, evento)
                if resultado == "aplicado":
                    total_cancelados += 1

            total_nao_reconhecidos += lote.eventos_nao_reconhecidos
            if lote.erros and arquivo is None:
                raise ValueError("Lote com falha de leitura sem resposta preservada: cursor não avançado.")
            max_nsu = lote.max_nsu
            if consulta_local and estado.max_nsu is not None and max_nsu is not None:
                max_nsu = str(max(int(estado.max_nsu), int(max_nsu)))
            consulta_anterior = estado.ultima_consulta_em
            sincronizacao.avançar_cursor(db, estado, ultimo_nsu=lote.proximo_nsu, max_nsu=max_nsu)
            if consulta_local:
                estado.ultima_consulta_em = consulta_anterior or recebido_em
            sincronizacao.renovar_lease(db, estado)
            execucao.ultimo_nsu = estado.ultimo_nsu
            execucao.documentos_importados = total_importado
            execucao.documentos_cancelados = total_cancelados
            execucao.eventos_nao_reconhecidos = total_nao_reconhecidos
            execucao.documentos_no_periodo = total_no_periodo
            execucao.documentos_fora_do_periodo = total_fora_do_periodo
            if lote.erros:
                execucao.aviso = _resumir_avisos(execucao.aviso, lote.erros)
            db.commit()
            if not lote.erros:
                lotes_recebidos.confirmar(arquivo)

        # Leia o checkpoint local ANTES de exigir certificado ou consultar
        # outra vez. Uma falha de parser/DB/disco não pode consumir o NSU e
        # descartar a resposta que já havia sido recebida.
        espera_local_ate = None
        for arquivo in lotes_recebidos.arquivos_pendentes(empresa_id, tipo_doc)[:50]:
            try:
                recebido = lotes_recebidos.ler(arquivo, empresa_id, tipo_doc, escritorio_id=empresa.escritorio_id)
                if recebido.cnpj != empresa.cnpj_cpf:
                    raise ValueError("Lote recebido pertence a outro documento cadastral.")
                lote_local = importador.interpretar_lote(recebido.conteudo, recebido.cnpj, recebido.nsu_anterior)
            except Exception as exc:
                execucao.aviso = _resumir_avisos(execucao.aviso, [f"Lote local preservado não pôde ser lido: {str(exc)[:200]}"])
                db.commit()
                continue
            gravar_lote(lote_local, arquivo, consulta_local=True, recebido_em=recebido.recebido_em)
            if (lote_local.sem_novidade or (lote_local.max_nsu is not None and int(lote_local.proximo_nsu) >= int(lote_local.max_nsu))) and sincronizacao.esta_em_dia(estado):
                quando = recebido.recebido_em + sincronizacao.cooldown_oficial()
                proxima = estado.proxima_consulta_em
                proxima = proxima.replace(tzinfo=timezone.utc) if proxima and proxima.tzinfo is None else proxima
                if proxima is None or proxima < quando:
                    estado.proxima_consulta_em = quando
                if espera_local_ate is None or espera_local_ate < quando:
                    espera_local_ate = quando
                db.commit()
        ultimo_nsu = estado.ultimo_nsu

        local_completo_recente = espera_local_ate and espera_local_ate > _agora() and lotes_recebidos.quantidade_pendente(empresa_id, tipo_doc) == 0
        if execucao.origem == "reprocessamento" or local_completo_recente:
            pendentes = lotes_recebidos.quantidade_pendente(empresa_id, tipo_doc)
            if pendentes:
                _marcar_erro(db, execucao, f"Importação parcial: {pendentes} lote(s) recebido(s) ainda exigem correção. Respostas preservadas no volume; nenhuma consulta fiscal foi repetida.", falha="importacao_parcial")
            else:
                execucao.status = StatusExecucao.CONCLUIDA
                execucao.aviso = _resumir_avisos(execucao.aviso, ["Lotes recebidos reprocessados localmente, sem nova consulta à SEFAZ/ADN."])
                execucao.finalizado_em = _agora()
                db.commit()
            return

        # ---------------- janela de consumo ----------------
        if not getattr(execucao, "forcar", False):
            libertacao = sincronizacao.liberacao_para(db, empresa_id, tipo_doc)
            if not libertacao.pode:
                _aguardar_janela(db, estado, execucao, libertacao)
                return
        status_preflight, mensagem_preflight = fila.verificar_empresa(db, empresa, tipo_doc)
        if status_preflight != "ok":
            _marcar_erro(db, execucao, mensagem_preflight, falha="cadastro")
            return
        certificado = (
            db.query(Certificado)
            .filter(Certificado.empresa_id == empresa_id, Certificado.ativo.is_(True))
            .first()
        )
        senha = decifrar_segredo(certificado.senha_cifrada)
        pfx_bytes = ler_pfx_protegido(certificado.arquivo_path)

        # Telemetria do A1: o centro de certificados mostra "última utilização"
        # e "último erro de autenticação". Abrir o .pfx com a senha É a
        # autenticação local (senha errada/certificado corrompido falham aqui,
        # antes de gastar qualquer chamada ao ambiente fiscal).
        try:
            pkcs12.load_key_and_certificates(pfx_bytes, senha.encode())
        except Exception as exc:  # noqa: BLE001
            certificado.ultimo_erro = f"Abertura do .pfx falhou: {str(exc)[:300]}"
            certificado.ultima_utilizacao_em = _agora()
            db.commit()
            raise
        certificado.ultima_utilizacao_em = _agora()
        certificado.ultimo_erro = None
        db.commit()

        with sessao_mtls(pfx_bytes, senha) as (cert_path, key_path):
            for pagina in range(TAMANHO_MAXIMO_LOTE_POR_EXECUCAO):
                if pagina:
                    time.sleep(ESPERA_ENTRE_LOTES)
                try:
                    lote = importador.buscar_lote(
                        cnpj=empresa.cnpj_cpf,
                        cert_path=cert_path,
                        key_path=key_path,
                        ultimo_nsu=ultimo_nsu,
                        uf=empresa.uf,
                    )
                except ConsumoIndevido as exc:
                    tratar_consumo_indevido(db, estado, execucao, exc)
                    return
                except AmbienteIndisponivel as exc:
                    tratar_ambiente_indisponivel(db, execucao, exc, tentativa)
                    return

                arquivo_recebido = lotes_recebidos.salvar(
                    empresa_id, tipo_doc, empresa.cnpj_cpf, ultimo_nsu, lote.resposta_bruta, escritorio_id=empresa.escritorio_id
                )
                if lote.ha_mais_documentos and int(lote.proximo_nsu) <= int(ultimo_nsu):
                    raise ValueError("Ambiente informou mais documentos sem avançar o NSU. Lote preservado; captura interrompida para evitar consultas repetidas.")
                gravar_lote(lote, arquivo_recebido)
                ultimo_nsu = estado.ultimo_nsu

                if not lote.ha_mais_documentos:
                    break
            else:
                # Estourou o teto de páginas: continua do checkpoint na mesma
                # execução (não finge "concluída" com trabalho pela metade).
                fila_reagendar(db, execucao, _agora(), motivo="Continuação da varredura (teto de páginas).")
                return

        # ---------------- fim da varredura ----------------
        if lote.sem_novidade:
            sincronizacao.marcar_sem_novidade(db, estado)
        elif sincronizacao.nunca_consultado(estado):
            # Nunca obtivemos `maxNSU` para esta empresa+tipo: não sabemos se
            # estamos em dia, logo NÃO cabe a espera de 1h. Era exatamente aqui
            # que a NF-e se enterrava: sem importar nada, caía no ramo de "em
            # dia", ganhava 1h de cooldown e nunca mais era consultada de fato.
            sincronizacao.marcar_consulta_ok(db, estado)
            execucao.aviso = _resumir_avisos(
                execucao.aviso,
                ["O ambiente ainda não informou o NSU máximo desta empresa/tipo. "
                 "Nada foi bloqueado: a próxima varredura tentará de novo."],
            )
        elif sincronizacao.esta_em_dia(estado) or not importou_alguma_coisa:
            # "ultNSU == maxNSU" é a definição oficial de "não há mais nada
            # agora" — e é o gatilho da espera de 1 hora.
            quando = sincronizacao.marcar_sem_novidade(db, estado)
            execucao.aviso = _resumir_avisos(
                execucao.aviso,
                [f"Em dia até o NSU {estado.ultimo_nsu}. Próxima consulta a partir de "
                 f"{quando:%d/%m/%Y %H:%M} (janela oficial de 1h do ambiente)."],
            )
        else:
            sincronizacao.marcar_consulta_ok(db, estado)

        if not lote.sem_novidade and (estado.max_nsu and int(estado.ultimo_nsu or 0) < int(estado.max_nsu or 0)):
            sincronizacao.marcar_consulta_ok(db, estado)

        if total_completados:
            execucao.aviso = _resumir_avisos(
                execucao.aviso,
                [
                    f"{contagem(total_completados, 'nota', 'notas')} que estavam só em resumo "
                    "foram completadas com o XML integral."
                ],
            )

        if total_fora_do_periodo:
            # Prova do recorte: sem esta linha o operador veria "500 documentos
            # distribuídos, 12 no período" e não saberia onde foi parar o resto.
            # Eles FORAM guardados — só não aparecem no filtro de tela atual.
            execucao.aviso = _resumir_avisos(
                execucao.aviso,
                [
                    f"{contagem(total_fora_do_periodo, 'documento', 'documentos')} "
                    f"{plural(total_fora_do_periodo, 'veio', 'vieram')} fora do período "
                    f"{periodo.rotulo()} e foram guardados assim mesmo (a SEFAZ não "
                    "reapresenta NSU já consumido). Para vê-los, ajuste o período "
                    "na tela de documentos."
                ],
            )

        pendentes = lotes_recebidos.quantidade_pendente(empresa_id, tipo_doc)
        if pendentes:
            _marcar_erro(db, execucao, f"Importação parcial: {pendentes} lote(s) com falha de leitura preservado(s) para reprocessamento. Notas válidas foram gravadas; a execução não é confirmação de acervo completo.", falha="importacao_parcial")
            return
        execucao.status = StatusExecucao.CONCLUIDA
        execucao.bloqueado_ate = None
        execucao.finalizado_em = _agora()
        db.commit()

        if tipo_doc == TipoDocumentoFiscal.NFE and _pendentes_de_completar(db, empresa, 1):
            try:
                completar_xmls_pendentes.delay(empresa_id=empresa_id)
            except Exception:  # noqa: BLE001
                pass

    except Exception as exc:  # noqa: BLE001 — task de background: captura, registra, não derruba o worker
        log.exception("Importação %s/%s falhou", empresa_id, tipo)
        db.rollback()
        execucao = db.get(ExecucaoImportacao, execucao_id)
        _marcar_erro(db, execucao, str(exc))
    finally:
        if estado is not None and travado:
            try:
                sincronizacao.liberar(db, estado)
                db.commit()
            except Exception:  # noqa: BLE001 — liberar nunca pode esconder o erro real
                db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# Tratamento dos dois "erros" que não são erro
# ---------------------------------------------------------------------------


def tratar_consumo_indevido(
    db, estado, execucao: ExecucaoImportacao, erro: ConsumoIndevido
) -> None:
    """
    cStat 656: o CNPJ está bloqueado e a regra oficial manda esperar a hora
    inteira — retentar antes zera o cronômetro do bloqueio.

    Duas coisas acontecem além de esperar:

    1. o `ultNSU`/`maxNSU` que veio *junto* na resposta é adotado. É o que
       destrava o caso "outro sistema consultou este CNPJ e o meu cursor ficou
       para trás", que é o motivo mais comum de gente presa em loop de 656;
    2. o que já tinha baixado fica commitado (checkpoint por lote), então a
       retomada continua exatamente de onde parou.
    """
    quando = sincronizacao.marcar_consumo_indevido(
        db,
        estado,
        motivo=f"cStat {erro.cstat}: {erro.motivo}",
        # Quando o ambiente informou o tempo exato (Retry-After do ADN), a
        # exceção já traz `bloqueio`; senão fica None e cai no cooldown de 1h.
        bloqueio=getattr(erro, "bloqueio", None),
    )
    if erro.ultimo_nsu:
        sincronizacao.realinhar_cursor(
            db, estado, ultimo_nsu=erro.ultimo_nsu, max_nsu=erro.max_nsu
        )
    db.commit()

    execucao.ultimo_nsu = estado.ultimo_nsu
    mensagem = (
        f"{erro.ambiente} bloqueou este CNPJ por consumo indevido (cStat {erro.cstat}): "
        f"{erro.motivo} "
        f"Nova tentativa automática em {quando:%d/%m/%Y às %H:%M}. "
        "Nada foi perdido: o que já baixou está gravado e a retomada continua do checkpoint."
    )
    if erro.motivo and "ultNSU" in erro.motivo:
        mensagem += " O cursor foi realinhado com o NSU informado pelo próprio ambiente."
    _marcar_aguardando(db, execucao, mensagem, quando)
    fila_reagendar(db, execucao, quando, motivo=mensagem)


def tratar_ambiente_indisponivel(
    db, execucao: ExecucaoImportacao, erro: AmbienteIndisponivel, tentativa: int
) -> None:
    """
    5xx/rede: nenhuma cota foi gasta, então a espera é curta e crescente.
    Depois do teto, vira erro visível — mas o agendador continua tentando
    sozinho nas próximas varreduras.
    """
    limite = max(1, int(settings.max_tentativas_transporte))
    if tentativa >= limite:
        _marcar_erro(
            db,
            execucao,
            f"Ambiente fiscal indisponível após {tentativa + 1} tentativas: {erro}",
            falha="ambiente_fiscal",
        )
        return
    quando = _agora() + erro.tentativa_recomendada * (2**tentativa)
    _marcar_aguardando(
        db,
        execucao,
        f"SEFAZ/ADN indisponível. Tentativa {tentativa + 1} de {limite + 1}; "
        f"próxima em {quando:%H:%M}. ({str(erro)[:300]})",
        quando,
    )
    fila_reagendar(
        db,
        execucao,
        quando,
        motivo="Ambiente fiscal indisponível — retentando.",
        tentativa=tentativa + 1,
    )


def _aguardar_janela(db, estado, execucao: ExecucaoImportacao, libertacao) -> None:
    """Disparamos uma varredura dentro da janela de espera: reagenda e sai."""
    _marcar_aguardando(
        db,
        execucao,
        (
            f"Janela de consumo do ambiente aberta em {libertacao.quando:%d/%m/%Y às %H:%M}. "
            + (f"{libertacao.motivo} " if libertacao.motivo else "")
            + "Nova tentativa automática já está agendada."
        ),
        libertacao.quando,
    )
    fila_reagendar(db, execucao, libertacao.quando, motivo="Aguardando janela de consumo.")


def _marcar_aguardando(
    db, execucao: ExecucaoImportacao, mensagem: str, quando: datetime
) -> None:
    execucao.status = StatusExecucao.AGUARDANDO
    execucao.bloqueado_ate = quando
    execucao.tentativas = (execucao.tentativas or 0) + 1
    execucao.mensagem_erro = mensagem[:4000]
    execucao.finalizado_em = None
    db.commit()


def fila_reagendar(
    db, execucao: ExecucaoImportacao, quando: datetime, *, motivo: str, tentativa: int | None = None
) -> bool:
    """Delegado para `app.services.fila.reagendar` (mesmo caminho do Beat)."""
    return fila.reagendar(db, execucao, quando, motivo=motivo, tentativa=tentativa)


def fila_periodo(execucao: ExecucaoImportacao):
    from app.services.periodo import Periodo

    return Periodo(inicio=execucao.data_inicio, fim=execucao.data_fim)


def _documento_no_periodo(doc, periodo) -> bool:
    """
    A nota recém-baixada pertence ao período pedido?

    Critério: **competência** com fallback para data de emissão — a mesma
    regra fiscal que as consultas ao banco usam (`app/services/referencia.py`),
    para o que foi importado no mês ser exatamente o que aparece quando se filtra
    pela competência.
    """
    if periodo is None or not periodo.definido:
        return True
    quando = _parse_data(str(getattr(doc, "competencia", "") or ""))
    if quando is None:
        quando = _parse_data(str(getattr(doc, "data_emissao", "") or ""))
    if quando is None:
        return True
    return periodo.contem(quando)


def _resolver_nsu_inicial(
    db, empresa_id: int, tipo: TipoDocumentoFiscal, execucao: ExecucaoImportacao, estado=None
) -> str:
    """
    Ponto de retomada: o cursor vive em `sincronizacoes_dfe`. Para bancos que
    ainda não têm estado (recém-migrado), cai no maior NSU do histórico — e só
    então em "0", que é o único valor que não briga com a sequência do ambiente.
    """
    if estado is None:
        estado = sincronizacao.obter_estado(db, empresa_id, tipo, criar=False)
    if estado is not None and estado.ultimo_nsu:
        return estado.ultimo_nsu

    if execucao.ultimo_nsu:
        return execucao.ultimo_nsu

    historico = (
        db.query(ExecucaoImportacao.ultimo_nsu)
        .filter(
            ExecucaoImportacao.empresa_id == empresa_id,
            ExecucaoImportacao.tipo == tipo,
            ExecucaoImportacao.id != execucao.id,
            ExecucaoImportacao.ultimo_nsu.isnot(None),
        )
        .all()
    )
    # Máximo **numérico** (ordenar como string colocaria "900" acima de "1000"
    # e mandaria a consulta para trás na sequência — o que a SEFAZ pune).
    maiores = [int("".join(c for c in nsu if c.isdigit()) or 0) for (nsu,) in historico]
    return str(max(maiores)) if maiores else "0"


def _normalizar_chave(chave: str | None) -> str:
    """A coluna tem 60 chars; chaves iguais após o corte colidem no unique."""
    if not chave:
        return ""
    return str(chave).strip()[:60]


def _inserir_documento_sem_duplicar(db, valores: dict) -> bool:
    """
    Insere um documento de forma atômica e retorna se uma linha foi criada.

    Consultar antes de inserir não é suficiente: dois workers podem consultar
    ao mesmo tempo, ambos concluírem que a chave não existe e um deles receber
    `psycopg2.errors.UniqueViolation`. O `ON CONFLICT DO NOTHING` deixa o
    próprio PostgreSQL arbitrar essa corrida sem abortar a importação.

    SQLite usa a mesma sintaxe para manter os testes locais fiéis ao banco de
    produção. A aplicação é suportada em PostgreSQL; outro dialeto recebe um
    erro explícito, em vez de voltar ao padrão inseguro de consulta + insert.
    """
    dialeto = db.get_bind().dialect.name
    tabela = DocumentoFiscal.__table__

    if dialeto == "postgresql":
        comando = postgresql_insert(tabela).values(**valores).on_conflict_do_nothing(
            constraint="uq_documento_por_empresa"
        )
    elif dialeto == "sqlite":
        comando = sqlite_insert(tabela).values(**valores).on_conflict_do_nothing(
            index_elements=("empresa_id", "chave_acesso")
        )
    else:
        raise RuntimeError(
            f"Banco não suportado para importação idempotente: {dialeto}. Use PostgreSQL."
        )

    resultado = db.execute(comando)
    return resultado.rowcount == 1


def _promover_resumo(db, empresa_id: int, tipo: TipoDocumentoFiscal, doc) -> bool:
    """
    Troca um `resumo` já gravado pelo XML completo que a distribuição entregou.

    Depois da Ciência da Operação o Ambiente Nacional envia o `procNFe` pelo
    próprio fluxo de NSU (sem gastar a cota do consChNFe). Como a chave já
    existe, o insert idempotente de `_gravar_documento` ignoraria o completo e o
    documento ficaria como resumo para sempre — por isso esta promoção roda
    ANTES do filtro de período e do insert.

    Retorna True quando um resumo foi completado.
    """
    if (getattr(doc, "leiaute", "") or "completo") != "completo":
        return False
    chave = _normalizar_chave(getattr(doc, "chave_acesso", None))
    if not chave:
        return False
    existente = (
        db.query(DocumentoFiscal)
        .filter(
            DocumentoFiscal.empresa_id == empresa_id,
            DocumentoFiscal.tipo == tipo,
            DocumentoFiscal.chave_acesso == chave,
            DocumentoFiscal.leiaute == "resumo",
        )
        .first()
    )
    if existente is None:
        return False
    if not _sobrescrever_xml(existente, doc):
        # O docZip veio rotulado como completo, mas não é a nota: a promoção não
        # acontece e a nota continua na fila (é o `consChNFe` devolvendo resumo).
        return False
    # O arquivo em disco agora é o docZip deste NSU; manter o NSU do resumo
    # quebraria a reconciliação "qual NSU gerou este XML" numa auditoria.
    if getattr(doc, "nsu", None):
        existente.nsu = str(doc.nsu)
    registrar_proveniencia(db, existente.id, "sefaz", str(doc.nsu))
    return True


def _gravar_documento(db, empresa_id: int, tipo: TipoDocumentoFiscal, doc, *, origem: str | None = None, identificador_externo: str | None = None, nsu_registro: str | None = None) -> bool:
    """
    Persiste um documento de forma idempotente.

    A mesma nota pode voltar em uma consulta posterior ou chegar a workers em
    paralelo. A restrição `uq_documento_por_empresa` continua sendo a regra
    final, mas o insert atômico absorve o conflito e a task segue normalmente.
    Retorna True somente quando uma nota nova foi gravada.
    """
    chave = _normalizar_chave(getattr(doc, "chave_acesso", None))
    if not chave:
        return False

    pasta = os.path.join(settings.dados_dir, "xml", str(empresa_id), tipo.value)
    nome_seguro = "".join(c for c in chave if c.isalnum() or c in "-_") or f"nsu_{doc.nsu}"
    xml_path = os.path.join(pasta, f"{nome_seguro}.xml")
    direcao = doc.direcao if doc.direcao in ("tomada", "prestada") else "tomada"

    def texto(field: str, limite: int) -> str | None:
        valor = str(getattr(doc, field, "") or "").strip()
        return valor[:limite] or None

    data_emissao_parsed = _parse_data_emissao(doc.data_emissao)
    competencia_parsed = _parse_data(getattr(doc, "competencia", ""))
    if competencia_parsed is None and data_emissao_parsed is not None:
        competencia_parsed = data_emissao_parsed.date()

    valores = {
        "empresa_id": empresa_id,
        "tipo": tipo,
        "direcao": DirecaoDocumento(direcao),
        "chave_acesso": chave,
        "nsu": nsu_registro if nsu_registro is not None else str(doc.nsu),
        "data_emissao": data_emissao_parsed,
        "competencia": competencia_parsed,
        "valor_total": valor_monetario(doc.valor_total),
        "xml_path": xml_path,
        "status": StatusDocumentoFiscal.NORMAL,
        "leiaute": getattr(doc, "leiaute", "completo") or "completo",
        "numero": texto("numero", 20),
        "serie": texto("serie", 10),
        "emitente_documento": texto("emitente_documento", 18),
        "emitente_nome": texto("emitente_nome", 255),
        "destinatario_documento": texto("destinatario_documento", 18),
        "destinatario_nome": texto("destinatario_nome", 255),
        "situacao": texto("status_autorizacao", 255),
        "origem": origem or ("adn" if tipo == TipoDocumentoFiscal.NFSE else "sefaz"),
    }
    criado = _inserir_documento_sem_duplicar(db, valores)
    documento = (
        db.query(DocumentoFiscal)
        .filter(DocumentoFiscal.empresa_id == empresa_id, DocumentoFiscal.chave_acesso == chave)
        .first()
    )
    if documento is not None:
        # A nota é única, mas cada confirmação de origem fica rastreável. Não
        # muda o XML quando a mesma chave reaparece por outra fonte.
        registrar_proveniencia(db, documento.id, valores["origem"] or "desconhecida", identificador_externo if identificador_externo is not None else str(doc.nsu))
    if not criado:
        return False

    # Só grava o XML depois de vencer a disputa no banco. Assim uma
    # reimportação não sobrescreve o arquivo já associado à nota existente.
    gravar_bytes_atomicamente(xml_path, doc.xml)
    return True


def _processar_evento(
    db, empresa_id: int, tipo: TipoDocumentoFiscal, evento: EventoFiscal
) -> str:
    """
    Aplica um evento recebido na distribuição.

    Retorno:
    - "aplicado": cancelamento aplicado numa nota já gravada;
    - "pendente": cancelamento guardado (a nota ainda não chegou);
    - "duplicado": evento repetido, já tratado antes;
    - "ignorado": não é cancelamento (CC-e etc.) — apenas contabilizado.
    """
    if not evento.eh_cancelamento:
        return "ignorado"

    chave = _normalizar_chave(evento.chave_acesso)
    if not chave:
        # Cancelamento sem chave: não dá pra aplicar, mas não pode sumir.
        return "ignorado"

    documento = (
        db.query(DocumentoFiscal)
        .filter(
            DocumentoFiscal.empresa_id == empresa_id,
            DocumentoFiscal.tipo == tipo,
            DocumentoFiscal.chave_acesso == chave,
        )
        .first()
    )

    if documento is not None:
        if documento.status != StatusDocumentoFiscal.CANCELADA:
            documento.status = StatusDocumentoFiscal.CANCELADA
            documento.motivo_cancelamento = (evento.motivo or "Cancelamento")[:2000]
            documento.cancelado_em = _parse_data_evento(evento.data_evento)
            return "aplicado"
        return "duplicado"

    # A nota ainda não chegou (ordem de NSU não é garantida): guarda o
    # evento para aplicar automaticamente quando o documento for gravado.
    existente = (
        db.query(EventoFiscalPendente)
        .filter(
            EventoFiscalPendente.empresa_id == empresa_id,
            EventoFiscalPendente.tipo == tipo,
            EventoFiscalPendente.chave_acesso == chave,
            EventoFiscalPendente.tipo_evento == evento.tipo_evento,
        )
        .first()
    )
    if existente is not None:
        return "duplicado"

    db.add(
        EventoFiscalPendente(
            empresa_id=empresa_id,
            tipo=tipo,
            chave_acesso=chave,
            tipo_evento=evento.tipo_evento,
            nsu=str(evento.nsu or "0"),
            motivo=(evento.motivo or "Cancelamento")[:2000],
            data_evento=_parse_data_evento(evento.data_evento),
        )
    )
    return "pendente"


def _aplicar_eventos_pendentes(
    db, empresa_id: int, tipo: TipoDocumentoFiscal, chave: str
) -> bool:
    """
    Quando a nota chega, aplica os cancelamentos que ficaram pendentes.
    Retorna True se algum cancelamento foi aplicado agora.
    """
    chave = _normalizar_chave(chave)
    pendentes = (
        db.query(EventoFiscalPendente)
        .filter(
            EventoFiscalPendente.empresa_id == empresa_id,
            EventoFiscalPendente.tipo == tipo,
            EventoFiscalPendente.chave_acesso == chave,
            EventoFiscalPendente.tipo_evento == "cancelamento",
            EventoFiscalPendente.processado.is_(False),
        )
        .all()
    )
    if not pendentes:
        return False

    documento = (
        db.query(DocumentoFiscal)
        .filter(
            DocumentoFiscal.empresa_id == empresa_id,
            DocumentoFiscal.tipo == tipo,
            DocumentoFiscal.chave_acesso == chave,
        )
        .first()
    )
    if documento is None:
        return False

    aplicou = False
    for pendente in pendentes:
        pendente.processado = True
        pendente.documento_id = documento.id
        if documento.status != StatusDocumentoFiscal.CANCELADA:
            documento.status = StatusDocumentoFiscal.CANCELADA
            documento.motivo_cancelamento = pendente.motivo or "Cancelamento"
            documento.cancelado_em = pendente.data_evento or _agora()
            aplicou = True
    return aplicou


def _parse_data_evento(valor: str | None) -> datetime | None:
    if not valor or not str(valor).strip():
        return _agora()
    try:
        dt = date_parser.isoparse(str(valor).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError, OverflowError):
        return _agora()


def _resumir_avisos(aviso_atual: str | None, novos: list[str], limite: int = 20) -> str:
    """Anexa avisos da execução sem crescer sem limite."""
    itens = [a for a in (aviso_atual or "").split("\n") if a and not a.startswith("…")]
    for novo in novos:
        if novo not in itens:
            itens.append(novo)
    if len(itens) > limite:
        resto = len(itens) - limite
        itens = itens[:limite]
        itens.append(f"… e mais {resto} aviso(s) no total")
    return "\n".join(itens)


def _marcar_erro(
    db, execucao: ExecucaoImportacao | None, mensagem: str, falha: str = "captura"
) -> None:
    """
    Fecha a execução em erro.

    `falha` é a natureza do problema (fila, cadastro, ambiente fiscal, leitura
    parcial, sistema); é o que permite à tela dar o próximo passo CERTO. Sem
    ela, toda falha recebia o mesmo conselho — inclusive "confira o certificado
    A1" para uma fila fora do ar, que não tem nada a ver com certificado.
    """
    if execucao is None:
        return
    execucao.status = StatusExecucao.ERRO
    execucao.falha = falha
    execucao.mensagem_erro = mensagem[:4000] if mensagem else "Erro desconhecido"
    execucao.finalizado_em = _agora()
    db.commit()


# ---------------------------------------------------------------------------
# Agendador (Celery Beat): o "quase 100% automático" de verdade
# ---------------------------------------------------------------------------


@celery_app.task(name="sincronizar_tudo", bind=True, max_retries=0)
def sincronizar_tudo(self) -> dict:
    """
    Varredura do agendador: dispara o que estiver liberado e acorda o que
    estava dormindo. Nenhuma requisição é feita daqui — só decisão.

    Rodar isto a cada poucos minutos é o que torna o sistema autônomo: as
    janelas de consumo (1h por empresa+tipo depois de "nada novo") limitam o
    ritmo por conta própria, então o tick barato é justamente o design certo.
    """
    if not settings.sincronismo_automatico:
        return {"desativado": True}

    db = SessionLocal()
    resumo = {"enfileiradas": 0, "aguardando": 0, "ignoradas": 0, "retomadas": 0}
    try:
        # Batimento do agendador: esta task só roda periodicamente se o Celery
        # Beat estiver vivo. Sem sinal recente, a tela inicial avisa "o
        # agendador parou" — em vez de deixar o operador descobrir pela falta
        # de documentos novos.
        batimento.registrar(
            db, "agendador", f"tick de {settings.sincronismo_intervalo_minutos} min"
        )
        # Um worker morto não pode deixar "em andamento" bloqueando o CNPJ
        # para sempre. Sem lease vivo, o prazo considera o hard time limit;
        # tarefas que nem começaram usam a janela conservadora do broker.
        agora_tick = _agora()
        candidatas = db.query(ExecucaoImportacao).filter(
            ExecucaoImportacao.status == StatusExecucao.EM_ANDAMENTO,
            ExecucaoImportacao.iniciado_em < agora_tick - sincronizacao.LEASE_MAXIMO,
        ).all()
        for parada in candidatas:
            estado_parado = sincronizacao.obter_estado(db, parada.empresa_id, parada.tipo, criar=False)
            if estado_parado and sincronizacao.esta_travado(estado_parado, agora=agora_tick):
                continue
            inicio = parada.iniciado_em.replace(tzinfo=timezone.utc) if parada.iniciado_em.tzinfo is None else parada.iniciado_em
            tinha_lease = estado_parado is not None and estado_parado.travado_em is not None
            margem = sincronizacao.LEASE_MAXIMO if tinha_lease else timedelta(seconds=max(settings.broker_visibility_timeout_segundos, settings.limite_tempo_task_segundos + 120))
            if inicio + margem > agora_tick:
                continue
            fila.reagendar(db, parada, agora_tick, motivo="Retomada de execução sem worker/lease ativo; checkpoint preservado.")

        # 1) execuções dormindo cujo bloqueio venceu: retoma (backstop caso o
        #    refiro agendado se perca — restart de worker, broker, etc.)
        vencidas = (
            db.query(ExecucaoImportacao)
            .filter(
                ExecucaoImportacao.status == StatusExecucao.AGUARDANDO,
                ExecucaoImportacao.bloqueado_ate.isnot(None),
                ExecucaoImportacao.bloqueado_ate <= _agora(),
            )
            .limit(50)
            .all()
        )
        for execucao in vencidas:
            empresa = db.get(Empresa, execucao.empresa_id)
            if empresa is None:
                continue
            if not empresa.ativa:
                _marcar_erro(db, execucao, "Empresa inativa: retomada cancelada.", falha="cadastro")
                continue
            libertacao = sincronizacao.liberacao_para(db, empresa.id, execucao.tipo)
            if not libertacao.pode:
                # continua dormindo, só empurra o horário
                execucao.bloqueado_ate = libertacao.quando
                continue
            if fila.retomar(db, execucao):
                resumo["retomadas"] += 1
        db.commit()

        # 2) empresas em modo automático cuja janela está livre: enfileira UMA
        #    varredura por empresa+tipo, sempre pela mesma porta (fila.enfileirar),
        #    que respeita o cooldown de 1h. É isto que torna o sistema autônomo:
        #    sem depender de clique manual, ninguém reconsulta antes da hora e o
        #    cronômetro do 656 nunca é zerado. Quem está na janela vira
        #    "aguardando" (não é erro) e o próprio tick tenta de novo mais tarde.
        limite = max(1, int(settings.sincronismo_lote_empresas))
        empresas_enfileiradas = 0
        for empresa, tipos in fila.disponiveis_para_sincronismo_automatico(db):
            gerou_trabalho = False
            for tipo in tipos:
                resultado = fila.enfileirar(db, empresa, tipo, origem="auto")
                if resultado.status == "enfileirada":
                    resumo["enfileiradas"] += 1
                    gerou_trabalho = True
                elif resultado.status == "em_cooldown":
                    resumo["aguardando"] += 1
                else:
                    # em_andamento / sem_certificado / sem_uf / fila_indisponivel:
                    # nenhuma requisição foi feita; só não há o que disparar agora.
                    resumo["ignoradas"] += 1
            if gerou_trabalho:
                empresas_enfileiradas += 1
                if empresas_enfileiradas >= limite:
                    break
        db.commit()

        if resumo["enfileiradas"] or resumo["retomadas"]:
            log.info("Agendador: %s", resumo)
        if (
            db.query(DocumentoFiscal.id)
            .filter(
                DocumentoFiscal.leiaute == "resumo",
                DocumentoFiscal.tipo == TipoDocumentoFiscal.NFE,
                DocumentoFiscal.manifestacao_erro.is_(None),
            )
            .first()
            is not None
        ):
            try:
                completar_xmls_pendentes.delay()
            except Exception:  # noqa: BLE001
                pass
        return resumo
    except Exception as exc:  # noqa: BLE001 — o tick do agendador nunca derruba o beat
        log.exception("Agendador falhou: %s", exc)
        db.rollback()
        return {"erro": str(exc)[:500], **resumo}
    finally:
        db.close()


def _consciente(valor: datetime | None) -> datetime | None:
    """Datetime com fuso. O SQLite devolve naive mesmo em coluna timezone=True."""
    if valor is None:
        return None
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor


def _hora_de_tentar_completar(documento: DocumentoFiscal, *, agora: datetime | None = None) -> bool:
    """
    Já passou o intervalo desta nota? (espaça a cota de 20 consultas/h)

    A consulta pontual por chave é limitada por CNPJ, não por nota. Sem espaçar,
    as mesmas notas tentadas na rodada anterior consomem a cota inteira e as
    notas novas — as que ainda estão dentro do prazo de 10 dias da Ciência —
    nunca chegam a ser manifestadas. O intervalo dobra a cada tentativa, até 24h.
    """
    tentativas = int(documento.tentativas_completar or 0)
    ultima = _consciente(documento.ultima_tentativa_completar_em)
    if tentativas <= 0 or ultima is None:
        return True
    agora = agora or _agora()
    horas = min(2 ** (tentativas - 1), 24)
    return agora - ultima >= timedelta(hours=horas)


def _pendentes_de_completar(db, empresa: Empresa, limite: int) -> list[DocumentoFiscal]:
    """
    NF-e que ainda estão em `resumo` e podem avançar nesta rodada.

    Regras que este filtro garante:

    - rejeição definitiva (`manifestacao_erro`) sai da fila — senão uma nota
      recusada ocupa vaga a cada rodada e barra todas as outras;
    - empresa sem manifestação automática só recebe a busca de XML já
      manifestado (a Ciência é ato jurídico e é opt-in);
    - **urgência primeiro:** a Ciência da Operação só é aceita até 10 dias da
      autorização. Nota ainda dentro da janela vem antes (mais antiga primeiro,
      porque é a que está prestes a perdê-la); fora da janela, só a manifestação
      conclusiva resolve e a nota não pode furar a fila;
    - tentativa repetida respeita um intervalo crescente (`_hora_de_tentar_completar`).
    """
    agora = _agora()
    limite_ciencia = agora - timedelta(days=PRAZO_CIENCIA_DIAS)
    consulta = db.query(DocumentoFiscal).filter(
        DocumentoFiscal.empresa_id == empresa.id,
        DocumentoFiscal.leiaute == "resumo",
        DocumentoFiscal.tipo == TipoDocumentoFiscal.NFE,
        DocumentoFiscal.manifestacao_erro.is_(None),
    )
    if not empresa.manifestar_automaticamente:
        consulta = consulta.filter(DocumentoFiscal.manifestado_em.isnot(None))
    dentro_do_prazo = case((DocumentoFiscal.data_emissao >= limite_ciencia, 0), else_=1)
    candidatas = (
        consulta.order_by(
            dentro_do_prazo,
            DocumentoFiscal.data_emissao.asc(),
            DocumentoFiscal.id.asc(),
        )
        .limit(max(limite, limite * 4))
        .all()
    )
    return [doc for doc in candidatas if _hora_de_tentar_completar(doc, agora=agora)][:limite]


@celery_app.task(name="completar_xmls_pendentes", bind=True, max_retries=0)
def completar_xmls_pendentes(self, empresa_id: int | None = None, limite: int | None = None) -> dict:
    """
    Busca o XML completo das notas que chegaram só em resumo (`resNFe`).

    Pelo leiaute oficial, enquanto o destinatário não se manifesta o Ambiente
    Nacional distribui o `resNFe`; o caminho suportado para obter o XML
    integral é a consulta pontual pela chave (`consChNFe`) — limitada a 20
    consultas/h por CNPJ. Por isso este task consome a cota aos poucos, respeita
    o lease da empresa e para imediatamente se vier 656.

    Roda sozinha no agendador; o botão "completar XML" da tela chama a mesma
    task para uma empresa só.
    """
    db = SessionLocal()
    resultado = {
        "completos": 0,
        "indisponiveis": 0,
        "sem_cota": 0,
        "aguardando_janela": 0,
        "empresas": 0,
        "manifestados": 0,
        "aguardando_manifestacao": 0,
        "manifestacao_recusada": 0,
    }
    limite_por_empresa = max(1, min(20, int(limite or settings.limite_consultas_pontuais_por_hora)))
    try:
        batimento.registrar(db, "worker", "completar_xmls_pendentes")
        consulta = db.query(Empresa).filter(Empresa.ativa.is_(True))
        if empresa_id is not None:
            consulta = consulta.filter(Empresa.id == empresa_id)
        empresas = consulta.order_by(Empresa.id).all()

        for empresa in empresas:
            documentos_pendentes = _pendentes_de_completar(db, empresa, limite_por_empresa)
            if not documentos_pendentes:
                continue
            resultado["empresas"] += 1

            certificado = (
                db.query(Certificado)
                .filter(Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True))
                .first()
            )
            if certificado is None:
                continue

            estado = sincronizacao.obter_estado(db, empresa.id, TipoDocumentoFiscal.NFE)
            if estado is None:
                continue
            precisa_manifestar = empresa.manifestar_automaticamente and any(
                not doc.manifestado_em for doc in documentos_pendentes
            )
            liberacao = sincronizacao.liberacao_para(db, empresa.id, TipoDocumentoFiscal.NFE)
            if not liberacao.pode and not precisa_manifestar:
                resultado["aguardando_janela"] += len(documentos_pendentes)
                continue
            if not sincronizacao.travar(db, estado):
                db.commit()
                continue

            try:
                db.commit()
                # A task pode ter esperado pelo lease; revalida a janela antes
                # de chamar consChNFe. Notas ainda não manifestadas continuam
                # podendo receber a Ciência da Operação (210210), pois ela vai
                # para o NFeRecepcaoEvento4 e não consome a janela de 1h da
                # distribuição DFe.
                liberacao = sincronizacao.liberacao_para(db, empresa.id, TipoDocumentoFiscal.NFE)
                if not liberacao.pode and not precisa_manifestar:
                    resultado["aguardando_janela"] += len(documentos_pendentes)
                    continue
                importador = obter_importador(TipoDocumentoFiscal.NFE)
                senha = decifrar_segredo(certificado.senha_cifrada)
                pfx_bytes = ler_pfx_protegido(certificado.arquivo_path)

                with sessao_mtls(pfx_bytes, senha) as (cert_path, key_path):
                    for documento in documentos_pendentes:
                        # A distribuição só entrega `resNFe` enquanto a nota
                        # não é manifestada; sem a Ciência da Operação, o
                        # consChNFe abaixo volta vazio para sempre. Por isso
                        # manifestamos ANTES de checar/gastar a cota pontual.
                        acabou_de_manifestar = False
                        if not documento.manifestado_em:
                            if not empresa.manifestar_automaticamente:
                                resultado["aguardando_manifestacao"] += 1
                                continue
                            try:
                                manifesto = manifestar_ciencia(
                                    chave=documento.chave_acesso,
                                    cnpj=empresa.cnpj_cpf,
                                    cert_path=cert_path,
                                    key_path=key_path,
                                    uf=empresa.uf,
                                )
                            except ManifestacaoRecusada as exc:
                                # Rejeição definitiva: repetir não muda nada.
                                # Guarda o motivo E o código — a tela precisa
                                # saber que no 596 (fora do prazo) a saída não é
                                # "tentar de novo", é a manifestação conclusiva.
                                documento.manifestacao_erro = mensagem_manifestacao_recusada(exc)
                                documento.manifestacao_cstat = (exc.cstat or "")[:4] or None
                                resultado["manifestacao_recusada"] += 1
                                db.commit()
                                continue
                            except AmbienteIndisponivel:
                                break
                            documento.manifestado_em = _agora()
                            documento.manifestacao_erro = None
                            documento.manifestacao_cstat = None
                            acabou_de_manifestar = True
                            if not manifesto.ja_estava_manifestada:
                                resultado["manifestados"] += 1
                            # Com a Ciência registrada, há novo XML completo a
                            # buscar na distribuição/consChNFe: libera a espera
                            # de "sem novidade" (preservando bloqueio 656 real).
                            bloqueado_ate = sincronizacao._aware(estado.bloqueado_ate)
                            if not (bloqueado_ate and bloqueado_ate > _agora()):
                                estado.proxima_consulta_em = None
                            db.commit()

                        liberacao = sincronizacao.liberacao_para(db, empresa.id, TipoDocumentoFiscal.NFE)
                        if not liberacao.pode:
                            resultado["aguardando_janela"] += 1
                            continue
                        disponivel = sincronizacao.cota_pontual_disponivel(db, estado)
                        if disponivel <= 0:
                            resultado["sem_cota"] += 1
                            continue

                        try:
                            completo = importador.buscar_por_chave(
                                cnpj=empresa.cnpj_cpf,
                                cert_path=cert_path,
                                key_path=key_path,
                                chave_acesso=documento.chave_acesso,
                                uf=empresa.uf,
                            )
                            if (completo is None or not completo.xml) and acabou_de_manifestar and ESPERA_ENTRE_LOTES > 0:
                                time.sleep(min(2.0, ESPERA_ENTRE_LOTES))
                                completo = importador.buscar_por_chave(
                                    cnpj=empresa.cnpj_cpf,
                                    cert_path=cert_path,
                                    key_path=key_path,
                                    chave_acesso=documento.chave_acesso,
                                    uf=empresa.uf,
                                )
                        except ConsumoIndevido as exc:
                            sincronizacao.consumir_cota_pontual(db, estado)
                            if exc.ultimo_nsu:
                                sincronizacao.realinhar_cursor(
                                    db, estado, ultimo_nsu=exc.ultimo_nsu, max_nsu=exc.max_nsu
                                )
                            sincronizacao.marcar_consumo_indevido(
                                db, estado, motivo=f"consChNFe: {exc.motivo}", bloqueio=getattr(exc, "bloqueio", None)
                            )
                            db.commit()
                            break
                        except AmbienteIndisponivel:
                            # 5xx/rede não consome a cota oficial; mantém a
                            # consulta pontual disponível para a próxima rodada.
                            break

                        sincronizacao.consumir_cota_pontual(db, estado)
                        # Tentativa contada ANTES de olhar o resultado: o que
                        # controla o intervalo é o gasto da cota, não o sucesso.
                        documento.tentativas_completar = (documento.tentativas_completar or 0) + 1
                        documento.ultima_tentativa_completar_em = _agora()
                        if completo is None or not completo.xml:
                            # Ainda não há XML completo liberado (o normal nas
                            # primeiras horas depois da Ciência). A nota fica
                            # como está e volta na próxima rodada espaçada.
                            resultado["indisponiveis"] += 1
                            db.commit()
                            continue

                        if not _sobrescrever_xml(documento, completo):
                            resultado["indisponiveis"] += 1
                            db.commit()
                            continue
                        sincronizacao.marcar_consulta_ok(db, estado)
                        resultado["completos"] += 1
                        db.commit()
                        time.sleep(ESPERA_ENTRE_LOTES)
            finally:
                sincronizacao.liberar(db, estado)
                db.commit()

        return resultado
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("completar_xmls_pendentes falhou: %s", exc)
        return {"erro": str(exc)[:500], **resultado}
    finally:
        db.close()


def mensagem_manifestacao_recusada(erro: ManifestacaoRecusada) -> str:
    """Mensagem para o operador a partir do cStat que a SEFAZ devolveu.

    O texto do motivo muda de redação entre as SEFAZ (e entre versões do
    serviço); o código não. O 596 é o que decide a próxima ação: a Ciência só é
    aceita até 10 dias da autorização e, depois disso, o XML completo só é
    liberado por uma manifestação CONCLUSIVA. Mostrar isso é o que impede o
    operador de ficar clicando "tentar de novo" para sempre.
    """
    motivo = (erro.motivo or "").strip() or "Evento recusado pela SEFAZ"
    if erro.cstat == CSTAT_EVENTO_FORA_DO_PRAZO:
        return (
            f"Ciência da Operação fora do prazo de {PRAZO_CIENCIA_DIAS} dias da "
            f"autorização da NF-e (cStat {erro.cstat}: {motivo}). Esta nota não "
            "aceita mais a Ciência; para liberar o XML completo é preciso registrar "
            "uma manifestação conclusiva (Confirmação da Operação, Operação não "
            "Realizada ou Desconhecimento)."
        )
    return f"cStat {erro.cstat}: {motivo}" if erro.cstat else motivo


def _sobrescrever_xml(documento: DocumentoFiscal, completo: DocumentoBaixado) -> bool:
    """
    Substitui o resumo pelo XML completo, mantendo o mesmo caminho de arquivo.

    O arquivo é substituído atomicamente antes do commit: uma falha de disco
    não trunca a evidência anterior. Se o banco falhar, o lote recebido permite
    reaplicar a promoção e reconciliar metadados/arquivo na próxima execução.

    **Recusa qualquer payload que não seja a nota inteira.** É a última linha de
    defesa do acervo: o `consChNFe` devolve `resNFe` (só a autorização) para o
    destinatário que ainda não tem manifestação registrada, e gravar esse XML
    como "completo" fazia a nota sair da fila com um arquivo que a contabilidade
    não pode usar. Devolve True somente quando promoveu de verdade.
    """
    xml = getattr(completo, "xml", b"") or b""
    if (getattr(completo, "leiaute", "") or "") != "completo" or not eh_documento_integral(xml):
        log.warning(
            "Documento %s: recebi %s no lugar da NF-e completa — nada foi sobrescrito.",
            documento.chave_acesso,
            classificar_documento_dfe(xml),
        )
        return False

    caminho = documento.xml_path
    gravar_bytes_atomicamente(caminho, xml)

    documento.leiaute = "completo"
    # O XML integral chegou: qualquer rejeição/pendência anterior de
    # manifestação virou história. Deixar `manifestacao_erro` preenchido
    # manteria a nota fora de `_pendentes_de_completar` para sempre e exibiria
    # um erro velho numa nota que já está completa no acervo.
    documento.manifestacao_erro = None
    documento.manifestacao_cstat = None
    documento.tentativas_completar = 0
    documento.ultima_tentativa_completar_em = None
    documento.valor_total = valor_monetario(completo.valor_total if completo.valor_total is not None else documento.valor_total)
    if completo.data_emissao:
        documento.data_emissao = _parse_data_emissao(completo.data_emissao)
    competencia = _parse_data(completo.competencia)
    if competencia:
        documento.competencia = competencia
    if completo.numero:
        documento.numero = completo.numero[:20]
    if completo.serie:
        documento.serie = completo.serie[:10]
    if completo.emitente_nome:
        documento.emitente_nome = completo.emitente_nome[:255]
    for campo, limite in (("emitente_documento", 18), ("destinatario_documento", 18), ("destinatario_nome", 255)):
        valor = str(getattr(completo, campo, "") or "").strip()
        if valor:
            setattr(documento, campo, valor[:limite])
    situacao = getattr(completo, "status_autorizacao", "")
    if situacao:
        documento.situacao = situacao[:255]
    return True


def completar_xml_documento_imediato(db, documento: DocumentoFiscal) -> tuple[bool, str]:
    """
    Registra a Ciência da Operação (210210) e busca o XML completo (`procNFe`)
    pela chave (`consChNFe`) sob demanda para uma NF-e individual.

    Permite que ao abrir ou baixar uma nota em `resumo` (`resNFe`), o sistema
    obtenha a nota fiscal completa diretamente na SEFAZ usando o certificado A1
    da empresa — sem exigir consulta externa em ferramentas como FSist/Portal.
    """
    if documento.tipo != TipoDocumentoFiscal.NFE:
        return documento.leiaute == "completo", ""

    empresa = db.get(Empresa, documento.empresa_id)
    if empresa is None:
        return False, "Empresa não encontrada."

    certificado = (
        db.query(Certificado)
        .filter(Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True))
        .first()
    )
    if certificado is None or not certificado.arquivo_path or not os.path.isfile(certificado.arquivo_path):
        return (
            False,
            "Esta nota ainda está apenas em resumo (resNFe) e a empresa está sem certificado A1 ativo para buscar o XML completo na SEFAZ.",
        )

    estado = sincronizacao.obter_estado(db, empresa.id, TipoDocumentoFiscal.NFE)
    importador = obter_importador(TipoDocumentoFiscal.NFE)
    try:
        senha = decifrar_segredo(certificado.senha_cifrada)
        pfx_bytes = ler_pfx_protegido(certificado.arquivo_path)
    except Exception as exc:  # noqa: BLE001
        return False, f"Não foi possível abrir o certificado A1 da empresa: {exc}"

    try:
        with sessao_mtls(pfx_bytes, senha) as (cert_path, key_path):
            acabou_de_manifestar = False
            if not documento.manifestado_em:
                try:
                    manifestar_ciencia(
                        chave=documento.chave_acesso,
                        cnpj=empresa.cnpj_cpf,
                        cert_path=cert_path,
                        key_path=key_path,
                        uf=empresa.uf,
                    )
                except ManifestacaoRecusada as exc:
                    documento.manifestacao_erro = mensagem_manifestacao_recusada(exc)
                    documento.manifestacao_cstat = (exc.cstat or "")[:4] or None
                    db.commit()
                    if exc.cstat == CSTAT_EVENTO_FORA_DO_PRAZO:
                        return False, documento.manifestacao_erro
                    return False, f"A SEFAZ recusou a Ciência da Operação desta nota: {exc}"
                except AmbienteIndisponivel as exc:
                    return False, f"Ambiente Nacional da SEFAZ indisponível no momento para registrar a Ciência: {exc}"

                documento.manifestado_em = _agora()
                documento.manifestacao_erro = None
                documento.manifestacao_cstat = None
                acabou_de_manifestar = True
                if estado is not None:
                    bloqueado_ate = sincronizacao._aware(estado.bloqueado_ate)
                    if not (bloqueado_ate and bloqueado_ate > _agora()):
                        estado.proxima_consulta_em = None
                db.commit()

            try:
                completo = importador.buscar_por_chave(
                    cnpj=empresa.cnpj_cpf,
                    cert_path=cert_path,
                    key_path=key_path,
                    chave_acesso=documento.chave_acesso,
                    uf=empresa.uf,
                )
                if (completo is None or not completo.xml) and acabou_de_manifestar and ESPERA_ENTRE_LOTES > 0:
                    time.sleep(min(2.0, ESPERA_ENTRE_LOTES))
                    completo = importador.buscar_por_chave(
                        cnpj=empresa.cnpj_cpf,
                        cert_path=cert_path,
                        key_path=key_path,
                        chave_acesso=documento.chave_acesso,
                        uf=empresa.uf,
                    )
            except ConsumoIndevido as exc:
                if estado is not None:
                    sincronizacao.consumir_cota_pontual(db, estado)
                    if exc.ultimo_nsu:
                        sincronizacao.realinhar_cursor(
                            db, estado, ultimo_nsu=exc.ultimo_nsu, max_nsu=exc.max_nsu
                        )
                    sincronizacao.marcar_consumo_indevido(
                        db, estado, motivo=f"consChNFe: {exc.motivo}", bloqueio=getattr(exc, "bloqueio", None)
                    )
                    db.commit()
                return (
                    False,
                    f"Ciência da Operação registrada, mas a SEFAZ limitou a consulta imediata por chave ({exc.motivo}). O robô baixará o XML completo automaticamente assim que a janela abrir.",
                )
            except AmbienteIndisponivel as exc:
                return (
                    False,
                    f"Ciência da Operação registrada, mas a consulta por chave na SEFAZ oscilou ({exc}). Tente novamente em instantes.",
                )

            if estado is not None:
                sincronizacao.consumir_cota_pontual(db, estado)

            if completo is not None and completo.xml:
                _sobrescrever_xml(documento, completo)
                if estado is not None:
                    sincronizacao.marcar_consulta_ok(db, estado)
                db.commit()
                return True, "XML completo (procNFe) obtido da SEFAZ."

            db.commit()
            try:
                completar_xmls_pendentes.delay(empresa_id=empresa.id)
            except Exception:  # noqa: BLE001
                pass
            return (
                False,
                "Ciência da Operação registrada na SEFAZ. O Ambiente Nacional ainda está liberando o XML completo (procNFe) desta nota — aguarde alguns instantes e clique novamente.",
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("completar_xml_documento_imediato falhou para doc %s: %s", documento.id, exc)
        return False, f"Não foi possível consultar o XML completo na SEFAZ agora: {exc}"



@celery_app.task(name="varrer_alertas_webhook", bind=True, max_retries=0)
def varrer_alertas_webhook(self) -> dict:
    """
    Envia os alertas abertos ao webhook externo (Slack/Discord/n8n/gateway).

    Roda no Beat a cada `ALERTA_WEBHOOK_INTERVALO_MINUTOS`. Sem URL
    configurada, não faz nada. Cada alerta respeita o nível mínimo e o
    cooldown de reenvio — ninguém recebe a mesma mensagem a cada 15 min.
    """
    from app.api.routers.alertas import computar_alertas
    from app.models import Escritorio
    from app.services import webhook as svc_webhook

    if not (settings.alerta_webhook_url or "").strip():
        return {"desativado": True}

    db = SessionLocal()
    resumo: dict = {"enviados": 0, "ignorados": 0, "erros": []}
    try:
        escritorios = [linha[0] for linha in db.query(Escritorio.id).all()]
        for escritorio_id in escritorios:
            for alerta in computar_alertas(db, escritorio_id):
                if not svc_webhook.nivel_vale(alerta.nivel, settings.alerta_webhook_min_nivel):
                    continue
                chave = f"webhook:{escritorio_id}:{alerta.id}"
                if svc_webhook.ja_enviado_recente(chave, settings.alerta_webhook_cooldown_minutos):
                    resumo["ignorados"] += 1
                    continue
                ok, detalhe = svc_webhook.disparar(
                    alerta.model_dump(), escritorio_id=escritorio_id
                )
                if ok:
                    resumo["enviados"] += 1
                    svc_webhook.marcar_enviado(chave, settings.alerta_webhook_cooldown_minutos)
                else:
                    resumo["erros"].append(detalhe[:200])
        if resumo["enviados"]:
            log.info("Webhook: %s", resumo)
        return resumo
    except Exception as exc:  # noqa: BLE001 — o tick nunca derruba o beat
        log.exception("Varredura de webhook falhou: %s", exc)
        resumo["erros"].append(str(exc)[:200])
        return resumo
    finally:
        db.close()


@celery_app.task(name="backup_agendado", bind=True, max_retries=0)
def backup_agendado(self) -> dict:
    """
    O backup das 03:00 — disparado pelo Beat, executado aqui.

    Roda no worker para não competir com requisições da UI, e usa o mesmo
    serviço do botão "Executar agora" da Saúde do sistema: um caminho só,
    testado do mesmo jeito.
    """
    from app.services import backup as svc_backup

    if not settings.backup_ativo:
        return {"desativado": True}

    db = SessionLocal()
    try:
        batimento.registrar(db, "worker", "backup_agendado")
        registro = svc_backup.executar_backup(db, tipo="agendado")
        return {
            "status": registro.status.value if hasattr(registro.status, "value") else str(registro.status),
            "caminho": registro.caminho,
            "erro": registro.erro,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Manifestação conclusiva: o caminho para a nota que passou dos 10 dias
# ---------------------------------------------------------------------------


def manifestar_conclusiva_lote(
    db,
    documentos: list[DocumentoFiscal],
    *,
    tipo_evento: str,
    justificativa: str = "",
) -> list[dict]:
    """Registra a manifestação conclusiva de cada nota e busca o XML liberado.

    Existe pelo prazo da norma (Ajuste SINIEF 44/20 / NT 2020.001): a Ciência da
    Operação só é aceita até **10 dias** da autorização da NF-e. Passado isso, a
    SEFAZ recusa com cStat 596 e a nota fica presa em resumo — sem XML completo
    para escriturar, e sem nenhum caminho automático. As manifestações
    conclusivas (Confirmação 210200, Desconhecimento 210220, Operação não
    Realizada 210240) são aceitas por até 180 dias e também liberam a NF-e no
    Ambiente Nacional — **exceto o Desconhecimento**, que por regra do manual
    não devolve o XML (não há operação a registrar).

    Como é ato de negócio, quem dispara é o operador na tela; esta função faz o
    trabalho pesado (assinar, enviar, marcar a nota, buscar o XML) e devolve um
    resultado por documento para a interface mostrar o que aconteceu.

    Retorna uma lista de dicionários: `{documento_id, chave, ok, mensagem}`.
    """
    from app.services.importadores.manifestacao import manifestar_conclusiva

    if tipo_evento not in EVENTOS_CONCLUSIVOS:
        raise ValueError(f"Evento {tipo_evento} não é manifestação conclusiva.")

    resultados: list[dict] = []
    # Uma sessão mTLS e um certificado por empresa: o evento vai para o
    # Ambiente Nacional com o A1 da própria empresa da nota.
    por_empresa: dict[int, list[DocumentoFiscal]] = {}
    for documento in documentos:
        por_empresa.setdefault(documento.empresa_id, []).append(documento)

    for empresa_id, desta_empresa in por_empresa.items():

        def resultado(documento: DocumentoFiscal, ok: bool, mensagem: str) -> None:
            resultados.append(
                {
                    "documento_id": documento.id,
                    "chave_acesso": documento.chave_acesso,
                    "ok": ok,
                    "mensagem": mensagem,
                }
            )

        empresa = db.get(Empresa, empresa_id)
        if empresa is None:
            for documento in desta_empresa:
                resultado(documento, False, "Empresa não encontrada.")
            continue
        certificado = (
            db.query(Certificado)
            .filter(Certificado.empresa_id == empresa_id, Certificado.ativo.is_(True))
            .first()
        )
        if certificado is None:
            for documento in desta_empresa:
                resultado(documento, False, "Empresa sem certificado A1 ativo.")
            continue
        estado = sincronizacao.obter_estado(db, empresa_id, TipoDocumentoFiscal.NFE)
        try:
            senha = decifrar_segredo(certificado.senha_cifrada)
            pfx_bytes = ler_pfx_protegido(certificado.arquivo_path)
        except Exception as exc:  # noqa: BLE001
            for documento in desta_empresa:
                resultado(documento, False, f"Não foi possível abrir o certificado A1: {exc}")
            continue

        precisa_buscar = False
        with sessao_mtls(pfx_bytes, senha) as (cert_path, key_path):
            for documento in desta_empresa:
                try:
                    evento = manifestar_conclusiva(
                        chave=documento.chave_acesso,
                        cnpj=empresa.cnpj_cpf,
                        cert_path=cert_path,
                        key_path=key_path,
                        tipo_evento=tipo_evento,
                        justificativa=justificativa,
                        uf=empresa.uf,
                    )
                except ManifestacaoRecusada as exc:
                    documento.manifestacao_erro = mensagem_manifestacao_recusada(exc)
                    documento.manifestacao_cstat = (exc.cstat or "")[:4] or None
                    db.commit()
                    resultado(documento, False, documento.manifestacao_erro)
                    continue
                except AmbienteIndisponivel as exc:
                    db.commit()
                    resultado(
                        documento,
                        False,
                        f"Ambiente Nacional indisponível no momento ({exc}). Nada foi registrado; tente de novo.",
                    )
                    continue

                documento.manifestado_em = _agora()
                documento.manifestacao_erro = None
                documento.manifestacao_cstat = None
                db.commit()

                if tipo_evento == TIPO_EVENTO_DESCONHECIMENTO:
                    resultado(
                        documento,
                        True,
                        "Desconhecimento registrado. Por regra do ambiente, o XML completo "
                        "não é liberado para nota desconhecida.",
                    )
                    continue

                # A manifestação faz o Ambiente Nacional gerar o NSU com a NF-e
                # completa; buscamos pela chave para não depender do próximo
                # ciclo de distribuição.
                completa = False
                if estado is not None and sincronizacao.cota_pontual_disponivel(db, estado) > 0:
                    try:
                        importador = obter_importador(TipoDocumentoFiscal.NFE)
                        baixado = importador.buscar_por_chave(
                            cnpj=empresa.cnpj_cpf,
                            cert_path=cert_path,
                            key_path=key_path,
                            chave_acesso=documento.chave_acesso,
                            uf=empresa.uf,
                        )
                        sincronizacao.consumir_cota_pontual(db, estado)
                        if baixado is not None and _sobrescrever_xml(documento, baixado):
                            sincronizacao.marcar_consulta_ok(db, estado)
                            db.commit()
                            completa = True
                    except ConsumoIndevido as exc:
                        # A consulta pontual foi bloqueada: o importante (a
                        # manifestação) já está registrada. Realinha o cursor e
                        # registra o bloqueio para o robô voltar na hora certa.
                        sincronizacao.consumir_cota_pontual(db, estado)
                        if exc.ultimo_nsu:
                            sincronizacao.realinhar_cursor(
                                db, estado, ultimo_nsu=exc.ultimo_nsu, max_nsu=exc.max_nsu
                            )
                        sincronizacao.marcar_consumo_indevido(
                            db,
                            estado,
                            motivo=f"consChNFe: {exc.motivo}",
                            bloqueio=getattr(exc, "bloqueio", None),
                        )
                    except AmbienteIndisponivel:
                        # Rede oscilou na busca: a manifestação continua válida
                        # e o XML completo chega pelo fluxo de NSU.
                        pass
                db.commit()

                if completa:
                    resultado(documento, True, "Manifestação registrada e XML completo obtido da SEFAZ.")
                else:
                    precisa_buscar = True
                    resultado(
                        documento,
                        True,
                        "Manifestação registrada. O Ambiente Nacional ainda está liberando o "
                        "XML completo — o sistema busca sozinho nas próximas rodadas.",
                    )

        if precisa_buscar:
            try:
                completar_xmls_pendentes.delay(empresa_id=empresa_id)
            except Exception:  # noqa: BLE001
                pass

    return resultados
