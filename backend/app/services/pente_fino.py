"""
Pente-fino da competência + termômetro de fechamento.

Nenhum concorrente faz isto porque todos param na captura: trazem as notas
e listam. Aqui o sistema *pensa* sobre o mês — cruza a competência contra o
histórico do escritório e responde as perguntas que o contador faz à mão:

- "Falta nota?" → salto de numeração por emitente + termômetro de volume.
- "Tem coisa estranha?" → estreante, valor anômalo, horário atípico, sumido.
- "Posso fechar o mês?" → checklist + `pronta_para_fechar`.

Tudo é leitura: nenhum achado dispara consulta à SEFAZ.
"""

from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DocumentoFiscal, Empresa, TipoDocumentoFiscal
from app.schemas import (
    AchadoPenteFino,
    ItemChecklistFechamento,
    PenteFinoResposta,
    TermometroResposta,
    TermometroTipo,
)
from app.services.referencia import data_referencia_sql

_FUSO = ZoneInfo("America/Sao_Paulo")

_MESfiN = 6  # meses de histórico para mediana e anomalias
_MAX_ACHADOS_POR_CODIGO = 20
_MAX_ACHADOS_TOTAL = 100
_MIN_AMOSTRA_VALOR = 5  # notas do emitente no histórico para julgar valor
_DESVIOS_ANOMALIA = 3.0  # valor acima de média + 3σ é anômalo
_MIN_RECORRENCIA_SUMIDO = 3  # notas em 90 dias = emitente recorrente

_TIPOS = [TipoDocumentoFiscal.NFSE, TipoDocumentoFiscal.NFE, TipoDocumentoFiscal.CTE]


def _moeda(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _vezes(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",")


def _mes_anterior(ano: int, mes: int, voltas: int) -> tuple[int, int]:
    total = ano * 12 + (mes - 1) - voltas
    return total // 12, total % 12 + 1


def _limites_mes(ano: int, mes: int) -> tuple[date, date]:
    return date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1])


def _emissao_sp(doc: DocumentoFiscal) -> datetime | None:
    emissao = doc.data_emissao
    if emissao is None:
        return None
    if emissao.tzinfo is None:
        emissao = emissao.replace(tzinfo=_FUSO)
    return emissao.astimezone(_FUSO)


def _razoes(db: Session, escritorio_id: int, ids: list[int]) -> dict[int, str]:
    linhas = (
        db.query(Empresa.id, Empresa.razao_social)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.id.in_(ids))
        .all()
    )
    return {empresa_id: razao for empresa_id, razao in linhas}


def auditar_competencia(
    db: Session,
    escritorio_id: int,
    competencia: date,
    ids_empresas: list[int],
) -> PenteFinoResposta:
    """Roda todos os cruzamentos do mês e monta checklist + achados."""
    inicio, fim = _limites_mes(competencia.year, competencia.month)
    rotulo = f"{competencia.month:02d}/{competencia.year}"
    resposta = PenteFinoResposta(competencia=rotulo)
    if not ids_empresas:
        return resposta

    ref = data_referencia_sql()
    docs: list[DocumentoFiscal] = (
        db.query(DocumentoFiscal)
        .join(Empresa, Empresa.id == DocumentoFiscal.empresa_id)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            DocumentoFiscal.empresa_id.in_(ids_empresas),
            ref >= inicio,
            ref <= fim,
        )
        .order_by(DocumentoFiscal.data_emissao.asc(), DocumentoFiscal.id.asc())
        .all()
    )
    resposta.total_documentos = len(docs)
    razoes = _razoes(db, escritorio_id, ids_empresas)

    achados: list[AchadoPenteFino] = []
    achados.extend(_achados_xml(docs, razoes))
    achados.extend(_achados_salto_sequencia(docs, razoes))
    achados.extend(_achados_estreantes(db, escritorio_id, ids_empresas, inicio, docs, razoes))
    achados.extend(_achados_valor_anomalo(db, escritorio_id, ids_empresas, inicio, docs, razoes))
    achados.extend(_achados_horario_atipico(docs, razoes))
    achados.extend(_achados_emitentes_sumidos(db, escritorio_id, ids_empresas, inicio, fim, razoes))
    achados.extend(_achados_canceladas(docs, razoes))
    resposta.achados = achados[:_MAX_ACHADOS_TOTAL]

    por_codigo: dict[str, int] = defaultdict(int)
    for achado in resposta.achados:
        por_codigo[achado.codigo] += 1
    resposta.checklist = _checklist(por_codigo, len(docs))
    resposta.pronta_para_fechar = all(item.ok for item in resposta.checklist)
    return resposta


