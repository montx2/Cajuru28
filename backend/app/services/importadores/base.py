"""
Interface comum a todo importador de documento fiscal.

NFS-e (ADN, REST), NFe e CT-e (SEFAZ, SOAP) são protocolos diferentes, mas
resolvem o mesmo formato de problema: autenticar via mTLS com o certificado
A1, avançar um cursor (NSU), baixar lotes, e informar de onde continuar na
próxima chamada. Modelar isso como interface comum é o que permite plugar
NFe (Fase 2) e CT-e (Fase 3) sem tocar no que já funciona para NFS-e.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.services.importadores.eventos import EventoFiscal


@dataclass
class DocumentoBaixado:
    chave_acesso: str
    nsu: str
    xml: bytes
    data_emissao: str
    valor_total: float
    direcao: str  # "tomada" ou "prestada"


@dataclass
class LoteImportado:
    documentos: list[DocumentoBaixado]
    proximo_nsu: str
    ha_mais_documentos: bool
    # Eventos recebidos neste lote (cancelamento etc.) — nunca descartados.
    eventos: list[EventoFiscal] = field(default_factory=list)
    # Itens que pareciam ser eventos mas não puderam ser aplicados nem
    # classificados como documento (contabilizados no painel).
    eventos_nao_reconhecidos: int = 0
    # Itens que falharam na conversão/decodificação (descritos em `erros`).
    erros: list[str] = field(default_factory=list)


class ImportadorFiscal(ABC):
    """
    Cada fonte (ADN para NFS-e, SEFAZ para NFe/CT-e) implementa isto.
    O worker (app/worker/tasks.py) só conhece esta interface — não sabe
    nem precisa saber se por trás é REST ou SOAP.
    """

    @abstractmethod
    def buscar_lote(
        self,
        cnpj: str,
        cert_path: str,
        key_path: str,
        ultimo_nsu: str,
        uf: str | None = None,
    ) -> LoteImportado:
        """
        Busca o próximo lote de documentos a partir do NSU informado.
        `uf` (sigla, ex.: "SP") é necessário para NFe/CT-e (identifica o
        cUFAutor da consulta ao SEFAZ) e ignorado pelo importador de NFS-e.
        """
        raise NotImplementedError
