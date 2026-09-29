"""
Configuração do módulo e modelo (template) de autorização.

Regra do projeto: **nenhum valor operacional fica fixo no código**. Vigência,
serviços, retries, timeouts e limites vivem no banco, por escritório, e têm
defaults explícitos aqui — um lugar só para auditar "o que vale quando
ninguém configurou nada".
"""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.procuracoes.estados import VIGENCIA_MAXIMA_MESES, ModoOperacao
from app.procuracoes.modelos import (
    ModeloAutorizacao,
    ModeloAutorizacaoServico,
    ProcuracaoConfiguracao,
)

#: Nome do modelo criado no primeiro acesso. Editável na tela depois.
NOME_MODELO_PADRAO = "Padrão Cajuru"

#: Vigência padrão em meses. Igual ao teto legal de 5 anos.
#:
#: A escolha é deliberada e vale a explicação, porque parece agressiva: cada
#: renovação custa uma sessão com certificado do cliente, CAPTCHA, 2FA e
#: assinatura — e um novo prazo de 30 dias para a contabilidade validar, que
#: se estourar cancela tudo. Pedir menos que o teto significa repetir esse
#: custo antes da hora, sem ganho nenhum: a autorização é revogável pelo
#: cliente a qualquer momento, então prazo curto não é uma proteção real.
VIGENCIA_PADRAO_MESES = VIGENCIA_MAXIMA_MESES


def _somar_meses(base: date, meses: int) -> date:
    """Soma meses em calendário real, ancorando no fim do mês quando preciso.

    Aritmética de calendário em vez de `timedelta(days=meses * 30.4375)`:
    a aproximação por dias erra até dois dias em 5 anos dependendo de quantos
    anos bissextos o intervalo abraça. Aqui isso importa, porque a data fica
    colada no teto legal — errar para cima é ter a autorização recusada pelo
    portal no último passo.

    O caso de borda é 31/01 + 1 mês: não existe 31/02, então o resultado é o
    último dia de fevereiro. `calendar.monthrange` resolve inclusive o ano
    bissexto.
    """
    total = base.month - 1 + meses
    ano = base.year + total // 12
    mes = total % 12 + 1
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, min(base.day, ultimo_dia))


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
            vigencia_meses=VIGENCIA_PADRAO_MESES,
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
    sessão inteira com certificado.
    """
    modelo = modelo or obter_modelo_padrao(db, escritorio_id)
    base = inicio or date.today()
    meses = max(1, min(int(modelo.vigencia_meses or VIGENCIA_PADRAO_MESES), VIGENCIA_MAXIMA_MESES))
    vigencia = _somar_meses(base, meses)

    # Margem de 1 dia contra o teto legal. O portal recusa data **acima** de
    # 5 anos; cair exatamente no limite depende de como o servidor arredonda
    # o fuso na validação, e ser recusado no passo 3 desperdiça uma sessão
    # inteira com certificado já autenticado. Um dia a menos custa nada.
    teto = _somar_meses(base, VIGENCIA_MAXIMA_MESES) - timedelta(days=1)
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