def _achados_xml(
    docs: list[DocumentoFiscal], razoes: dict[int, str]
) -> list[AchadoPenteFino]:
    saidas: list[AchadoPenteFino] = []
    for doc in docs:
        if (doc.manifestacao_cstat or "") == "596":
            saidas.append(
                AchadoPenteFino(
                    codigo="erro_596",
                    severidade="alta",
                    titulo=f"Nota {doc.numero or 's/n'} travada no erro 596",
                    detalhe=(
                        "A SEFAZ recusou a Ciência por decurso de prazo. Só uma "
                        "manifestação conclusiva (confirmação/desconhecimento) "
                        "libera o XML completo."
                    ),
                    documento_id=doc.id,
                    documento_numero=doc.numero,
                    empresa_id=doc.empresa_id,
                    empresa_razao=razoes.get(doc.empresa_id),
                    emitente_nome=doc.emitente_nome,
                )
            )
        elif (doc.leiaute or "") in {"resumo", "metadados"}:
            saidas.append(
                AchadoPenteFino(
                    codigo="sem_xml",
                    severidade="media",
                    titulo=f"Nota {doc.numero or 's/n'} ainda só em resumo",
                    detalhe=(
                        "O resumo não escritura. O Fluxa busca o XML sozinho; "
                        "use “Buscar XMLs completos” para adiantar."
                    ),
                    documento_id=doc.id,
                    documento_numero=doc.numero,
                    empresa_id=doc.empresa_id,
                    empresa_razao=razoes.get(doc.empresa_id),
                    emitente_nome=doc.emitente_nome,
                )
            )
    return saidas[:_MAX_ACHADOS_POR_CODIGO]


def _achados_salto_sequencia(
    docs: list[DocumentoFiscal], razoes: dict[int, str]
) -> list[AchadoPenteFino]:
    # Numeração é sequencial por emitente+série: um buraco no meio quase
    # sempre é nota que existe e não está no acervo.
    grupos: dict[tuple, list[tuple[int, DocumentoFiscal]]] = defaultdict(list)
    for doc in docs:
        try:
            numero = int(str(doc.numero or "").strip())
        except (TypeError, ValueError):
            continue
        chave = (doc.empresa_id, str(doc.tipo), doc.emitente_documento or "", doc.serie or "")
        grupos[chave].append((numero, doc))
    saidas: list[AchadoPenteFino] = []
    for (empresa_id, _tipo, _emit_doc, serie), itens in sorted(grupos.items()):
        ordenados = sorted({numero: doc for numero, doc in itens}.items())
        for (anterior, _doc_ant), (atual, doc_atual) in zip(ordenados, ordenados[1:]):
            if atual - anterior <= 1:
                continue
            faltantes = f"{anterior + 1}" if atual - anterior == 2 else f"{anterior + 1}–{atual - 1}"
            saidas.append(
                AchadoPenteFino(
                    codigo="salto_sequencia",
                    severidade="media",
                    titulo=f"Faltam as notas {faltantes} de {doc_atual.emitente_nome or 'emitente sem nome'}",
                    detalhe=(
                        f"A numeração pulou de {anterior} para {atual}"
                        + (f" (série {serie})" if serie else "")
                        + ". Pode ser nota ainda não capturada — ou emitida para outro CNPJ."
                    ),
                    documento_id=doc_atual.id,
                    documento_numero=doc_atual.numero,
                    empresa_id=empresa_id,
                    empresa_razao=razoes.get(empresa_id),
                    emitente_nome=doc_atual.emitente_nome,
                )
            )
            if len(saidas) >= _MAX_ACHADOS_POR_CODIGO:
                return saidas
    return saidas


