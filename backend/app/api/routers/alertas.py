"""
Central de alertas: tudo que precisa de olho humano, num lugar só.

Os alertas são **computados na hora** a partir do estado real (certificados,
janelas SEFAZ, cursor de NSU, disco) — não há tabela de notificações para
ficar dessincronizada. Quando o problema se resolve, o alerta some sozinho
na próxima leitura.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_papel
from app.api.routers.importacoes import estados_do_escritorio
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    Certificado,
    DocumentoFiscal,
    Empresa,
    ExecucaoImportacao,
    StatusExecucao,
    Usuario,
)
from app.schemas import AlertaItem, AlertasResposta, TesteWebhookResposta
from app.services import auditoria
from app.services import webhook as svc_webhook

router = APIRouter(prefix="/alertas", tags=["alertas"])

_ROTULO_TIPO = {"nfse": "NFS-e", "nfe": "NFe", "cte": "CT-e"}
_PESO_NIVEL = {"critico": 0, "atencao": 1, "info": 2}


def _montar(
    id: str,
    nivel: str,
    categoria: str,
    titulo: str,
    detalhe: str,
    *,
    empresa_id: int | None = None,
    empresa_razao_social: str | None = None,
    acao_rotulo: str | None = None,
    acao_href: str | None = None,
) -> AlertaItem:
    return AlertaItem(
        id=id,
        nivel=nivel,  # type: ignore[arg-type]
        categoria=categoria,  # type: ignore[arg-type]
        titulo=titulo,
        detalhe=detalhe,
        empresa_id=empresa_id,
        empresa_razao_social=empresa_razao_social,
        acao_rotulo=acao_rotulo,
        acao_href=acao_href,
    )


def _hora(iso: datetime | None) -> str:
    if iso is None:
        return "—"
    valor = iso if iso.tzinfo else iso.replace(tzinfo=timezone.utc)
    return valor.astimezone().strftime("%d/%m %H:%M")


def _alertas_procuracoes(db: Session, escritorio_id: int, agora: datetime) -> list[AlertaItem]:
    """Decision pendentes do módulo de Procurações RFB, no vocabulário da fila.

    Regras de volume: processo esperando **pessoa** é pouca coisa e ganha
    alerta próprio com link direto (o clique da fila abre o processo); quando
    são muitos, vira um alerta agregado para não virar parede. O que espera
    **máquina** (estação) só alerta quando nenhuma estação está de pé — com
    estação viva, a fila anda sozinha e alerta seria ruído.
    """
    from app.procuracoes.modelos import Agente, Autorizacao, JobProcuracao
    from app.procuracoes.servicos import agentes as srv_agentes
    from app.procuracoes.servicos import configuracao as srv_config_procuracoes

    itens: list[AlertaItem] = []
    config = srv_config_procuracoes.obter_configuracao(db, escritorio_id)

    # --- estações de execução ----------------------------------------------
    estacoes = (
        db.query(Agente)
        .filter(
            Agente.escritorio_id == escritorio_id,
            Agente.ativo.is_(True),
            Agente.revogado_em.is_(None),
        )
        .all()
    )
    vivas = [
        estacao
        for estacao in estacoes
        if srv_agentes.situacao(estacao, config.heartbeat_tolerancia_segundos)
        in ("online", "processando")
    ]
    if estacoes and not vivas:
        itens.append(
            _montar(
                "proc-estacoes-mudas",
                "atencao",
                "procuracao",
                f"Nenhuma estação de execução de pé ({len(estacoes)} registrada(s))",
                "Os processos de outorga precisam de uma máquina com o Cajuru "
                "Agent. Ligue a estação ou faça a outorga direto no portal e "
                "registre o resultado no processo.",
                acao_rotulo="Ver estações",
                acao_href="/dashboard/procuracoes/estacoes",
            )
        )

    # --- processos esperando uma pessoa -------------------------------------
    esperando_pessoa = (
        "intervencao_manual",
        "pronto_para_operacao",
        "aguardando_assinatura",
        "aguardando_validacao",
    )
    rotulo_do_estado = {
        "intervencao_manual": "intervenção manual",
        "pronto_para_operacao": "sua vez na estação",
        "aguardando_assinatura": "assinatura",
        "aguardando_validacao": "aceite da contabilidade",
    }
    jobs = (
        db.query(JobProcuracao)
        .filter(
            JobProcuracao.escritorio_id == escritorio_id,
            JobProcuracao.status.in_(esperando_pessoa),
        )
        .order_by(JobProcuracao.id)
        .all()
    )
    if jobs:
        empresas = {
            empresa.id: empresa
            for empresa in db.query(Empresa).filter(
                Empresa.id.in_([job.empresa_id for job in jobs])
            ).all()
        }
        if len(jobs) <= 5:
            for job in jobs:
                empresa = empresas.get(job.empresa_id)
                itens.append(
                    _montar(
                        f"proc-job-{job.id}",
                        "atencao",
                        "procuracao",
                        f"Outorga de {empresa.razao_social if empresa else 'empresa'} esperando você",
                        f"Processo #{job.id} parado em "
                        f"{rotulo_do_estado.get(job.status, job.status)}. O próximo "
                        f"passo está no roteiro do processo — a Receita só "
                        f"registra o ato praticado por pessoa.",
                        empresa_id=job.empresa_id,
                        empresa_razao_social=empresa.razao_social if empresa else None,
                        acao_rotulo="Abrir processo",
                        acao_href=f"/dashboard/procuracoes?job={job.id}",
                    )
                )
        else:
            itens.append(
                _montar(
                    "proc-jobs-agregado",
                    "atencao",
                    "procuracao",
                    f"{len(jobs)} processos de outorga esperando você",
                    "Cada um parou num ponto que depende de pessoa — intervenção, "
                    "assinatura ou aceite. Abra a tela de Procurações e resolva "
                    "um por um.",
                    acao_rotulo="Ver processos",
                    acao_href="/dashboard/procuracoes?situacao=intervencao_manual",
                )
            )

    # --- processos esperando estação (só quando ninguém está de pé) ---------
    if estacoes and not vivas:
        esperando_estacao = (
            db.query(func.count(JobProcuracao.id))
            .filter(
                JobProcuracao.escritorio_id == escritorio_id,
                JobProcuracao.status.in_(("pendente", "aguardando_agente")),
            )
            .scalar()
            or 0
        )
        if esperando_estacao:
            itens.append(
                _montar(
                    "proc-jobs-sem-estacao",
                    "atencao",
                    "procuracao",
                    f"{esperando_estacao} processo(s) de outorga esperando estação",
                    "A fila está montada, mas nenhuma estação está comunicando. "
                    "Sem estação, nada sai do lugar.",
                    acao_rotulo="Ver estações",
                    acao_href="/dashboard/procuracoes/estacoes",
                )
            )

    # --- autorizações a expirar ---------------------------------------------
    horizonte = min(config.alerta_dias_lista or [30])
    corte_validade = (agora + timedelta(days=horizonte)).date()
    expirando = (
        db.query(func.count(Autorizacao.id))
        .filter(
            Autorizacao.escritorio_id == escritorio_id,
            Autorizacao.situacao == "ativa",
            Autorizacao.data_validade.isnot(None),
            Autorizacao.data_validade <= corte_validade,
        )
        .scalar()
        or 0
    )
    if expirando:
        itens.append(
            _montar(
                "proc-autorizacoes-expirando",
                "atencao",
                "procuracao",
                f"{expirando} autorização(ões) expiram em até {horizonte} dias",
                "Autorização vencida tira o acesso da contabilidade no e-CAC. "
                "Renove antes do vencimento — a fila de outorga já sabe quem "
                "precisa.",
                acao_rotulo="Ver autorizações",
                acao_href="/dashboard/procuracoes",
            )
        )

    # --- prazo de aceite (a Receita cancela o que não é validado) -----------
    hoje = agora.date()
    em_analise = (
        db.query(Autorizacao)
        .filter(
            Autorizacao.escritorio_id == escritorio_id,
            Autorizacao.situacao == "em_analise",
            Autorizacao.prazo_aceite_ate.isnot(None),
        )
        .all()
    )
    for autorizacao in em_analise:
        prazo = autorizacao.prazo_aceite_ate
        dias = (prazo - hoje).days
        if dias > 7:
            continue
        nome = autorizacao.outorgante_nome or autorizacao.outorgante_documento
        if dias < 0:
            itens.append(
                _montar(
                    f"proc-aceite-vencido-{autorizacao.id}",
                    "critico",
                    "procuracao",
                    f"Prazo de aceite vencido — {nome}",
                    "A Receita cancela autorizações não validadas. Faça o aceite "
                    "no portal e registre-o no processo, ou a outorga terá que "
                    "ser refeita.",
                    acao_rotulo="Ver autorizações",
                    acao_href="/dashboard/procuracoes",
                )
            )
        elif dias <= 3:
            itens.append(
                _montar(
                    f"proc-aceite-urgente-{autorizacao.id}",
                    "critico",
                    "procuracao",
                    f"Aceite em {dias}d — {nome}",
                    "A contabilidade precisa validar a autorização no portal "
                    "antes do prazo, ou a Receita a cancela.",
                    acao_rotulo="Ver autorizações",
                    acao_href="/dashboard/procuracoes",
                )
            )
        else:
            itens.append(
                _montar(
                    f"proc-aceite-prazo-{autorizacao.id}",
                    "atencao",
                    "procuracao",
                    f"Aceite em {dias}d — {nome}",
                    "A contabilidade precisa validar a autorização no portal "
                    "antes do prazo.",
                    acao_rotulo="Ver autorizações",
                    acao_href="/dashboard/procuracoes",
                )
            )

    return itens


def computar_alertas(db: Session, escritorio_id: int) -> list[AlertaItem]:
    agora = datetime.now(timezone.utc)
    itens: list[AlertaItem] = []

    empresas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .order_by(Empresa.razao_social)
        .all()
    )
    ids_ativas = [e.id for e in empresas]
    mapa = {e.id: e for e in empresas}

    # ---- Certificados -----------------------------------------------------
    certificados = (
        {
            c.empresa_id: c
            for c in db.query(Certificado)
            .filter(
                Certificado.empresa_id.in_(ids_ativas or [-1]),
                Certificado.ativo.is_(True),
            )
            .all()
        }
        if ids_ativas
        else {}
    )
    vencidos: list[tuple[Empresa, int]] = []
    vencendo: list[tuple[Empresa, int]] = []
    sem_cert: list[Empresa] = []
    for empresa in empresas:
        cert = certificados.get(empresa.id)
        if cert is None:
            sem_cert.append(empresa)
            continue
        validade = cert.validade
        if validade is not None and validade.tzinfo is None:
            validade = validade.replace(tzinfo=timezone.utc)
        dias = (validade - agora).days if validade is not None else None
        if dias is not None and dias < 0:
            vencidos.append((empresa, dias))
        elif dias is not None and dias <= 30:
            vencendo.append((empresa, dias))

    for empresa, dias in vencidos:
        itens.append(
            _montar(
                f"cert-vencido-{empresa.id}",
                "critico",
                "certificado",
                f"Certificado vencido — {empresa.razao_social}",
                f"Venceu há {abs(dias)} dia(s). Nenhuma importação desta empresa "
                f"funciona até a renovação do A1.",
                empresa_id=empresa.id,
                empresa_razao_social=empresa.razao_social,
                acao_rotulo="Enviar novo certificado",
                acao_href=f"/dashboard/empresa?id={empresa.id}",
            )
        )
    if vencendo:
        nomes = ", ".join(f"{e.razao_social} ({d}d)" for e, d in vencendo[:4])
        resto = len(vencendo) - 4
        itens.append(
            _montar(
                "cert-vencendo",
                "atencao",
                "certificado",
                f"{len(vencendo)} certificado(s) vencendo em até 30 dias",
                f"{nomes}{' …' if resto > 0 else ''} — o A1 leva dias para "
                f"renovar; programe-se antes do vencimento.",
                acao_rotulo="Ver certificados",
                acao_href="/dashboard/certificados",
            )
        )
    if sem_cert:
        nomes = ", ".join(e.razao_social for e in sem_cert[:4])
        resto = len(sem_cert) - 4
        itens.append(
            _montar(
                "cert-ausente",
                "atencao",
                "cadastro",
                f"{len(sem_cert)} empresa(s) sem certificado A1",
                f"{nomes}{' …' if resto > 0 else ''} — sem o .pfx a importação "
                f"nem começa.",
                acao_rotulo="Enviar certificados",
                acao_href="/dashboard/empresas",
            )
        )

    # ---- Janelas SEFAZ, cursor parado e risco de perda --------------------
    for estado in estados_do_escritorio(db, escritorio_id=escritorio_id):
        empresa = mapa.get(estado.empresa_id)
        if empresa is None:
            continue
        rotulo = _ROTULO_TIPO.get(estado.tipo, estado.tipo)
        if estado.risco_documento_fora_da_distribuicao:
            itens.append(
                _montar(
                    f"risco-{estado.empresa_id}-{estado.tipo}",
                    "critico",
                    "distribuicao",
                    f"Risco de perda definitiva — {empresa.razao_social} ({rotulo})",
                    f"{estado.dias_sem_varrer} dias sem varrer com documento "
                    f"faltando. A SEFAZ só guarda ~3 meses: o que passou disso "
                    f"pode já ter saído da distribuição.",
                    empresa_id=empresa.id,
                    empresa_razao_social=empresa.razao_social,
                    acao_rotulo="Puxar agora",
                    acao_href="/dashboard/importacoes",
                )
            )
        elif estado.bloqueado_ate:
            itens.append(
                _montar(
                    f"bloqueio-{estado.empresa_id}-{estado.tipo}",
                    "critico" if estado.bloqueios_seguidos >= 3 else "atencao",
                    "sefaz",
                    f"{rotulo} bloqueada até {_hora(estado.bloqueado_ate)} — {empresa.razao_social}",
                    "Consumo indevido (cStat 656): a janela pertence ao CNPJ na SEFAZ, "
                    "não a este sistema. Mesmo sendo a primeira consulta aqui, outro programa "
                    "pode ter consultado antes. O sistema retoma sozinho na hora certa. "
                    + (
                        f"{estado.bloqueios_seguidos} bloqueios seguidos — outro "
                        f"sistema pode estar consultando este CNPJ."
                        if estado.bloqueios_seguidos >= 2
                        else "Evite forçar antes da hora: isso zera o cronômetro."
                    ),
                    empresa_id=empresa.id,
                    empresa_razao_social=empresa.razao_social,
                    acao_rotulo="Acompanhar",
                    acao_href="/dashboard/importacoes",
                )
            )
        elif (
            estado.dias_sem_varrer is not None
            and estado.dias_sem_varrer >= 7
            and estado.pendencia > 0
        ):
            itens.append(
                _montar(
                    f"parado-{estado.empresa_id}-{estado.tipo}",
                    "atencao",
                    "sincronismo",
                    f"{estado.dias_sem_varrer} dias sem varrer — {empresa.razao_social} ({rotulo})",
                    f"Faltam {estado.pendencia} documento(s). "
                    + (
                        "O sincronismo automático está desligado nesta empresa."
                        if not estado.sincronizar_automaticamente
                        else "Confira se o agendador está rodando."
                    ),
                    empresa_id=empresa.id,
                    empresa_razao_social=empresa.razao_social,
                    acao_rotulo="Ver sincronismo",
                    acao_href=f"/dashboard/empresa?id={empresa.id}",
                )
            )

    # ---- XMLs que chegaram só em resumo -----------------------------------
    resumos = (
        db.query(func.count(DocumentoFiscal.id))
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            DocumentoFiscal.leiaute == "resumo",
        )
        .scalar()
        or 0
    )
    if resumos:
        itens.append(
            _montar(
                "resumos-pendentes",
                "info",
                "xml",
                f"{resumos} documento(s) aguardando XML completo",
                "A SEFAZ distribui primeiro o resumo; o XML inteiro vem pela "
                "chave (cota de 20/h por CNPJ). O sistema completa sozinho — "
                "ou adiante pela tela de Documentos.",
                acao_rotulo="Ver documentos",
                acao_href="/dashboard/documentos",
            )
        )

    # ---- Execuções com erro nas últimas 24h --------------------------------
    corte = agora - timedelta(hours=24)
    if settings.usando_sqlite:
        corte = corte.replace(tzinfo=None)
    erros = (
        db.query(func.count(ExecucaoImportacao.id))
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status == StatusExecucao.ERRO,
            ExecucaoImportacao.iniciado_em >= corte,
        )
        .scalar()
        or 0
    )
    if erros:
        itens.append(
            _montar(
                "erros-24h",
                "atencao",
                "execucao",
                f"{erros} execução(ões) falharam nas últimas 24h",
                "Abra a central de Execuções para ver o motivo de cada "
                "uma — falhas de rede se resolvem sozinhas na retomada.",
                acao_rotulo="Ver execuções",
                acao_href="/dashboard/execucoes",
            )
        )

    # ---- Procurações RFB ----------------------------------------------------
    # A fila "Precisa da sua atenção" é a lista mais importante do sistema —
    # e o módulo de procurações não podia ficar fora dela: um processo de
    # outorga esperando pessoa não é informação "da tela de procurações",
    # é decisão pendente da operação, como certificado vencido.
    if settings.procuracoes_ativo:
        try:
            itens.extend(_alertas_procuracoes(db, escritorio_id, agora))
        except Exception:  # noqa: BLE001 — alerta de procuração nunca derruba os demais
            pass

    # ---- Backup -------------------------------------------------------------
    # Um sistema que guarda anos de XMLs de dezenas de empresas sem backup
    # recente é um risco andando. O alerta aparece quando o job das 03:00
    # não completou (worker parado, disco cheio) — resolver é um clique.
    try:
        from app.services import backup as svc_backup

        saude = svc_backup.saude_do_backup(db)
        if saude["ativo"] and saude["atrasado"]:
            horas = saude.get("horas_desde_ultimo_ok")
            if horas is None:
                itens.append(
                    _montar(
                        "backup-nunca",
                        "atencao",
                        "sistema",
                        "Nenhum backup completo ainda",
                        "O sistema já tem dados que não podem ser perdidos e "
                        "nunca rodou um backup. Dispare um agora na Saúde do "
                        "sistema e deixe o agendamento das 03:00 assumir.",
                        acao_rotulo="Fazer backup agora",
                        acao_href="/dashboard/saude",
                    )
                )
            else:
                itens.append(
                    _montar(
                        "backup-atrasado",
                        "critico" if saude.get("erros_recentes") else "atencao",
                        "sistema",
                        f"Backup atrasado — último ok há {horas:.0f} h",
                        "O backup diário não completou dentro do esperado. "
                        "Verifique espaço em disco e o resultado dos últimos "
                        "backups na Saúde do sistema.",
                        acao_rotulo="Ver saúde do backup",
                        acao_href="/dashboard/saude",
                    )
                )
    except Exception:  # noqa: BLE001 — alerta de backup nunca derruba os demais
        pass

    # ---- Saúde do ambiente --------------------------------------------------
    if not settings.vault_master_key:
        itens.append(
            _montar(
                "vault-sem-chave",
                "critico",
                "sistema",
                "Cofre sem chave mestra configurada",
                "VAULT_MASTER_KEY vazia: certificados não podem ser gravados "
                "com segurança. Configure no .env e reinicie a API.",
                acao_rotulo="Ver diagnóstico",
                acao_href="/dashboard/configuracoes",
            )
        )
    try:
        livre = shutil.disk_usage(Path(settings.dados_dir)).free
        if livre < 500 * 1024 * 1024:
            itens.append(
                _montar(
                    "disco-cheio",
                    "critico",
                    "sistema",
                    "Pouco espaço em disco no volume de dados",
                    f"Restam {livre / 1024 / 1024:.0f} MB — XMLs e certificados "
                    f"novos podem não ser gravados.",
                    acao_rotulo="Ver diagnóstico",
                    acao_href="/dashboard/configuracoes",
                )
            )
    except OSError:
        pass

    itens.sort(key=lambda a: (_PESO_NIVEL.get(a.nivel, 9), a.categoria, a.titulo))
    return itens[:80]


@router.get("", response_model=AlertasResposta)
def listar_alertas(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Tudo que precisa de atenção, ordenado por gravidade."""
    itens = computar_alertas(db, escritorio_id)
    return AlertasResposta(
        total=len(itens),
        criticos=sum(1 for a in itens if a.nivel == "critico"),
        atencao=sum(1 for a in itens if a.nivel == "atencao"),
        infos=sum(1 for a in itens if a.nivel == "info"),
        itens=itens,
    )


