"""
Adaptador **oficial** de leitura: SERPRO Integra Contador — `PROCURACOES`.

Por que este adaptador existe e por que ele é o caminho preferido:

- é o canal **oficial** para consultar procurações/autorizações de forma
  programática, em produção desde 23/09/2022
  (`idSistema=PROCURACOES`, `idServico=OBTERPROCURACAO41`);
- consultar por API oficial não é "sistema automatizado não autorizado":
  é exatamente o que a IN RFB nº 2.320/2026 preserva como viável;
- substitui varredura de tela para a pergunta "quem está sem autorização?".

Endpoints usados (documentação pública do SERPRO, nada inventado):

- token OAuth2: ``POST https://gateway.apiserpro.serpro.gov.br/token``
  com ``grant_type=client_credentials`` e
  ``Authorization: Basic base64(consumerKey:consumerSecret)``;
- consulta: ``POST {base}/v1/Consultar`` com o corpo
  ``{contratante, autorPedidoDados, contribuinte, pedidoDados}``.

Base de produção: ``https://gateway.apiserpro.serpro.gov.br/integra-contador``
Base de demonstração: ``https://gateway.apiserpro.serpro.gov.br/integra-contador-trial``

**O que falta para operar em produção** (não é código, é contratação):
credenciais `consumerKey`/`consumerSecret` obtidas na Loja SERPRO com e-CNPJ
do escritório e, quando exigido pelo contrato, certificado cliente para mTLS.
Enquanto não houver credencial, o adaptador recusa-se a rodar com
`FonteNaoConfiguradaError` — não há caminho falso de sucesso.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Iterable

import httpx

from app.procuracoes.estados import StatusAutorizacao
from app.procuracoes.integracoes.base import (
    FonteError,
    FonteNaoConfiguradaError,
    RegistroProcuracao,
    ServicoAutorizado,
    situacao_por_validade,
)

log = logging.getLogger("cajuru.procuracoes.integra_contador")

HOST_OFICIAL = "gateway.apiserpro.serpro.gov.br"
URL_TOKEN = f"https://{HOST_OFICIAL}/token"
BASE_PRODUCAO = f"https://{HOST_OFICIAL}/integra-contador"
BASE_DEMONSTRACAO = f"https://{HOST_OFICIAL}/integra-contador-trial"

ID_SISTEMA = "PROCURACOES"
ID_SERVICO = "OBTERPROCURACAO41"
VERSAO_SISTEMA = "1"

TIPO_PJ = 2
TIPO_PF = 1


def _tipo_do_documento(documento: str) -> int:
    return TIPO_PF if len(documento) == 11 else TIPO_PJ


class ClienteIntegraContador:
    """Cliente mínimo, defensivo e sem estado global."""

    nome = "integra_contador"

    def __init__(
        self,
        *,
        consumer_key: str,
        consumer_secret: str,
        contratante: str,
        autor_pedido: str,
        base_url: str = BASE_PRODUCAO,
        certificado_cliente: tuple[str, str] | None = None,
        timeout: float = 45.0,
        client: httpx.Client | None = None,
    ):
        self.consumer_key = (consumer_key or "").strip()
        self.consumer_secret = (consumer_secret or "").strip()
        self.contratante = (contratante or "").strip()
        self.autor_pedido = (autor_pedido or "").strip() or self.contratante
        self.base_url = (base_url or BASE_PRODUCAO).strip().rstrip("/")
        self.certificado_cliente = certificado_cliente
        self.timeout = timeout
        self._client = client
        self._token: str = ""
        self._token_expira: datetime | None = None

        if not self.consumer_key or not self.consumer_secret:
            raise FonteNaoConfiguradaError(
                "Integra Contador sem credenciais. Informe consumerKey e consumerSecret "
                "obtidos na Loja SERPRO."
            )
        if not self.contratante:
            raise FonteNaoConfiguradaError(
                "Integra Contador exige o CNPJ contratante (e-CNPJ do escritório)."
            )
        if not self.base_url.startswith(f"https://{HOST_OFICIAL}/"):
            raise FonteError(
                "A base do Integra Contador deve ser o endereço oficial do SERPRO.",
                codigo="INTEGRACAO_RECUSOU",
                status_code=422,
            )

    # -- transporte ---------------------------------------------------------

    def _abrir(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(
            timeout=self.timeout,
            follow_redirects=False,
            cert=self.certificado_cliente,
        )

    def _executar(self, requisicao) -> httpx.Response:
        if self._client is not None:
            return requisicao(self._client)
        with self._abrir() as client:
            return requisicao(client)

    def _obter_token(self) -> str:
        agora = datetime.now(timezone.utc)
        if self._token and self._token_expira and self._token_expira > agora:
            return self._token

        credencial = base64.b64encode(
            f"{self.consumer_key}:{self.consumer_secret}".encode("utf-8")
        ).decode("ascii")
        try:
            resposta = self._executar(
                lambda c: c.post(
                    URL_TOKEN,
                    data={"grant_type": "client_credentials"},
                    headers={
                        "Authorization": f"Basic {credencial}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
            )
        except httpx.TimeoutException as exc:
            raise FonteError(
                "Tempo esgotado ao autenticar no SERPRO.", codigo="TEMPO_ESGOTADO", status_code=504
            ) from exc
        except httpx.TransportError as exc:
            raise FonteError(
                "Não foi possível alcançar o gateway do SERPRO.",
                codigo="FALHA_DE_REDE",
                status_code=502,
            ) from exc

        if resposta.status_code in (400, 401, 403):
            raise FonteError(
                "O SERPRO recusou as credenciais do Integra Contador.",
                codigo="INTEGRACAO_RECUSOU",
                status_code=401,
            )
        if resposta.status_code >= 400:
            raise FonteError(
                f"O gateway do SERPRO respondeu {resposta.status_code} na autenticação."
            )
        try:
            dados = resposta.json()
            token = str(dados["access_token"])
            expira = int(dados.get("expires_in") or 3000)
        except (ValueError, KeyError, TypeError) as exc:
            raise FonteError("Resposta de autenticação do SERPRO em formato inesperado.") from exc

        self._token = token
        # Renova com folga: um token que expira no meio do lote custa uma
        # rodada inteira de consultas.
        self._token_expira = agora + _segundos(max(60, expira - 120))
        return token

    def _consultar(self, corpo: dict[str, Any]) -> dict[str, Any]:
        token = self._obter_token()
        url = f"{self.base_url}/v1/Consultar"
        try:
            resposta = self._executar(
                lambda c: c.post(
                    url,
                    json=corpo,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
            )
        except httpx.TimeoutException as exc:
            raise FonteError(
                "Tempo esgotado na consulta ao Integra Contador.",
                codigo="TEMPO_ESGOTADO",
                status_code=504,
            ) from exc
        except httpx.TransportError as exc:
            raise FonteError(
                "Falha de rede na consulta ao Integra Contador.",
                codigo="FALHA_DE_REDE",
                status_code=502,
            ) from exc

        if resposta.status_code in (401, 403):
            self._token = ""
            raise FonteError(
                "O Integra Contador negou a consulta. Verifique contrato e autorização de acesso.",
                codigo="INTEGRACAO_RECUSOU",
                status_code=401,
            )
        if resposta.status_code == 429:
            raise FonteError(
                "Limite de requisições do Integra Contador atingido.",
                codigo="INTEGRACAO_RECUSOU",
                status_code=429,
            )
        if resposta.status_code >= 400:
            raise FonteError(
                f"O Integra Contador respondeu {resposta.status_code}.",
            )
        try:
            return resposta.json()
        except ValueError as exc:
            raise FonteError("O Integra Contador respondeu em formato inválido.") from exc

    # -- porta --------------------------------------------------------------

    def testar(self) -> str:
        self._obter_token()
        return "Autenticação OAuth2 no gateway do SERPRO confirmada."

    def listar(self, documentos: Iterable[str] | None = None) -> list[RegistroProcuracao]:
        """Consulta a procuração de cada contribuinte informado.

        O serviço `OBTERPROCURACAO41` é por outorgante/outorgado — não existe
        "listar tudo". Por isso `documentos` é obrigatório aqui: consultar a
        carteira inteira é responsabilidade de quem chama, que sabe o ritmo
        aceitável e o custo por requisição.
        """
        alvos = [d for d in (documentos or []) if d]
        if not alvos:
            raise FonteError(
                "O Integra Contador consulta um contribuinte por vez; informe os CNPJs.",
                codigo="DADOS_INSUFICIENTES",
                status_code=422,
            )

        resultados: list[RegistroProcuracao] = []
        for documento in alvos:
            corpo = {
                "contratante": {
                    "numero": self.contratante,
                    "tipo": _tipo_do_documento(self.contratante),
                },
                "autorPedidoDados": {
                    "numero": self.autor_pedido,
                    "tipo": _tipo_do_documento(self.autor_pedido),
                },
                "contribuinte": {
                    "numero": documento,
                    "tipo": _tipo_do_documento(documento),
                },
                "pedidoDados": {
                    "idSistema": ID_SISTEMA,
                    "idServico": ID_SERVICO,
                    "versaoSistema": VERSAO_SISTEMA,
                    "dados": json.dumps(
                        {
                            "outorgante": documento,
                            "tipoOutorgante": str(_tipo_do_documento(documento)),
                            "outorgado": self.autor_pedido,
                            "tipoOutorgado": str(_tipo_do_documento(self.autor_pedido)),
                        },
                        ensure_ascii=False,
                    ),
                },
            }
            try:
                bruto = self._consultar(corpo)
            except FonteError as exc:
                # Uma empresa que falha não derruba a carteira inteira.
                log.warning(
                    "integra_contador_falha_por_contribuinte",
                    extra={"documento": documento, "erro": str(exc)},
                )
                resultados.append(
                    RegistroProcuracao(
                        documento=documento,
                        situacao=StatusAutorizacao.SEM_AUTORIZACAO,
                        observacao=str(exc)[:500],
                    )
                )
                continue
            resultados.append(self._traduzir(documento, bruto))
        return resultados

    def _traduzir(self, documento: str, bruto: dict[str, Any]) -> RegistroProcuracao:
        """Traduz a resposta oficial para o vocabulário do módulo.

        A resposta do Integra Contador embrulha o conteúdo do serviço num
        campo `dados` que vem como *string* JSON. Estruturas ausentes viram
        `SEM_AUTORIZACAO` — nunca uma suposição otimista.
        """
        conteudo: Any = bruto.get("dados")
        if isinstance(conteudo, str):
            try:
                conteudo = json.loads(conteudo)
            except ValueError:
                conteudo = None
        if isinstance(conteudo, list):
            conteudo = conteudo[0] if conteudo else None
        if not isinstance(conteudo, dict):
            mensagens = bruto.get("mensagens")
            observacao = ""
            if isinstance(mensagens, list) and mensagens:
                primeira = mensagens[0]
                if isinstance(primeira, dict):
                    observacao = str(primeira.get("texto") or "")[:500]
            return RegistroProcuracao(
                documento=documento,
                situacao=StatusAutorizacao.SEM_AUTORIZACAO,
                observacao=observacao or "Sem procuração retornada pelo serviço oficial.",
            )

        servicos: list[ServicoAutorizado] = []
        lista = conteudo.get("sistemas") or conteudo.get("listaSistemas") or []
        if isinstance(lista, list):
            for item in lista:
                if isinstance(item, dict):
                    codigo = str(
                        item.get("nomeSistema") or item.get("sistema") or item.get("nome") or ""
                    ).strip()
                    if not codigo:
                        continue
                    servicos.append(
                        ServicoAutorizado(
                            codigo=codigo[:120],
                            rotulo=codigo[:255],
                            expira_em=_data(item.get("dataExpiracao") or item.get("expiracao")),
                        )
                    )
                elif isinstance(item, str) and item.strip():
                    servicos.append(ServicoAutorizado(codigo=item.strip()[:120], rotulo=item.strip()[:255]))

        validade = _data(
            conteudo.get("dataExpiracao")
            or conteudo.get("expiracao")
            or conteudo.get("dataValidade")
        )
        if validade is None and servicos:
            futuras = [s.expira_em for s in servicos if s.expira_em]
            validade = max(futuras) if futuras else None

        return RegistroProcuracao(
            documento=documento,
            razao_social=str(conteudo.get("nomeOutorgante") or "")[:255],
            situacao=situacao_por_validade(validade, ativa=bool(servicos or validade)),
            data_validade=validade,
            outorgado_documento=self.autor_pedido,
            servicos=tuple(servicos),
            observacao="" if servicos else "Procuração sem serviços listados.",
        )


def _segundos(valor: int):
    from datetime import timedelta

    return timedelta(seconds=valor)


def _data(valor: Any) -> date | None:
    """Aceita `AAAA-MM-DD`, `AAAAMMDD` e `DD/MM/AAAA` — formatos vistos na API."""
    if valor in (None, ""):
        return None
    texto = str(valor).strip()
    for formato in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date()
    except ValueError:
        return None