def _achados_estreantes(
    db: Session,
    escritorio_id: int,
    ids_empresas: list[int],
    inicio: date,
    docs: list[DocumentoFiscal],
    razoes: dict[int, str],
) -> list[AchadoPenteFino]:
    conhecidos: set[tuple[int, str]] = {
        (empresa_id, emitente or "")
        for empresa_id, emitente in db.query(
            DocumentoFiscal.empresa_id, DocumentoFiscal.emitente_documento
        )
        .join(Empresa, Empresa.id == DocumentoFiscal.empresa_id)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            DocumentoFiscal.empresa_id.in_(ids_empresas),
            DocumentoFiscal.data_emissao < datetime(inicio.year, inicio.month, 1),
        )
        .distinct()
        .all()
    }
    vistos: set[tuple[int, str]] = set()
    saidas: list[AchadoPenteFino] = []
    for doc in docs:
        chave = (doc.empresa_id, doc.emitente_documento or "")
        if not doc.emitente_documento or chave in conhecidos or chave in vistos:
            continue
        vistos.add(chave)
        saidas.append(
            AchadoPenteFino(
                codigo="emitente_estreante",
                severidade="baixa",
                titulo=f"Emitente novo: {doc.emitente_nome or doc.emitente_documento}",
                detalhe=(
                    "Primeira nota deste emitente no histórico. Vale conferir "
                    "se o fornecedor é esperado antes de escriturar."
                ),
                documento_id=doc.id,
                documento_numero=doc.numero,
                empresa_id=doc.empresa_id,
                empresa_razao=razoes.get(doc.empresa_id),
                emitente_nome=doc.emitente_nome,
            )
        )
        if len(saidas) >= _MAX_ACHADOS_POR_CODIGO:
            break
    return saidas


def _achados_valor_anomalo(
    db: Session,
    escritorio_id: int,
    ids_empresas: list[int],
    inicio: date,
    docs: list[DocumentoFiscal],
    razoes: dict[int, str],
) -> list[AchadoPenteFino]:
    historico: dict[tuple, list[float]] = defaultdict(list)
    cortes: list[date] = []
    for voltas in range(1, _MESfiN + 1):
        ano, mes = _mes_anterior(inicio.year, inicio.month, voltas)
        cortes.append(date(ano, mes, 1))
    piso = min(cortes)
    linhas = (
        db.query(
            DocumentoFiscal.empresa_id,
            DocumentoFiscal.tipo,
            DocumentoFiscal.emitente_documento,
            DocumentoFiscal.valor_total,
        )
        .join(Empresa, Empresa.id == DocumentoFiscal.empresa_id)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            DocumentoFiscal.empresa_id.in_(ids_empresas),
            data_referencia_sql() >= piso,
            data_referencia_sql() < inicio,
        )
        .all()
    )
    for empresa_id, tipo, emitente, valor in linhas:
        if valor is None:
            continue
        historico[(empresa_id, str(tipo), emitente or "")].append(float(valor))
    saidas: list[AchadoPenteFino] = []
    for doc in docs:
        if doc.valor_total is None or float(doc.valor_total) <= 0:
            continue
        amostra = historico.get((doc.empresa_id, str(doc.tipo), doc.emitente_documento or ""), [])
        if len(amostra) < _MIN_AMOSTRA_VALOR:
            continue
        media = statistics.fmean(amostra)
        desvio = statistics.pstdev(amostra)
        limite = media + _DESVIOS_ANOMALIA * desvio if desvio > 0 else media * 2
        valor = float(doc.valor_total)
        if valor <= limite:
            continue
        vezes = valor / media if media > 0 else 0
        saidas.append(
            AchadoPenteFino(
                codigo="valor_anomalo",
                severidade="media",
                titulo=f"Nota {doc.numero or 's/n'} de {_moeda(valor)} destoa do emitente",
                detalhe=(
                    f"Média histórica de {doc.emitente_nome or 'este emitente'}: "
                    f"{_moeda(media)} em {len(amostra)} notas "
                    f"({_vezes(vezes)}× acima). Confira digitação e CFOP."
                ),
                documento_id=doc.id,
                documento_numero=doc.numero,
                empresa_id=doc.empresa_id,
                empresa_razao=razoes.get(doc.empresa_id),
                emitente_nome=doc.emitente_nome,
            )
        )
        if len(saidas) >= _MAX_ACHADOS_POR_CODIGO:
            break
    return saidas


