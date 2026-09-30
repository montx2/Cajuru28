"""
Configuração do módulo e modelo (template) de autorização.

Regra do projeto: **nenhum valor operacional fica fixo no código**. Vigência,
serviços, retries, timeouts e limites vivem no banco, por escritório, e têm
defaults explícitos aqui — um lugar só para auditar "o que vale quando
ninguém configurou nada".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.procuracoes.estados import ModoOperacao
from app.procuracoes.modelos import (
    ModeloAutorizacao,
    ModeloAutorizacaoServico,
    ProcuracaoConfiguracao,
)

#: Nome do modelo criado no primeiro acesso. Editável na tela depois.
NOME_MODELO_PADRAO = "Padrão Cajuru"


def obter_configuracao(db: Session, escritorio_id: int) -> ProcuracaoConfiguracao:
    """Configuração do escritório, criando a linha padrão na primeira vez."""
    config = (
        db.query(ProcuracaoConfiguracao)
        .filter(ProcuracaoConfiguracao.escritorio_id == escritorio_id)
        .first()
    )
    if config is None:
        config = ProcuracaoConfiguracao(escritorio_id=escritorio_id)
        db.add(config)
        db.flush()
    return config


def obter_modelo_padrao(db: Session, escritorio_id: int) -> ModeloAutorizacao:
    """Modelo marcado como padrão; cria "Padrão Cajuru" se ainda não existir."""
    modelo = (
        db.query(ModeloAutorizacao)
        .filter(
            ModeloAutorizacao.escritorio_id == escritorio_id,
            ModeloAutorizacao.padrao.is_(True),
            ModeloAutorizacao.ativo.is_(True),
        )
        .order_by(ModeloAutorizacao.id)
        .first()
    )
    if modelo is not None:
        return modelo

    modelo = (
        db.query(ModeloAutorizacao)
        .filter(
            ModeloAutorizacao.escritorio_id == escritorio_id,
            ModeloAutorizacao.nome == NOME_MODELO_PADRAO,
        )
        .first()
    )
    if modelo is None:
        modelo = ModeloAutorizacao(
            escritorio_id=escritorio_id,
            nome=NOME_MODELO_PADRAO,
            descricao=(
                "Vigência de 5 anos (máximo admitido pelo portal) e todos os "
                "serviços, para não precisar refazer a autorização quando a "
                "Receita publicar um serviço novo."
            ),
            vigencia_meses=60,
            escopo_servicos="ALL",
            padrao=True,
            ativo=True,
        )
        db.add(modelo)
    modelo.padrao = True
    modelo.ativo = True
    db.flush()
    return modelo


def definir_modelo_padrao(db: Session, escritorio_id: int, modelo_id: int) -> ModeloAutorizacao:
    """Troca o padrão garantindo que exista exatamente um."""
    alvo = (
        db.query(ModeloAutorizacao)
        .filter(
            ModeloAutorizacao.id == modelo_id,
            ModeloAutorizacao.escritorio_id == escritorio_id,
        )
        .first()
    )
    if alvo is None:
        raise ValueError("Modelo de autorização não encontrado.")
    db.query(ModeloAutorizacao).filter(
        ModeloAutorizacao.escritorio_id == escritorio_id,
        ModeloAutorizacao.id != modelo_id,
    ).update({ModeloAutorizacao.padrao: False}, synchronize_session=False)
    alvo.padrao = True
    alvo.ativo = True
    db.flush()
    return alvo


@dataclass(frozen=True)
class PlanoAutorizacao:
    """O que exatamente será outorgado — congelado no job na criação."""

    vigencia_ate: date
    escopo_servicos: str
    servicos: tuple[dict[str, str], ...]
    modelo_id: int | None
    modelo_nome: str

    @property
    def servicos_json(self) -> str:
        return json.dumps(list(self.servicos), ensure_ascii=False)

    @property
    def todos_os_servicos(self) -> bool:
        return self.escopo_servicos == "ALL"


def _mais_cinco_anos(base: date) -> date:
    """Retorna a mesma data no quinto aniversário, inclusive em ano bissexto.

    A Receita trabalha com data de expiração, não com uma quantidade fixa de
    dias. Usar ``60 * 30,4375`` podia deslocar a validade em alguns meses e
    contrariava a configuração explícita de "exatamente 5 anos". Em 29/02,
    o último dia de fevereiro é o único aniversário representável.
    """
    try:
        return base.replace(year=base.year + 5)
    except ValueError:  # 29/02 → 28/02 no ano não bissexto
        return base.replace(year=base.year + 5, day=28)


def montar_plano(
    db: Session,
    escritorio_id: int,
    *,
    modelo: ModeloAutorizacao | None = None,
    inicio: date | None = None,
) -> PlanoAutorizacao:
    """Traduz o modelo em valores concretos, respeitando o teto legal.

    A vigência é limitada a 5 anos porque o portal recusa datas acima disso —
    deixar o operador submeter e ser recusado no passo 3 desperdiça uma
    sessão inteira com certificado. Quando o modelo padrão é de 60 meses, a
    data é o quinto aniversário do início, e não uma aproximação em dias.
    """
    modelo = modelo or obter_modelo_padrao(db, escritorio_id)
    base = inicio or date.today()
    meses = max(1, min(int(modelo.vigencia_meses or 60), 60))
    if meses == 60:
        vigencia = _mais_cinco_anos(base)
        teto = vigencia
    else:
        # Para modelos menores, mantém a conversão existente em dias. O
        # modelo padrão e o fluxo direto usam o ramo exato acima.
        vigencia = base + timedelta(days=int(meses * 30.4375))
        teto = _mais_cinco_anos(base)
    if vigencia > teto:
        vigencia = teto

    servicos: tuple[dict[str, str], ...] = ()
    escopo = (modelo.escopo_servicos or "ALL").upper()
    if escopo != "ALL":
        itens = (
            db.query(ModeloAutorizacaoServico)
            .filter(ModeloAutorizacaoServico.modelo_id == modelo.id)
            .order_by(ModeloAutorizacaoServico.ordem, ModeloAutorizacaoServico.id)
            .all()
        )
        servicos = tuple(
            {"codigo": item.codigo, "rotulo": item.rotulo or item.codigo}
            for item in itens
        )
        if not servicos:
            # Modelo "lista explícita" sem nenhum serviço é um erro de cadastro
            # que só apareceria na frente do cliente. Falha aqui.
            raise ValueError(
                f"O modelo '{modelo.nome}' está configurado para serviços específicos "
                "mas não tem nenhum serviço marcado."
            )

    return PlanoAutorizacao(
        vigencia_ate=vigencia,
        escopo_servicos=escopo,
        servicos=servicos,
        modelo_id=modelo.id,
        modelo_nome=modelo.nome,
    )


def modo_padrao(config: ProcuracaoConfiguracao) -> ModoOperacao:
    try:
        return ModoOperacao(config.modo_padrao)
    except ValueError:
        return ModoOperacao.ASSISTIDO
