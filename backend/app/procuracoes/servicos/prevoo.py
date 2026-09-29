"""
Pré-voo do lote: tudo que pode ser descoberto **antes** de abrir o primeiro
navegador.

O problema que este módulo resolve é de economia de atenção humana. Sem ele, um
lote de 137 empresas descobre no cliente 57 que o CNPJ do outorgado está errado
— e as 56 sessões anteriores, cada uma com certificado, CAPTCHA e 2FA, foram
desperdiçadas. Pior: algumas já viraram outorga assinada, que é ato jurídico e
não se desfaz com Ctrl+Z.

Três propriedades inegociáveis:

1. **Somente leitura.** Nada aqui cria job, altera autorização, grava evento ou
   toca o portal. Rodar o pré-voo duas vezes seguidas produz o mesmo resultado
   e nenhum efeito. É o que permite oferecê-lo como "conferir antes" sem medo.
2. **Mesmas regras da fila.** As checagens espelham `fila.criar_job` — se o
   pré-voo diz APTO e a fila recusa, o pré-voo está mentindo e perde a razão de
   existir. Por isso ele reusa `cfg.montar_plano` e
   `certificados.selecionar_para_documento` em vez de reimplementar o critério.
3. **Distingue "bloqueado" de "nada a fazer".** Uma empresa que já tem
   autorização ativa não é um problema a resolver: é trabalho que não precisa
   ser feito. Misturar as duas coisas num único contador de "erros" faz o
   operador caçar fantasma.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.documentos import normalizar_documento, validar_documento
from app.core.mascaramento import mascarar_documento, mascarar_serial
from app.models import Empresa
from app.procuracoes.estados import (
    ModoOperacao,
    StatusAutorizacao,
    TipoCertificado,
    avaliar_modo,
)
from app.procuracoes.modelos import Agente, Autorizacao, ProcuracaoConfiguracao
from app.procuracoes.servicos import agentes as srv_agentes
from app.procuracoes.servicos import certificados as srv_certificados
from app.procuracoes.servicos import configuracao as cfg
from app.procuracoes.servicos import fila as srv_fila


class Situacao(str, enum.Enum):
    """Veredito de uma linha ou do lote inteiro."""

    #: Pode entrar na fila agora.
    APTO = "apto"
    #: Entra, mas com ressalva que o operador precisa ver.
    ATENCAO = "atencao"
    #: Não entra. Falta algo que só uma pessoa resolve fora do fluxo.
    BLOQUEADO = "bloqueado"
    #: Não há trabalho a fazer (autorização ativa e fora da renovação).
    DISPENSADO = "dispensado"


_GRAVIDADE = {
    Situacao.DISPENSADO: 0,
    Situacao.APTO: 1,
    Situacao.ATENCAO: 2,
    Situacao.BLOQUEADO: 3,
}


@dataclass(frozen=True)
class Achado:
    """Uma constatação do pré-voo, legível por máquina e por gente."""

    codigo: str
    nivel: Situacao
    mensagem: str
    acao: str = ""

    def para_json(self) -> dict:
        return {
            "codigo": self.codigo,
            "nivel": self.nivel.value,
            "mensagem": self.mensagem,
            "acao": self.acao,
        }


@dataclass
class LinhaPrevoo:
    """Resultado do pré-voo para uma empresa."""

    empresa_id: int
    razao_social: str
    documento: str
    situacao: Situacao
    achados: list[Achado] = field(default_factory=list)
    certificado: str = ""
    certificado_valido_ate: date | None = None
    vigencia_prevista: date | None = None

    def para_json(self) -> dict:
        return {
            "empresa_id": self.empresa_id,
            "razao_social": self.razao_social,
            # Mascarado: este relatório é exportado e circula por e-mail.
            "documento": mascarar_documento(self.documento),
            "situacao": self.situacao.value,
            "certificado": self.certificado,
            "certificado_valido_ate": (
                self.certificado_valido_ate.isoformat()
                if self.certificado_valido_ate
                else None
            ),
            "vigencia_prevista": (
                self.vigencia_prevista.isoformat() if self.vigencia_prevista else None
            ),
            "achados": [a.para_json() for a in self.achados],
        }


@dataclass
class RelatorioPrevoo:
    """Pré-voo do lote inteiro: ambiente + uma linha por empresa."""

    ambiente: list[Achado] = field(default_factory=list)
    linhas: list[LinhaPrevoo] = field(default_factory=list)
    gerado_em: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def bloqueio_de_ambiente(self) -> bool:
        """Problema de configuração que impede o lote inteiro."""
        return any(a.nivel is Situacao.BLOQUEADO for a in self.ambiente)

    @property
    def pode_iniciar(self) -> bool:
        """Só faz sentido iniciar se o ambiente está ok e há ao menos 1 apto."""
        if self.bloqueio_de_ambiente:
            return False
        return self.contagem()["apto"] + self.contagem()["atencao"] > 0

    def contagem(self) -> dict[str, int]:
        base = {situacao.value: 0 for situacao in Situacao}
        for linha in self.linhas:
            base[linha.situacao.value] += 1
        return base

    def por_codigo(self) -> dict[str, int]:
        """Quantas empresas por motivo — é o que vira plano de ação."""
        contagem: dict[str, int] = {}
        for linha in self.linhas:
            for achado in linha.achados:
                if achado.nivel in (Situacao.BLOQUEADO, Situacao.ATENCAO):
                    contagem[achado.codigo] = contagem.get(achado.codigo, 0) + 1
        return dict(sorted(contagem.items(), key=lambda item: -item[1]))

    def para_json(self) -> dict:
        return {
            "gerado_em": self.gerado_em.isoformat(),
            "pode_iniciar": self.pode_iniciar,
            "bloqueio_de_ambiente": self.bloqueio_de_ambiente,
            "ambiente": [a.para_json() for a in self.ambiente],
            "contagem": self.contagem(),
            "por_codigo": self.por_codigo(),
            "linhas": [linha.para_json() for linha in self.linhas],
        }


# ---------------------------------------------------------------------------
# Verificações de ambiente (uma vez por lote)
# ---------------------------------------------------------------------------


def verificar_ambiente(db: Session, escritorio_id: int) -> list[Achado]:
    """Configuração do escritório e capacidade de execução."""
    achados: list[Achado] = []
    config = cfg.obter_configuracao(db, escritorio_id)

    achados.extend(_verificar_outorgado(config))
    achados.extend(_verificar_modelo(db, escritorio_id))
    achados.extend(_verificar_politica(config))
    achados.extend(_verificar_estacoes(db, escritorio_id, config))

    if not achados:
        achados.append(
            Achado("AMBIENTE_OK", Situacao.APTO, "Configuração do escritório validada.")
        )
    return achados


def _verificar_outorgado(config: ProcuracaoConfiguracao) -> list[Achado]:
    documento = (config.outorgado_documento or "").strip()
    if not documento:
        return [
            Achado(
                "OUTORGADO_AUSENTE",
                Situacao.BLOQUEADO,
                "O CNPJ/CPF da contabilidade (outorgado) não está configurado.",
                "Procurações → Configurar → Dados do escritório.",
            )
        ]
    if not validar_documento(documento):
        return [
            Achado(
                "OUTORGADO_INVALIDO",
                Situacao.BLOQUEADO,
                f"O documento do outorgado ({mascarar_documento(documento)}) é inválido.",
                "Corrija o CNPJ/CPF da contabilidade antes de iniciar o lote.",
            )
        ]
    if not (config.outorgado_nome or "").strip():
        return [
            Achado(
                "OUTORGADO_SEM_NOME",
                Situacao.ATENCAO,
                "O outorgado não tem nome cadastrado.",
                "Sem o nome, a conferência na tela de revisão fica fraca. Preencha.",
            )
        ]
    return []


def _verificar_modelo(db: Session, escritorio_id: int) -> list[Achado]:
    """O modelo tem que produzir um plano concreto — aqui, não na frente do cliente."""
    try:
        plano = cfg.montar_plano(db, escritorio_id)
    except ValueError as exc:
        return [
            Achado(
                "MODELO_INVALIDO",
                Situacao.BLOQUEADO,
                str(exc),
                "Procurações → Modelos: revise os serviços marcados.",
            )
        ]

    achados: list[Achado] = []
    if plano.vigencia_ate <= date.today():
        achados.append(
            Achado(
                "VIGENCIA_INVALIDA",
                Situacao.BLOQUEADO,
                f"A vigência calculada ({plano.vigencia_ate.isoformat()}) não é futura.",
                "Revise a vigência do modelo.",
            )
        )
    return achados


def _verificar_politica(config: ProcuracaoConfiguracao) -> list[Achado]:
    """A política de conformidade decide o modo antes de qualquer execução."""
    avaliacao = avaliar_modo(
        cfg.modo_padrao(config),
        autorizacao_formal_rfb=bool(config.autorizacao_formal_rfb),
    )
    if avaliacao.modo_efetivo is ModoOperacao.ASSISTIDO and not avaliacao.permitido:
        return [
            Achado(
                "MODO_AJUSTADO",
                Situacao.ATENCAO,
                avaliacao.motivo,
                "O lote seguirá em modo assistido.",
            )
        ]
    return []


def _verificar_estacoes(
    db: Session, escritorio_id: int, config: ProcuracaoConfiguracao
) -> list[Achado]:
    """Sem estação online o lote entra na fila e não sai do lugar."""
    estacoes = (
        db.query(Agente)
        .filter(Agente.escritorio_id == escritorio_id, Agente.ativo.is_(True))
        .all()
    )
    tolerancia = config.heartbeat_tolerancia_segundos or 120
    disponiveis = [
        agente
        for agente in estacoes
        if srv_agentes.situacao(agente, tolerancia) in ("online", "processando")
    ]

    if not estacoes:
        return [
            Achado(
                "SEM_ESTACAO",
                Situacao.ATENCAO,
                "Nenhuma estação Windows está matriculada.",
                "Os jobs ficarão na fila até uma estação assumir. "
                "Instale o Cajuru Agent na máquina que tem os certificados.",
            )
        ]
    if not disponiveis:
        return [
            Achado(
                "ESTACAO_OFFLINE",
                Situacao.ATENCAO,
                f"As {len(estacoes)} estações matriculadas estão offline.",
                "Abra o Cajuru Agent na estação antes de iniciar o lote.",
            )
        ]

    if config.assinador_exigido:
        aptas = [a for a in disponiveis if a.assinador_ok]
        if not aptas:
            return [
                Achado(
                    "ASSINADOR_INDISPONIVEL",
                    Situacao.ATENCAO,
                    "Nenhuma estação online reportou o Assinador SERPRO apto.",
                    "Rode `cajuru-agent diagnostico` na estação e resolva as falhas.",
                )
            ]
    return []


# ---------------------------------------------------------------------------
# Verificação por empresa
# ---------------------------------------------------------------------------


def verificar_empresa(
    db: Session,
    escritorio_id: int,
    empresa: Empresa,
    *,
    config: ProcuracaoConfiguracao,
    outorgado: str,
    vigencia_prevista: date | None,
    hoje: date | None = None,
) -> LinhaPrevoo:
    """Pré-voo de uma empresa. Espelha as recusas de `fila.criar_job`."""
    hoje = hoje or date.today()
    linha = LinhaPrevoo(
        empresa_id=empresa.id,
        razao_social=empresa.razao_social,
        documento=empresa.cnpj_cpf or "",
        situacao=Situacao.APTO,
        vigencia_prevista=vigencia_prevista,
    )

    documento = normalizar_documento(empresa.cnpj_cpf or "") if empresa.cnpj_cpf else ""
    if not documento or not validar_documento(documento):
        linha.achados.append(
            Achado(
                "DOCUMENTO_INVALIDO",
                Situacao.BLOQUEADO,
                "O CNPJ/CPF da empresa é inválido ou está em branco.",
                "Corrija o cadastro da empresa.",
            )
        )
        return _consolidar(linha)

    # Outorgar para si mesmo não é uma operação que exista. Se os documentos
    # coincidem, é erro de cadastro — e o portal recusaria no passo 1, depois
    # de gastar uma sessão inteira com certificado.
    if documento == normalizar_documento(outorgado):
        linha.achados.append(
            Achado(
                "OUTORGA_PARA_SI",
                Situacao.BLOQUEADO,
                "A empresa e o outorgado têm o mesmo documento.",
                "Verifique se esta empresa é o próprio escritório e remova-a do lote.",
            )
        )
        return _consolidar(linha)

    linha.achados.extend(_verificar_autorizacao(db, escritorio_id, empresa, outorgado, config, hoje))
    linha.achados.extend(_verificar_job_ativo(db, escritorio_id, empresa))
    linha.achados.extend(_verificar_certificado(db, escritorio_id, documento, linha, hoje))

    return _consolidar(linha)


def _verificar_autorizacao(
    db: Session,
    escritorio_id: int,
    empresa: Empresa,
    outorgado: str,
    config: ProcuracaoConfiguracao,
    hoje: date,
) -> list[Achado]:
    autorizacao = (
        db.query(Autorizacao)
        .filter(
            Autorizacao.escritorio_id == escritorio_id,
            Autorizacao.empresa_id == empresa.id,
            Autorizacao.outorgado_documento == normalizar_documento(outorgado),
        )
        .first()
    )
    if autorizacao is None:
        return []

    situacao = autorizacao.situacao

    if situacao == StatusAutorizacao.ATIVA.value:
        if srv_fila._perto_de_vencer(autorizacao, config):
            dias = (
                (autorizacao.data_validade - hoje).days
                if autorizacao.data_validade
                else None
            )
            return [
                Achado(
                    "RENOVACAO",
                    Situacao.ATENCAO,
                    f"Autorização ativa vencendo{f' em {dias} dias' if dias is not None else ''}.",
                    "Será renovada — uma nova outorga substitui a atual.",
                )
            ]
        return [
            Achado(
                "JA_AUTORIZADA",
                Situacao.DISPENSADO,
                "A empresa já tem autorização ativa e fora da janela de renovação.",
                "Nada a fazer. Não entra no lote.",
            )
        ]

    if situacao in {
        StatusAutorizacao.EM_ANALISE.value,
        StatusAutorizacao.AGUARDANDO_ACEITE.value,
    }:
        prazo = autorizacao.prazo_aceite_ate
        if prazo and prazo < hoje:
            return [
                Achado(
                    "PRAZO_ACEITE_VENCIDO",
                    Situacao.ATENCAO,
                    f"O prazo de validação venceu em {prazo.isoformat()}.",
                    "A Receita cancela sozinha após 30 dias. Será necessária nova outorga.",
                )
            ]
        dias = (prazo - hoje).days if prazo else None
        return [
            Achado(
                "AGUARDA_ACEITE",
                Situacao.ATENCAO,
                "A outorga já foi feita; falta a contabilidade validar"
                + (f" (restam {dias} dias)." if dias is not None else "."),
                "O job entra direto na fase de aceite — não cria outorga duplicada.",
            )
        ]

    return []


def _verificar_job_ativo(db: Session, escritorio_id: int, empresa: Empresa) -> list[Achado]:
    existente = srv_fila.job_ativo_da_empresa(db, escritorio_id, empresa.id)
    if existente is None:
        return []
    return [
        Achado(
            "JOB_EM_ANDAMENTO",
            Situacao.ATENCAO,
            f"Já existe o job #{existente.id} em andamento ({existente.status}).",
            "Nada será duplicado; a empresa não entra de novo no lote.",
        )
    ]


def _verificar_certificado(
    db: Session,
    escritorio_id: int,
    documento: str,
    linha: LinhaPrevoo,
    hoje: date,
) -> list[Achado]:
    """Reusa a seleção determinística da fila — mesmo critério, sem efeito."""
    resultado = srv_certificados.selecionar_para_documento(
        db, escritorio_id, documento, tipo=TipoCertificado.CLIENTE
    )
    if not resultado.ok:
        return [
            Achado(
                (resultado.codigo_erro.value if resultado.codigo_erro else "CERTIFICADO_INDISPONIVEL").upper(),
                Situacao.BLOQUEADO,
                resultado.mensagem,
                "Importe ou corrija o A1 desta empresa na estação antes do lote.",
            )
        ]

    certificado = resultado.certificado
    linha.certificado = mascarar_serial(certificado.thumbprint)
    validade = certificado.valido_ate
    if validade is not None:
        linha.certificado_valido_ate = (
            validade.date() if isinstance(validade, datetime) else validade
        )

    achados: list[Achado] = []
    if linha.certificado_valido_ate:
        dias = (linha.certificado_valido_ate - hoje).days
        if dias <= 30:
            achados.append(
                Achado(
                    "CERTIFICADO_VENCENDO",
                    Situacao.ATENCAO,
                    f"O A1 desta empresa vence em {dias} dias.",
                    "Renove o certificado; um A1 que vence no meio do fluxo derruba a outorga.",
                )
            )
    return achados


def _consolidar(linha: LinhaPrevoo) -> LinhaPrevoo:
    """A situação da linha é o achado mais grave que ela tem."""
    if not linha.achados:
        linha.situacao = Situacao.APTO
        return linha
    linha.situacao = max(
        (achado.nivel for achado in linha.achados), key=lambda nivel: _GRAVIDADE[nivel]
    )
    return linha


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def executar(
    db: Session,
    escritorio_id: int,
    *,
    empresa_ids: list[int] | None = None,
    hoje: date | None = None,
) -> RelatorioPrevoo:
    """Pré-voo completo. Somente leitura, idempotente.

    `empresa_ids` restringe a um subconjunto — é o que permite ao operador
    conferir só as empresas que ele pretende colocar no lote de hoje.
    """
    hoje = hoje or date.today()
    relatorio = RelatorioPrevoo(ambiente=verificar_ambiente(db, escritorio_id))

    # Sem outorgado válido nem plano, verificar empresa a empresa só produz
    # ruído: todas falhariam pelo mesmo motivo já reportado no ambiente.
    if relatorio.bloqueio_de_ambiente:
        return relatorio

    config = cfg.obter_configuracao(db, escritorio_id)
    outorgado = (config.outorgado_documento or "").strip()
    try:
        vigencia = cfg.montar_plano(db, escritorio_id, inicio=hoje).vigencia_ate
    except ValueError:
        vigencia = None

    consulta = db.query(Empresa).filter(
        Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True)
    )
    if empresa_ids:
        consulta = consulta.filter(Empresa.id.in_(empresa_ids))

    for empresa in consulta.order_by(Empresa.razao_social).all():
        relatorio.linhas.append(
            verificar_empresa(
                db,
                escritorio_id,
                empresa,
                config=config,
                outorgado=outorgado,
                vigencia_prevista=vigencia,
                hoje=hoje,
            )
        )

    return relatorio