def _achados_horario_atipico(
    docs: list[DocumentoFiscal], razoes: dict[int, str]
) -> list[AchadoPenteFino]:
    saidas: list[AchadoPenteFino] = []
    for doc in docs:
        emissao = _emissao_sp(doc)
        if emissao is None:
            continue
        domingo = emissao.weekday() == 6
        madrugada = 0 <= emissao.hour <= 5
        if not (domingo or madrugada):
            continue
        motivo = "domingo" if domingo and not madrugada else "madrugada" if madrugada and not domingo else "domingo de madrugada"
        saidas.append(
            AchadoPenteFino(
                codigo="horario_atipico",
                severidade="baixa",
                titulo=f"Nota {doc.numero or 's/n'} emitida {motivo} ({emissao:%d/%m %H:%M})",
                detalhe=(
                    "Emissão fora do horário comercial. Na maioria é plantão "
                    "legítimo — mas é também o horário clássico de nota fria."
                ),
                documento_id=doc.id,
                documento_numero=doc.numero,
                empresa_id=doc.empresa_id,
                empresa_razao=razoes.get(doc.empresa_id),
                emitente_nome=doc.emitente_nome,
            )
        )
        if len(saidas) >= _MAX_ACHADOS_POR_CODIGO:
            break
    return saidas


def _achados_emitentes_sumidos(
    db: Session,
    escritorio_id: int,
    ids_empresas: list[int],
    inicio: date,
    fim: date,
    razoes: dict[int, str],
) -> list[AchadoPenteFino]:
    # Recorrente = 3+ notas nos 90 dias antes do mês e zero dentro do mês.
    from datetime import timedelta

    piso = inicio - timedelta(days=90)
    ref = data_referencia_sql()
    recentes = (
        db.query(
            DocumentoFiscal.empresa_id,
            DocumentoFiscal.emitente_documento,
            func.max(DocumentoFiscal.emitente_nome),
            func.count(DocumentoFiscal.id),
        )
        .join(Empresa, Empresa.id == DocumentoFiscal.empresa_id)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            DocumentoFiscal.empresa_id.in_(ids_empresas),
            DocumentoFiscal.emitente_documento.isnot(None),
            ref >= piso,
            ref < inicio,
        )
        .group_by(DocumentoFiscal.empresa_id, DocumentoFiscal.emitente_documento)
        .having(func.count(DocumentoFiscal.id) >= _MIN_RECORRENCIA_SUMIDO)
        .all()
    )
    if not recentes:
        return []
    no_mes = {
        (empresa_id, emitente or "")
        for empresa_id, emitente in db.query(
            DocumentoFiscal.empresa_id, DocumentoFiscal.emitente_documento
        )
        .join(Empresa, Empresa.id == DocumentoFiscal.empresa_id)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            DocumentoFiscal.empresa_id.in_(ids_empresas),
            ref >= inicio,
            ref <= fim,
            DocumentoFiscal.emitente_documento.isnot(None),
        )
        .distinct()
        .all()
    }
    saidas: list[AchadoPenteFino] = []
    for empresa_id, emitente, nome, quantidade in sorted(recentes):
        if (empresa_id, emitente or "") in no_mes:
            continue
        saidas.append(
            AchadoPenteFino(
                codigo="emitente_sumido",
                severidade="media",
                titulo=f"{nome or emitente} sumiu neste mês",
                detalhe=(
                    f"Emitia com frequência ({quantidade} notas nos 90 dias "
                    f"anteriores) e não aparece na competência. Nota perdida, "
                    f"atraso do fornecedor ou fim do contrato?"
                ),
                empresa_id=empresa_id,
                empresa_razao=razoes.get(empresa_id),
                emitente_nome=nome,
            )
        )
        if len(saidas) >= _MAX_ACHADOS_POR_CODIGO:
            break
    return saidas


def _achados_canceladas(
    docs: list[DocumentoFiscal], razoes: dict[int, str]
) -> list[AchadoPenteFino]:
    canceladas = [doc for doc in docs if str(doc.status) == "cancelada"]
    if not canceladas:
        return []
    if len(canceladas) == 1:
        doc = canceladas[0]
        return [
            AchadoPenteFino(
                codigo="cancelada_no_mes",
                severidade="baixa",
                titulo=f"Nota {doc.numero or 's/n'} cancelada no mês",
                detalhe=doc.motivo_cancelamento or "Cancelamento registrado na SEFAZ.",
                documento_id=doc.id,
                documento_numero=doc.numero,
                empresa_id=doc.empresa_id,
                empresa_razao=razoes.get(doc.empresa_id),
                emitente_nome=doc.emitente_nome,
            )
        ]
    return [
        AchadoPenteFino(
            codigo="cancelada_no_mes",
            severidade="baixa",
            titulo=f"{len(canceladas)} notas canceladas no mês",
            detalhe="Canceladas não entram na escrituração — o pente-fino só registra.",
        )
    ]