@router.get("/contagem")
def contagem_alertas(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Só os números — para o sino da barra superior (leve)."""
    itens = computar_alertas(db, escritorio_id)
    return {
        "total": len(itens),
        "criticos": sum(1 for a in itens if a.nivel == "critico"),
        "atencao": sum(1 for a in itens if a.nivel == "atencao"),
    }


@router.post("/testar-webhook", response_model=TesteWebhookResposta)
def testar_webhook(
    admin: Usuario = Depends(requer_papel("admin")),
    db: Session = Depends(get_db),
):
    """Envia um alerta de teste ao webhook configurado (só admin)."""
    ok, detalhe = svc_webhook.disparar(
        {
            "id": "teste-manual",
            "nivel": "info",
            "categoria": "sistema",
            "titulo": "Teste do webhook Fluxa",
            "detalhe": "Se esta mensagem chegou, os alertas externos estão funcionando.",
            "empresa_razao_social": None,
            "acao_rotulo": "Abrir painel",
            "acao_href": "/dashboard/alertas",
        },
        escritorio_id=admin.escritorio_id,
    )
    auditoria.registrar(
        db, admin, "webhook_teste", detalhe=f"ok={ok} · {detalhe}",
    )
    db.commit()
    return TesteWebhookResposta(ok=ok, detalhe=detalhe)
