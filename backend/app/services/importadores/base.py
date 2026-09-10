"""
Interface comum a todo importador de documento fiscal.

NFS-e (ADN, REST), NFe e CT-e (SEFAZ, SOAP) são protocolos diferentes, mas
resolvem o mesmo formato de problema: autenticar via mTLS com o certificado
A1, avançar um cursor (NSU), baixar lotes, e informar de onde continuar na
próxima chamada. Modelar isso como interface comum é o que permite plugar
NFe (Fase 2) e CT-e (Fase 3) sem tocar no que já funciona para NFS-e.

## As regras que este módulo existe para respeitar

Tanto o ADN (NFS-e) quanto o Ambiente Nacional (NFe/CT-e) aplicam a mesma
política de "consumo consciente" (NT 2014.002 v1.12 / Manual dos Contribuintes
do ADN):

1. Recebeu `cStat=137` (nada novo)? **Aguarde 1 hora** antes de perguntar de
   novo. Perguntar antes ⇒ `cStat=656` e o CNPJ é bloqueado por 1 hora.
2. Esteja em `656` ou não, a consulta seguinte **tem que usar o `ultNSU`
   devolvido pelo serviço** — consultar fora da sequência também bloqueia.
3. Consultas pontuais (por chave `consChNFe` / por NSU `consNSU`) têm teto de
   **20 por hora** por CNPJ.
4. Dentro do loop de paginação, o intervalo mínimo entre requisições é de
   **2 segundos**, com limite de iterações (o sped-nfe recomenda 50).
5. Recebido um 656, **recomeçar antes de completar 1 hora zera a contagem** e
   o bloqueio recomeça. Ou seja: retry agressivo *piora* o problema — é
   exatamente o anti-padrão que derruba sistemas de importação no mercado.

Nada disso é "detalhe de rede": é o motivo pelo qual o importador certo roda
sozinho para sempre e o errado fica travado em "Consumo Indevido". A
orquestração desses prazos vive em `app/services/sincronizacao.py`; aqui só
está o contrato que os importadores cumprem.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta

from app.services.importadores.eventos import EventoFiscal

# Regra oficial (NT 2014.002 v1.12 + manual do ADN): depois de "nada novo",
# a próxima consulta só deve acontecer 1 hora depois.
COOLDOWN_SEM_NOVIDADE = timedelta(hours=1)

# Margem aplicada em cima da hora oficial: o relógio do ambiente e o nosso
# nunca batem exatamente, e chegar 2 minutos adiantado vale um novo bloqueio.
MARGEM_SEGURANCA = timedelta(minutes=6)

# Limite oficial de consultas pontuais (consChNFe / consNSU) por CNPJ.
LIMITE_CONSULTAS_PONTUAIS_POR_HORA = 20


class ErroFiscal(ConnectionError):
    """
    Base dos erros que o importador sabe explicar para o operador.

    Herda de `ConnectionError` porque é assim que o resto do sistema (e
    chamadores antigos) trata "a consulta não pôde ser feita": continua
    funcionando o `except ConnectionError` pré-existente, e quem quiser
    distinguir 656 de queda de rede usa as subclasses abaixo.
    """


class ConsumoIndevido(ErroFiscal):
    """
    O ambiente (SEFAZ/ADN) respondeu `cStat=656` — o CNPJ está bloqueado por
    consumo indevido.

    Isso **não é falha do sistema nem do certificado**: é limite de uso. A
    resposta ainda traz os `ultNSU`/`maxNSU` autoritativos do ambiente, então
    quem trata o erro deve (a) adotar esses NSUs para voltar alinhado e
    (b) só tentar de novo depois do bloqueio, nunca antes — tentar mais cedo
    zera o cronômetro do bloqueio.
    """

    def __init__(
        self,
        motivo: str,
        *,
        cstat: str = "656",
        ultimo_nsu: str | None = None,
        max_nsu: str | None = None,
        bloqueio: timedelta | None = None,
        ambiente: str = "SEFAZ",
    ) -> None:
        self.cstat = cstat
        self.motivo = motivo or "Consumo indevido"
        self.ultimo_nsu = ultimo_nsu
        self.max_nsu = max_nsu
        self.bloqueio = bloqueio or (COOLDOWN_SEM_NOVIDADE + MARGEM_SEGURANCA)
        self.ambiente = ambiente
        super().__init__(f"{ambiente} retornou cStat={cstat}: {self.motivo}")


class AmbienteIndisponivel(ErroFiscal):
    """
    Falha de transporte/5xx: dá para tentar de novo sem queimar cota (o
    documento nem foi consultado). Diferente de `ConsumoIndevido`, que exige
    esperar o bloqueio inteiro.
    """

    def __init__(self, mensagem: str, *, tentativa_recomendada: timedelta | None = None):
        self.tentativa_recomendada = tentativa_recomendada or timedelta(minutes=5)
        super().__init__(mensagem)


@dataclass
class DocumentoBaixado:
    chave_acesso: str
    nsu: str
    xml: bytes
    data_emissao: str
    valor_total: float
    direcao: str  # "tomada" ou "prestada"
    # Competência do documento (o que o contador chama de "mês"). vem de
    # dCompet/PeriodoRef/dComp quando existe; vazio quando o XML não traz.
    competencia: str = ""
    # "completo" = procNFe/procCTe/NFS-e com o XML inteiro.
    # "resumo"  = resNFe/resCTe — a distribuição só libera o XML completo do
    #             destinatário depois da manifestação; dá para recuperar
    #             pontualmente pela chave (consChNFe), e o worker faz isso.
    leiaute: str = "completo"
    numero: str = ""
    serie: str = ""
    emitente_documento: str = ""
    emitente_nome: str = ""
    destinatario_documento: str = ""
    destinatario_nome: str = ""
    status_autorizacao: str = ""


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
    # Maior NSU existente no ambiente para este CNPJ. Quando `proximo_nsu`
    # chega nele, a empresa está 100% em dia — é isso que o painel mostra.
    max_nsu: str | None = None
    # True quando o ambiente respondeu explicitamente "nada novo" (cStat 137
    # / HTTP 404 NENHUM_DOCUMENTO_LOCALIZADO). É o gatilho do cooldown de 1h.
    sem_novidade: bool = False


class ImportadorFiscal(ABC):
    """
    Cada fonte (ADN para NFS-e, SEFAZ para NFe/CT-e) implementa isto.
    O worker (app/worker/tasks.py) só conhece esta interface — não sabe
    nem precisa saber se por trás é REST ou SOAP.
    """

    # Nome do ambiente nas mensagens para o operador.
    ambiente_nome = "SEFAZ"

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

        Levanta `ConsumoIndevido` quando o CNPJ está bloqueado e
        `AmbienteIndisponivel` quando a falha é de rede/5xx — o worker trata
        os dois de forma oposta (esperar 1h × tentar logo).
        """
        raise NotImplementedError

    def buscar_por_chave(
        self, cnpj: str, cert_path: str, key_path: str, chave_acesso: str, uf: str | None = None
    ) -> DocumentoBaixado | None:
        """
        Consulta pontual pela chave de acesso (`consChNFe`).

        Só a NFe tem essa operação no leiaute oficial — CT-e e NFS-e não
        expõem `consChNFe`, então a implementação base declara indisponível e
        os importadores que suportam sobrescrevem.
        """
        raise NotImplementedError(
            f"{type(self).__name__} não suporta consulta por chave de acesso."
        )

    def buscar_por_nsu(
        self, cnpj: str, cert_path: str, key_path: str, nsu: str, uf: str | None = None
    ) -> DocumentoBaixado | None:
        """Consulta pontual de um NSU específico (fechar lacuna na sequência)."""
        raise NotImplementedError(
            f"{type(self).__name__} não suporta consulta por NSU específico."
        )
