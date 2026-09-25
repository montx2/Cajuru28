"""
Tasks periódicas do módulo Procurações RFB.

O que roda sozinho aqui é só o que **não** depende de tocar o ambiente da
Receita: manutenção da fila, contagem de prazos, alertas e leitura das fontes
oficiais/configuradas. A operação no portal continua sendo ato humano
assistido — ver `app/procuracoes/portal.py` e a IN RFB nº 2.320/2026, art. 13.

Todas as tasks são:

- **idempotentes**: rodar duas vezes no mesmo minuto não duplica nada;
- **por escritório**: um tenant com erro não impede o próximo;
- **silenciosas quando desligadas**: `PROCURACOES_ATIVO=false` interrompe o
  agendamento inteiro sem precisar mexer no beat.
"""

from __future__ import annotations

import logging
from datetime import date

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Escritorio
from app.procuracoes.estados import CodigoErro
from app.procuracoes.integracoes.base import FonteError
from app.procuracoes.integracoes.registro import ROTULOS, construir, fontes_configuradas
from app.procuracoes.servicos import agentes as srv_agentes
from app.procuracoes.servicos import certificados as srv_certificados
from app.procuracoes.servicos import configuracao as srv_config
from app.procuracoes.servicos import eventos as srv_eventos
from app.procuracoes.servicos import evidencias as srv_evidencias
from app.procuracoes.servicos import fila as srv_fila
from app.procuracoes.servicos import sincronizacao as srv_sinc
from app.worker.celery_app import celery_app

log = logging.getLogger("cajuru.procuracoes.tasks")


def _escritorios(db) -> list[int]:
    return [linha[0] for linha in db.query(Escritorio.id).all()]


@celery_app.task(name="procuracoes_manutencao", bind=True, max_retries=0)
def procuracoes_manutencao(self) -> dict:
    """Varredura de manutenção: leases, prazos, alertas e higiene.

    É a task que faz o módulo "andar sozinho" sem tocar no portal:

    1. devolve à fila o que estações abandonadas seguravam;
    2. aplica o tempo sobre as autorizações (expiração e os 30 dias do aceite);
    3. avisa sobre certificado A1 prestes a vencer;
    4. marca como indisponível a estação que parou de responder;
    5. limpa nonces vencidos e evidências fora do prazo de retenção.
    """
    if not settings.procuracoes_ativo:
        return {"ignorado": "modulo_desativado"}

    db = SessionLocal()
    relatorio = {
        "leases_recuperados": 0,
        "autorizacoes_expiradas": 0,
        "aceites_vencidos": 0,
        "alertas": 0,
        "agentes_offline": 0,
        "nonces_removidos": 0,
        "evidencias_expurgadas": 0,
    }
    try:
        relatorio["leases_recuperados"] = srv_fila.recuperar_leases_expirados(db)
        db.commit()

        for escritorio_id in _escritorios(db):
            try:
                contagem = srv_sinc.avaliar_vencimentos(db, escritorio_id)
                relatorio["autorizacoes_expiradas"] += contagem["expiradas"]
                relatorio["aceites_vencidos"] += contagem["aceite_vencido"]
                relatorio["alertas"] += contagem["alertas"]
                relatorio["alertas"] += _alertar_certificados(db, escritorio_id)
                relatorio["agentes_offline"] += _marcar_agentes_ausentes(db, escritorio_id)
                db.commit()
            except Exception:  # noqa: BLE001 — um tenant não derruba os outros
                db.rollback()
                log.exception(
                    "procuracao_manutencao_falhou", extra={"escritorio": escritorio_id}
                )

        relatorio["nonces_removidos"] = srv_agentes.limpar_nonces(db)
        relatorio["evidencias_expurgadas"] = srv_evidencias.expurgar(db)
        srv_sinc.limpar_integracoes_antigas(db)
        db.commit()
    finally:
        db.close()

    log.info("procuracao_manutencao_concluida", extra=relatorio)
    return relatorio


