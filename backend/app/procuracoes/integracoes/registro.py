"""
Registro de fontes: resolve o nome configurado no adaptador concreto.

Adicionar uma fonte nova é registrar uma função construtora aqui. Nenhum
serviço precisa saber que SERPRO existe.

Sobre o Jettax 360: **não é integração remota neste produto**. Não existe
endpoint público documentado para a tela de procurações do painel, e a
decisão do produto é não manter adaptador "pronto para quando houver". A
lista do painel entra por importação (colagem/arquivo) nas rotas
`/importar-lista` e `/importar-planilha`, com o valor `jettax360` como
**procedência do dado** — ver `esquemas.FONTES_MANUAIS` e a precedência em
`sincronizacao.PRECEDENCIA`.
"""

from __future__ import annotations

import json
from typing import Callable

from sqlalchemy.orm import Session

from app.core.vault import SegredoIndecifravelError, decifrar_segredo
from app.procuracoes.integracoes.base import FonteNaoConfiguradaError, FonteProcuracoes
from app.procuracoes.integracoes.integra_contador import (
    BASE_DEMONSTRACAO,
    BASE_PRODUCAO,
    ClienteIntegraContador,
)
from app.procuracoes.modelos import CredencialIntegracao

#: Procedência de listas importadas do painel do Jettax (sem API, sem
#: credencial). Não é fonte remota — é rótulo de confiança na reconciliação.
FONTE_JETTAX = "jettax360"
FONTE_INTEGRA_CONTADOR = "integra_contador"
FONTE_PLANILHA = "planilha"

#: Integrações remotas — únicas que aceitam credencial, teste e sincronização.
FONTES_REMOTAS = (FONTE_INTEGRA_CONTADOR,)
FONTES_CONHECIDAS = (*FONTES_REMOTAS, FONTE_PLANILHA)

ROTULOS: dict[str, str] = {
    FONTE_JETTAX: "Jettax360",
    FONTE_INTEGRA_CONTADOR: "SERPRO Integra Contador (oficial)",
    FONTE_PLANILHA: "Planilha CSV",
}


def credencial(
    db: Session, escritorio_id: int, fonte: str
) -> CredencialIntegracao | None:
    return (
        db.query(CredencialIntegracao)
        .filter(
            CredencialIntegracao.escritorio_id == escritorio_id,
            CredencialIntegracao.fonte == fonte,
        )
        .first()
    )


def _opcoes(registro: CredencialIntegracao) -> dict:
    try:
        dados = json.loads(registro.opcoes_json or "{}")
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _segredo(texto_cifrado: str) -> str:
    if not texto_cifrado:
        return ""
    try:
        return decifrar_segredo(texto_cifrado)
    except SegredoIndecifravelError as exc:
        raise FonteNaoConfiguradaError(
            "A credencial gravada não pôde ser aberta com a chave atual do cofre. "
            "Regrave a credencial."
        ) from exc


def _construir_integra_contador(registro: CredencialIntegracao) -> FonteProcuracoes:
    opcoes = _opcoes(registro)
    ambiente = str(opcoes.get("ambiente") or "producao").lower()
    base = registro.base_url or (
        BASE_DEMONSTRACAO if ambiente == "demonstracao" else BASE_PRODUCAO
    )
    return ClienteIntegraContador(
        consumer_key=registro.identificador,
        consumer_secret=_segredo(registro.segredo_cifrado),
        contratante=str(opcoes.get("contratante") or ""),
        autor_pedido=str(opcoes.get("autor_pedido") or ""),
        base_url=base,
    )


_CONSTRUTORES: dict[str, Callable[[CredencialIntegracao], FonteProcuracoes]] = {
    FONTE_INTEGRA_CONTADOR: _construir_integra_contador,
}


def construir(db: Session, escritorio_id: int, fonte: str) -> FonteProcuracoes:
    """Instancia o adaptador configurado ou explica exatamente o que falta."""
    if fonte == FONTE_JETTAX:
        raise FonteNaoConfiguradaError(
            "O Jettax 360 não é integração por API neste produto: não existe "
            "endpoint público documentado para a tela de procurações. Traga a "
            "lista por 'Importar lista' na tela de Procurações — o dado entra "
            "com a mesma procedência e governança."
        )
    if fonte not in _CONSTRUTORES:
        raise FonteNaoConfiguradaError(
            f"Fonte '{fonte}' não é uma integração remota conhecida. "
            f"Disponíveis: {', '.join(FONTES_REMOTAS)}."
        )
    registro = credencial(db, escritorio_id, fonte)
    if registro is None or not registro.ativo:
        raise FonteNaoConfiguradaError(
            f"A integração {ROTULOS.get(fonte, fonte)} ainda não foi configurada."
        )
    return _CONSTRUTORES[fonte](registro)


def fontes_configuradas(db: Session, escritorio_id: int) -> list[str]:
    linhas = (
        db.query(CredencialIntegracao)
        .filter(
            CredencialIntegracao.escritorio_id == escritorio_id,
            CredencialIntegracao.ativo.is_(True),
        )
        .all()
    )
    return [linha.fonte for linha in linhas if linha.fonte in _CONSTRUTORES]
