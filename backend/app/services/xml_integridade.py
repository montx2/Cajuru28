"""
O XML que está no disco é a NOTA ou só o resumo dela?

## Por que este módulo existe

O `DocumentoFiscal.leiaute` ("completo" / "resumo" / "metadados") é a única
coisa que o resto do sistema consulta para decidir se uma nota pode ser
exportada, se ainda precisa ser completada e se o download individual deve ser
bloqueado. Se ele mentir, tudo mente junto: o ZIP da contabilidade sai com um
`resNFe` (chave, emitente e valor — nada de item, ICMS ou total) rotulado como
"xml_completo = sim", e a nota sai da fila de complemento para sempre.

Foi exatamente o que aconteceu quando o `consChNFe` passou a devolver o resumo
para uma nota ainda não manifestada: o arquivo do resumo sobrescrevia o da nota
e o registro era marcado como "completo". Este módulo é a segunda linha de
defesa — confere o ARQUIVO contra o que o banco declara, e corrige o cadastro
quando eles discordam. A primeira linha é o importador, que agora só aceita a
nota inteira (`classificar_documento_dfe`).

## Como é barato

`procNFe` tem itens, totais, impostos e assinatura: nunca cabe em poucos KB.
`resNFe`/`protNFe` cabem. Então:

- arquivo grande ⇒ é a nota, sem abrir;
- arquivo pequeno ⇒ abre e classifica pelo conteúdo (nunca pelo nome do
  arquivo, que quem escolhe é a SEFAZ/portal e já veio errado antes).

Assim dá para varrer o acervo em acervo grande sem ler gigabytes, e o reparo é
idempotente: na segunda passada, nada divergente é encontrado.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from app.models import DocumentoFiscal, TipoDocumentoFiscal
from app.services.importadores._distribuicao_dfe import (
    LEIAUTE_COMPLETO,
    LEIAUTE_DESCONHECIDO,
    LEIAUTE_EVENTO,
    LEIAUTE_PROTOCOLO,
    LEIAUTE_RESUMO,
    classificar_documento_dfe,
)

log = logging.getLogger("notasflow.xml_integridade")

# Acima disto, o arquivo não é resumo/protocolo — evita abrir e parsear o
# acervo inteiro só para conferir. Um `resNFe` ocupa ~1 KB; um `protNFe`, ~2 KB.
TAMANHO_MAXIMO_SUSPEITO = 16 * 1024

# Leiautes que NÃO são a nota. Qualquer um deles num registro marcado como
# "completo" é divergência.
_NAO_E_NOTA = {LEIAUTE_RESUMO, LEIAUTE_PROTOCOLO, LEIAUTE_EVENTO, LEIAUTE_DESCONHECIDO}


def nao_e_a_nota(leiaute: str | None) -> bool:
    """O leiaute classificado é algo que não é o documento inteiro?"""
    return leiaute in _NAO_E_NOTA


def classificar_bytes(conteudo: bytes | None) -> str | None:
    """Classifica o que já está em memória (o ZIP lê o arquivo de qualquer jeito)."""
    if not conteudo:
        return None
    return classificar_documento_dfe(conteudo)


def leiaute_do_arquivo(caminho: str | None) -> str | None:
    """Classifica o XML em disco: `completo`, `resumo`, `protocolo`, `evento`…

    Devolve `None` quando o arquivo não existe ou não pôde ser lido — ausência
    de arquivo é outro problema (disco/backup), não uma mentira do cadastro, e
    quem chama não deve rebaixar a nota por causa disso.
    """
    caminho = (caminho or "").strip()
    if not caminho or not os.path.isfile(caminho):
        return None
    try:
        tamanho = os.path.getsize(caminho)
        if tamanho > TAMANHO_MAXIMO_SUSPEITO:
            return LEIAUTE_COMPLETO
        with open(caminho, "rb") as arquivo:
            conteudo = arquivo.read()
    except OSError:
        return None
    if not conteudo:
        return None
    return classificar_documento_dfe(conteudo)


def leiaute_real_divergente(documento: DocumentoFiscal) -> str | None:
    """Leiaute real do arquivo quando ele contradiz o cadastro — senão `None`.

    Só interessa o caso perigoso: o banco diz "completo" e o arquivo é um
    resumo/protocolo/evento. O contrário (banco diz "resumo", arquivo é a nota)
    é uma nota completa que continua na fila — quem promove é o worker, com os
    metadados; reescrever o cadastro aqui só criaria inconsistência.
    """
    if (documento.leiaute or "") != LEIAUTE_COMPLETO:
        return None
    real = leiaute_do_arquivo(documento.xml_path)
    if real is None:
        return None
    return real if real in _NAO_E_NOTA else None


def reconciliar(db: Session, documento: DocumentoFiscal) -> str | None:
    """Corrige o `leiaute` do registro que diz "completo" sem ter a nota.

    Devolve o novo leiaute quando corrigiu, `None` quando não havia o que
    corrigir. **Não** faz commit: quem chama decide quando confirmar (o painel
    pode estar no meio de outra transação).
    """
    real = leiaute_real_divergente(documento)
    if real is None:
        return None
    documento.leiaute = LEIAUTE_RESUMO
    log.warning(
        "Documento %s (%s) dizia 'completo', mas o arquivo é %s: voltou para a fila de XML completo.",
        documento.id,
        documento.chave_acesso,
        real,
    )
    return LEIAUTE_RESUMO


def rebaixar_divergentes(
    db: Session, *, empresa_id: int | None = None, limite: int = 500
) -> int:
    """Varre o acervo e devolve para `resumo` o que foi marcado como completo sem ser.

    Limitado por `limite` para não transformar o reparo num processo longo de
    startup: como ele é idempotente, chamadas seguintes continuam de onde a
    anterior parou (o que já está correto não é tocado de novo).
    """
    consulta = db.query(DocumentoFiscal).filter(
        DocumentoFiscal.leiaute == LEIAUTE_COMPLETO,
        DocumentoFiscal.tipo == TipoDocumentoFiscal.NFE,
    )
    if empresa_id is not None:
        consulta = consulta.filter(DocumentoFiscal.empresa_id == empresa_id)
    corrigidos = 0
    conferidos = 0
    for documento in consulta.order_by(DocumentoFiscal.id.desc()).limit(limite).all():
        conferidos += 1
        if reconciliar(db, documento) is not None:
            corrigidos += 1
    if corrigidos:
        db.commit()
        log.warning(
            "Reparo de leiaute: %d de %d documento(s) conferidos voltaram para 'resumo'.",
            corrigidos,
            conferidos,
        )
    return corrigidos