def _alertar_certificados(db, escritorio_id: int) -> int:
    """Um A1 vencido descoberto na hora da assinatura custa a sessão inteira."""
    config = srv_config.obter_configuracao(db, escritorio_id)
    janelas = sorted(config.alerta_dias_lista or [30], reverse=True)
    if not janelas:
        return 0
    hoje = date.today()
    emitidos = 0
    for certificado in srv_certificados.certificados_expirando(db, escritorio_id, janelas[0]):
        if certificado.valido_ate is None:
            continue
        faltam = (certificado.valido_ate.date() - hoje).days
        janela = next((dias for dias in janelas if faltam <= dias), janelas[0])
        vencido = faltam < 0
        srv_eventos.notificar(
            db,
            escritorio_id,
            chave=f"certificado:{certificado.id}:{'vencido' if vencido else janela}",
            tipo="certificado_vencendo",
            nivel="erro" if vencido else "alerta",
            titulo=(
                f"Certificado {'vencido' if vencido else f'vence em {faltam} dia(s)'} — "
                f"{certificado.titular_nome or certificado.documento}"
            ),
            detalhe=(
                f"Validade até {certificado.valido_ate:%d/%m/%Y}. "
                "Sem A1 válido a estação não consegue abrir o portal em nome desta empresa."
            ),
            empresa_id=certificado.empresa_id,
        )
        emitidos += 1
    return emitidos


def _marcar_agentes_ausentes(db, escritorio_id: int) -> int:
    """Estação sem heartbeat vira notificação — silêncio não é 'tudo bem'."""
    from app.procuracoes.modelos import Agente

    config = srv_config.obter_configuracao(db, escritorio_id)
    ausentes = 0
    for agente in (
        db.query(Agente)
        .filter(Agente.escritorio_id == escritorio_id, Agente.ativo.is_(True))
        .all()
    ):
        estado = srv_agentes.situacao(agente, config.heartbeat_tolerancia_segundos)
        if estado != "offline":
            continue
        ausentes += 1
        srv_eventos.notificar(
            db,
            escritorio_id,
            chave=f"agente_offline:{agente.id}",
            tipo="agente_offline",
            nivel="alerta",
            titulo=f"Estação {agente.nome} sem comunicação",
            detalhe=(
                "Nenhum sinal recebido dentro da tolerância configurada. "
                "Jobs em andamento voltam para a fila automaticamente."
            ),
        )
    return ausentes


@celery_app.task(name="procuracoes_sincronizar", bind=True, max_retries=0)
def procuracoes_sincronizar(self, escritorio_id: int | None = None) -> dict:
    """Leitura automática das fontes configuradas.

    Respeita o horário escolhido por escritório: rodar a varredura fora da
    janela combinada surpreende o operador e concorre com a captura fiscal.
    """
    if not settings.procuracoes_ativo:
        return {"ignorado": "modulo_desativado"}

    from datetime import datetime
    from zoneinfo import ZoneInfo

    agora_local = datetime.now(ZoneInfo("America/Sao_Paulo"))
    db = SessionLocal()
    relatorio: dict[str, dict] = {}
    try:
        alvos = [escritorio_id] if escritorio_id else _escritorios(db)
        for alvo in alvos:
            config = srv_config.obter_configuracao(db, alvo)
            db.commit()
            forcado = escritorio_id is not None
            if not forcado:
                if not config.sincronizacao_automatica:
                    continue
                if agora_local.hour != int(config.hora_sincronizacao or 6):
                    continue

            documentos = None
            for fonte in fontes_configuradas(db, alvo):
                try:
                    cliente = construir(db, alvo, fonte)
                    if fonte == "integra_contador":
                        documentos = documentos or _documentos_do_escritorio(db, alvo)
                    resultado = srv_sinc.sincronizar(
                        db,
                        alvo,
                        fonte,
                        cliente,
                        origem="agendado",
                        documentos=documentos if fonte == "integra_contador" else None,
                    )
                    db.commit()
                    relatorio.setdefault(str(alvo), {})[fonte] = resultado.resumo
                except FonteError as exc:
                    db.commit()
                    relatorio.setdefault(str(alvo), {})[fonte] = f"falhou: {exc}"
                    log.warning(
                        "procuracao_sincronizacao_agendada_falhou",
                        extra={"escritorio": alvo, "fonte": ROTULOS.get(fonte, fonte)},
                    )
                except Exception:  # noqa: BLE001
                    db.rollback()
                    log.exception(
                        "procuracao_sincronizacao_agendada_erro",
                        extra={"escritorio": alvo, "fonte": fonte},
                    )
    finally:
        db.close()
    return relatorio


