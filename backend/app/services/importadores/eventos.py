"""
Classificação de eventos fiscais recebidos na distribuição de DFe.

O ADN e o SEFAZ misturam, no mesmo lote, documentos fiscais e EVENTOS
(cancelamento, carta de correção, etc.). Eventos não viram `DocumentoFiscal`,
mas o cancelamento precisa ser rastreado — antes este código descartava o
evento silenciosamente, sem aplicar nada, e o usuário não ficava sabendo que
a nota tinha sido cancelada (ou pior: o lote parecia "menor" e a importação
parava antes da hora).

Aqui a regra é: QUALQUER item que não é documento fiscal vira um
`EventoFiscal`. Se for cancelamento, é aplicado na nota correspondente
(ou guardado como pendente se a nota ainda não chegou). Se for outro evento
ou um formato não reconhecido, é contabilizado em `eventos_nao_reconhecidos`
— nunca some sem deixar rastro.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# Eventos de cancelamento confirmado (NFe/CT-e, leiaute nacional):
#   110111 = Cancelamento
#   110112 = Cancelamento por substituição (NFe)
TP_EVENTO_CANCELAMENTO = {"110111", "110112"}

# Strings que indicam cancelamento quando aparecem no tipo/descrição do item
_HINT_CANCELAMENTO = ("CANCEL", "CANCE", "CANC")
_HINT_EVENTO = ("EVENTO", "EVENT", "NFSEDFECANCELAMENTO")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _texto(elemento: ET.Element | None) -> str:
    return (elemento.text or "").strip() if elemento is not None else ""


def _primeiro(elemento: ET.Element, nome_local: str) -> ET.Element | None:
    for filho in elemento.iter():
        if _local(filho.tag) == nome_local:
            return filho
    return None


@dataclass
class EventoFiscal:
    """Um evento de distribuição que não é documento fiscal."""

    chave_acesso: str = ""
    nsu: str = "0"
    tipo_evento: str = "nao_reconhecido"  # "cancelamento" | "nao_reconhecido"
    motivo: str = ""
    data_evento: str = ""
    schema: str = ""
    xml: bytes = field(default=b"")

    @property
    def eh_cancelamento(self) -> bool:
        return self.tipo_evento == "cancelamento"


def classificar_evento_xml(
    xml_bytes: bytes,
    *,
    schema: str = "",
    tipo_hint: str = "",
    nsu: str = "",
    chave_hint: str = "",
) -> EventoFiscal | None:
    """
    Tenta interpretar `xml_bytes` como EVENTO fiscal.

    Retorna:
    - EventoFiscal(cancelamento) quando é um cancelamento confirmado;
    - EventoFiscal(nao_reconhecido) quando é um evento/XML que reconhecemos
      como não-documento mas não conseguimos aplicar (ex.: CC-e, resumo de
      evento, formato fora do leiaute);
    - None quando o XML parece um DOCUMENTO fiscal normal (o chamador então
      tenta convertê-lo em DocumentoBaixado).
    """
    hint = f"{tipo_hint or ''} {schema or ''}".upper()
    tipo_explicito_cancelamento = any(h in hint for h in _HINT_CANCELAMENTO)
    tipo_explicito_evento = any(h in hint for h in _HINT_EVENTO)

    try:
        raiz = ET.fromstring(xml_bytes)
    except ET.ParseError:
        # XML quebrado: não é documento. Se o ADN diz que é cancelamento,
        # devolvemos o evento com a chave do item do lote, sem deixar sumir.
        if tipo_explicito_cancelamento:
            return EventoFiscal(
                chave_acesso=chave_hint,
                nsu=nsu,
                tipo_evento="cancelamento",
                motivo="Cancelamento (XML ilegível)",
                schema=schema,
            )
        return None

    nome_raiz = _local(raiz.tag).lower()
    eh_evento = "evento" in nome_raiz or tipo_explicito_evento
    if not eh_evento:
        # Fallback: conteúdo de evento dentro de um XML que não se anuncia
        # como evento (alguns leiautes de NFS-e embutem no próprio DFe).
        desc = _texto(_primeiro(raiz, "descEvento"))
        tp = _texto(_primeiro(raiz, "tpEvento"))
        if desc or tp:
            eh_evento = True
    if not eh_evento:
        return None

    tp_evento = _texto(_primeiro(raiz, "tpEvento"))
    desc_evento = _texto(_primeiro(raiz, "descEvento"))
    cstat = _texto(_primeiro(raiz, "cStat"))
    motivo = _texto(_primeiro(raiz, "xJust")) or _texto(_primeiro(raiz, "xMotivo"))
    data = (
        _texto(_primeiro(raiz, "dhEvento"))
        or _texto(_primeiro(raiz, "dhEmi"))
        or _texto(_primeiro(raiz, "dEvento"))
    )

    chave = (
        _texto(_primeiro(raiz, "chNFe"))
        or _texto(_primeiro(raiz, "chCTe"))
        or _texto(_primeiro(raiz, "chaveAcesso"))
        or _texto(_primeiro(raiz, "chave"))
    )
    if not chave:
        # Alguns eventos usam o Id do próprio elemento (ex.: "ID110111...").
        id_el = _primeiro(raiz, "evento")
        if id_el is not None and id_el.get("Id"):
            chave = id_el.get("Id")[2:] if id_el.get("Id").upper().startswith("ID") else id_el.get("Id")
    if not chave:
        chave = chave_hint

    eh_cancelamento = (
        tipo_explicito_cancelamento
        or (tp_evento in TP_EVENTO_CANCELAMENTO)
        or (cstat == "135")
        or ("cancel" in desc_evento.lower())
        or ("cancel" in motivo.lower())
    )

    if eh_cancelamento:
        # Sem chave não há como aplicar o cancelamento: reportamos como
        # evento não reconhecido para o painel contar (nunca some).
        if not chave:
            return EventoFiscal(
                nsu=nsu,
                tipo_evento="nao_reconhecido",
                motivo=motivo or desc_evento or "Cancelamento sem chave de acesso",
                data_evento=data,
                schema=schema,
                xml=xml_bytes,
            )
        return EventoFiscal(
            chave_acesso=chave,
            nsu=nsu,
            tipo_evento="cancelamento",
            motivo=motivo or desc_evento or "Cancelamento",
            data_evento=data,
            schema=schema,
            xml=xml_bytes,
        )

    return EventoFiscal(
        chave_acesso=chave,
        nsu=nsu,
        tipo_evento="nao_reconhecido",
        motivo=desc_evento or f"Evento não reconhecido ({nome_raiz})",
        data_evento=data,
        schema=schema,
        xml=xml_bytes,
    )
