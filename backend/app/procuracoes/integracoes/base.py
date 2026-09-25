"""
Contrato das fontes de situação de procuração.

Uma fonte responde uma pergunta só: *para cada CNPJ da carteira, existe
autorização de acesso para a contabilidade, com que validade e que serviços?*

Todo adaptador devolve `RegistroProcuracao` já normalizado. Normalizar na
borda é o que permite somar fontes sem `if fonte == "jettax"` espalhado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Protocol, runtime_checkable

from app.core.documentos import normalizar_documento
from app.procuracoes.estados import StatusAutorizacao


class FonteError(RuntimeError):
    """Erro de uma fonte externa, com código estável e status HTTP sugerido."""

    def __init__(self, mensagem: str, *, codigo: str = "INTEGRACAO_RECUSOU", status_code: int = 502):
        super().__init__(mensagem)
        self.codigo = codigo
        self.status_code = status_code


class FonteNaoConfiguradaError(FonteError):
    def __init__(self, mensagem: str):
        super().__init__(mensagem, codigo="INTEGRACAO_NAO_CONFIGURADA", status_code=409)


@dataclass(frozen=True)
class ServicoAutorizado:
    codigo: str
    rotulo: str = ""
    expira_em: date | None = None


@dataclass(frozen=True)
class RegistroProcuracao:
    """Situação de uma empresa, como a fonte a enxerga.

    `situacao` é sempre um valor do domínio — o adaptador traduz o vocabulário
    do fornecedor. Quando não dá para afirmar nada, o valor correto é
    `SEM_AUTORIZACAO`, nunca `ATIVA` por otimismo.
    """

    documento: str
    razao_social: str = ""
    situacao: StatusAutorizacao = StatusAutorizacao.SEM_AUTORIZACAO
    data_inicio: date | None = None
    data_validade: date | None = None
    outorgado_documento: str = ""
    protocolo: str = ""
    servicos: tuple[ServicoAutorizado, ...] = field(default_factory=tuple)
    observacao: str = ""

    def normalizado(self) -> "RegistroProcuracao":
        """Canoniza o documento; levanta `ValueError` se for irreconhecível."""
        return RegistroProcuracao(
            documento=normalizar_documento(self.documento),
            razao_social=(self.razao_social or "").strip()[:255],
            situacao=self.situacao,
            data_inicio=self.data_inicio,
            data_validade=self.data_validade,
            outorgado_documento=(
                normalizar_documento(self.outorgado_documento)
                if self.outorgado_documento
                else ""
            ),
            protocolo=(self.protocolo or "").strip()[:120],
            servicos=self.servicos,
            observacao=(self.observacao or "").strip()[:500],
        )


@runtime_checkable
class FonteProcuracoes(Protocol):
    """Porta. Quem implementa vira plugável no registro de fontes."""

    nome: str

    def testar(self) -> str:
        """Confirma credencial/conectividade. Devolve uma frase para a tela."""

    def listar(self, documentos: Iterable[str] | None = None) -> list[RegistroProcuracao]:
        """Situação atual. `documentos` restringe a consulta quando a fonte suporta."""


def situacao_por_validade(
    validade: date | None, *, hoje: date | None = None, ativa: bool = True
) -> StatusAutorizacao:
    """Regra comum: validade no passado é expirada, independente do que a fonte diga."""
    if not ativa:
        return StatusAutorizacao.SEM_AUTORIZACAO
    if validade is None:
        return StatusAutorizacao.SEM_AUTORIZACAO
    referencia = hoje or date.today()
    return (
        StatusAutorizacao.EXPIRADA if validade < referencia else StatusAutorizacao.ATIVA
    )