def _checklist(por_codigo: dict[str, int], total: int) -> list[ItemChecklistFechamento]:
    sem_xml = por_codigo.get("sem_xml", 0) + por_codigo.get("erro_596", 0)
    saltos = por_codigo.get("salto_sequencia", 0)
    anomalias = por_codigo.get("valor_anomalo", 0) + por_codigo.get("horario_atipico", 0)
    sumidos = por_codigo.get("emitente_sumido", 0)
    return [
        ItemChecklistFechamento(
            codigo="xmls_completos",
            rotulo="XMLs completos",
            ok=sem_xml == 0,
            detalhe="Todas as notas têm XML completo." if sem_xml == 0 else f"{sem_xml} sem XML completo.",
        ),
        ItemChecklistFechamento(
            codigo="sequencia_sem_saltos",
            rotulo="Numeração sem saltos",
            ok=saltos == 0,
            detalhe="Nenhum buraco na sequência por emitente." if saltos == 0 else f"{saltos} salto(s) de numeração.",
        ),
        ItemChecklistFechamento(
            codigo="sem_anomalias",
            rotulo="Valores e horários coerentes",
            ok=anomalias == 0,
            detalhe="Nada fora do padrão histórico." if anomalias == 0 else f"{anomalias} anomalia(s) para conferir.",
        ),
        ItemChecklistFechamento(
            codigo="emitentes_presentes",
            rotulo="Emitentes recorrentes presentes",
            ok=sumidos == 0,
            detalhe="Nenhum fornecedor frequente sumiu." if sumidos == 0 else f"{sumidos} emitente(s) sumido(s).",
        ),
        ItemChecklistFechamento(
            codigo="movimento_registrado",
            rotulo="Mês com movimento",
            ok=total > 0,
            detalhe=f"{total} documento(s) no mês." if total > 0 else "Nenhum documento capturado no mês.",
        ),
    ]


def termometro(
    db: Session,
    escritorio_id: int,
    competencia: date,
    ids_empresas: list[int],
    hoje: date | None = None,
) -> TermometroResposta:
    """
    “Quantas notas este mês deveria ter?” — mediana dos últimos 6 meses por
    tipo, proporcional ao dia corrido quando o mês ainda está aberto.
    """
    inicio, fim = _limites_mes(competencia.year, competencia.month)
    dias_no_mes = fim.day
    hoje = hoje or datetime.now(_FUSO).date()
    dia = min(max(hoje.day if (hoje.year, hoje.month) == (inicio.year, inicio.month) else dias_no_mes, 1), dias_no_mes)
    rotulo = f"{competencia.month:02d}/{competencia.year}"
    resposta = TermometroResposta(competencia=rotulo, dia=dia, dias_no_mes=dias_no_mes)
    if not ids_empresas:
        return resposta

    ref = data_referencia_sql()
    base = (
        db.query(DocumentoFiscal)
        .join(Empresa, Empresa.id == DocumentoFiscal.empresa_id)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            DocumentoFiscal.empresa_id.in_(ids_empresas),
        )
    )
    tipos: list[TermometroTipo] = []
    for tipo in _TIPOS:
        capturadas = base.filter(DocumentoFiscal.tipo == tipo, ref >= inicio, ref <= fim).count()
        serie: list[int] = []
        for voltas in range(1, _MESfiN + 1):
            ano, mes = _mes_anterior(inicio.year, inicio.month, voltas)
            ini, fim_hist = _limites_mes(ano, mes)
            serie.append(
                base.filter(DocumentoFiscal.tipo == tipo, ref >= ini, ref <= fim_hist).count()
            )
        serie = [valor for valor in serie if valor > 0]
        item = TermometroTipo(tipo=tipo.value, capturadas=capturadas)
        if serie:
            mediana = statistics.median(serie)
            fator = dia / dias_no_mes
            minimo = min(serie) * fator
            maximo = max(serie) * fator
            item.mediana = round(mediana * fator, 1)
            item.esperadas_min = int(minimo)
            item.esperadas_max = max(int(round(maximo)), item.esperadas_min)
            item.percentual = round(capturadas / (mediana * fator) * 100, 1) if mediana * fator > 0 else 0
            if capturadas < minimo:
                item.estado = "abaixo"
            elif capturadas > maximo:
                item.estado = "acima"
            else:
                item.estado = "no_ritmo"
        tipos.append(item)
    resposta.tipos = tipos
    resposta.total_capturadas = sum(item.capturadas for item in tipos)
    return resposta