def _documentos_do_escritorio(db, escritorio_id: int) -> list[str]:
    from app.models import Empresa

    return [
        linha[0]
        for linha in db.query(Empresa.cnpj_cpf)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .all()
    ]


@celery_app.task(name="procuracoes_enfileirar_pendencias", bind=True, max_retries=0)
def procuracoes_enfileirar_pendencias(self, escritorio_id: int | None = None) -> dict:
    """Monta a fila automaticamente, quando o escritório optou por isso.

    Fica desligado por padrão (`processamento_automatico=False`): montar fila
    sozinho em nome de terceiros é decisão do escritório, não do sistema.
    """
    if not settings.procuracoes_ativo:
        return {"ignorado": "modulo_desativado"}

    db = SessionLocal()
    relatorio: dict[str, dict] = {}
    try:
        alvos = [escritorio_id] if escritorio_id else _escritorios(db)
        for alvo in alvos:
            config = srv_config.obter_configuracao(db, alvo)
            db.commit()
            if not config.processamento_automatico and escritorio_id is None:
                continue
            try:
                resultado = srv_fila.enfileirar_pendencias(
                    db,
                    alvo,
                    origem="agendado",
                    limite=int(settings.procuracoes_max_jobs_por_ciclo),
                )
                db.commit()
                relatorio[str(alvo)] = {
                    "avaliadas": resultado["avaliadas"],
                    "criados": resultado["criados"],
                    "ja_na_fila": resultado["ja_na_fila"],
                    "ignoradas": resultado["total_ignoradas"],
                }
            except srv_fila.FilaError as exc:
                db.rollback()
                relatorio[str(alvo)] = {"erro": exc.codigo.value, "mensagem": str(exc)}
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception(
                    "procuracao_enfileiramento_falhou", extra={"escritorio": alvo}
                )
    finally:
        db.close()
    return relatorio


@celery_app.task(name="procuracoes_verificar_estacoes", bind=True, max_retries=0)
def procuracoes_verificar_estacoes(self) -> dict:
    """Devolve à fila jobs presos em estações revogadas ou mudas.

    Complementa a recuperação por lease: uma estação pode estar com lease
    válido e, ainda assim, ter sido revogada no meio do caminho.
    """
    if not settings.procuracoes_ativo:
        return {"ignorado": "modulo_desativado"}

    from app.procuracoes.modelos import Agente, JobProcuracao

    db = SessionLocal()
    liberados = 0
    try:
        revogados = [
            linha[0]
            for linha in db.query(Agente.id)
            .filter((Agente.ativo.is_(False)) | (Agente.revogado_em.isnot(None)))
            .all()
        ]
        if revogados:
            presos = (
                db.query(JobProcuracao)
                .filter(
                    JobProcuracao.agente_id.in_(revogados),
                    JobProcuracao.status.in_(srv_fila.ESTADOS_ATIVOS),
                )
                .all()
            )
            for job in presos:
                srv_fila.liberar_lease(db, job)
                srv_fila.registrar_falha(
                    db,
                    job,
                    CodigoErro.AGENTE_REVOGADO,
                    "A estação responsável foi revogada; o job voltou para a fila.",
                )
                liberados += 1
            db.commit()
    finally:
        db.close()
    return {"jobs_liberados": liberados}
