"""Adaptador seguro para a API pública Jettax 360 / Morfeu.

A Jettax é uma fonte de captura *a montante*, não uma variante do protocolo
ADN/SEFAZ. Por isso seus cursores (`lastId`/`ultimoId`), suas execuções e seus
resultados ficam em tabelas próprias. O documento fiscal, por outro lado,
continua único no NotasFlow: se a mesma nota também vier da fonte direta, a
proveniência é adicionada sem substituir o XML já guardado.

Este módulo só usa contratos publicados na coleção Morfeu:
- clientes: POST/PUT ``/api/clients``;
- NFS-e: GET ``/api/nfse/invoices/{cnpj}``;
- NF-e: GET ``/api/nfes/clients/{cnpj}/sales|purchases/``;
A coleção também identifica uma rota CT-e ``sales``, mas não publica uma
estrutura de resposta suficiente para importar com segurança; ela permanece
fora deste adaptador até a documentação estar completa.

Não há endpoint de download de XML de NFS-e documentado. A captura de NFS-e
persiste, portanto, somente o resumo normalizado retornado pela API e marca o
leiaute como ``metadados``. Nunca inventamos uma URL de XML/PDF.
"""

from __future__ import annotations

import base64
import gzip
import os
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import httpx
from dateutil import parser as date_parser
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.documentos import normalizar_cnpj, normalizar_documento
from app.models import (
    DirecaoDocumento,
    DocumentoFiscal,
    DocumentoFiscalFonte,
    Empresa,
    JettaxConfiguracaoEmpresa,
    JettaxExecucao,
    StatusDocumentoFiscal,
    TipoDocumentoFiscal,
)
from app.services.importadores.base import DocumentoBaixado
from app.services.importadores.nfe_sefaz import ImportadorNFeSEFAZ


ORIGEM_JETTAX = "jettax"
_FLUXO_NFSE = "nfse"
_FLUXOS_DFE = {"sales", "purchases"}
_MAX_TEXTO_ERRO = 500


class JettaxErro(RuntimeError):
    """Erro seguro para a API/UI, sem corpo de resposta ou segredo remoto."""

    def __init__(self, mensagem: str, *, categoria: str = "indisponivel", status_code: int | None = None):
        super().__init__(mensagem)
        self.categoria = categoria
        self.status_code = status_code


class JettaxNaoConfigurada(JettaxErro):
    def __init__(self) -> None:
        super().__init__(
            "Integração Jettax não configurada. Defina JETTAX_API_TOKEN no ambiente seguro do servidor.",
            categoria="nao_configurada",
        )


def _texto(valor: object, limite: int = 255) -> str:
    return str(valor or "").strip()[:limite]


def _digitos(valor: object) -> str:
    """Usado somente em campos que o contrato define como numéricos (ex. IBGE)."""
    return "".join(caractere for caractere in str(valor or "") if caractere.isdigit())


def _cnpj_jettax(valor: object) -> str:
    """Evita transmitir CNPJ alfa a um contrato Morfeu ainda não verificado."""
    try:
        cnpj = normalizar_cnpj(str(valor or ""))
    except ValueError as exc:
        raise JettaxErro("CNPJ inválido para a integração Jettax.", categoria="cadastro") from exc
    if not cnpj.isdigit():
        raise JettaxErro(
            "O suporte da Jettax a CNPJ alfanumérico ainda não foi confirmado no contrato público; "
            "a empresa foi preservada localmente e não será transmitida até essa validação.",
            categoria="contrato",
        )
    return cnpj


def _documento_preservado(valor: object) -> str:
    try:
        return normalizar_documento(str(valor or ""))
    except ValueError:
        return ""


def _campo(item: dict[str, Any], *nomes: str, padrao: Any = None) -> Any:
    """Lê campos sem confiar em maiúsculas/minúsculas do fornecedor."""
    normalizado = {str(chave).lower(): valor for chave, valor in item.items()}
    for nome in nomes:
        if nome in item:
            return item[nome]
        valor = normalizado.get(nome.lower())
        if valor is not None:
            return valor
    return padrao


def _dicionario(valor: object) -> dict[str, Any]:
    return valor if isinstance(valor, dict) else {}


def _data_hora(valor: object) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    texto = _texto(valor)
    if not texto:
        return datetime.now(timezone.utc)
    try:
        resultado = date_parser.isoparse(texto)
    except (ValueError, TypeError, OverflowError):
        try:
            resultado = date_parser.parse(texto)
        except (ValueError, TypeError, OverflowError):
            return datetime.now(timezone.utc)
    return resultado if resultado.tzinfo else resultado.replace(tzinfo=timezone.utc)


def _para_data(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = _texto(valor)
    if not texto:
        return None
    try:
        return date_parser.isoparse(texto).date()
    except (ValueError, TypeError, OverflowError):
        return None


def _competencia(valor: object, fallback: datetime) -> date | None:
    texto = _texto(valor)
    if texto:
        try:
            return date_parser.parse(texto, default=datetime(2000, 1, 1)).date().replace(day=1)
        except (ValueError, TypeError, OverflowError):
            pass
    return fallback.date().replace(day=1) if fallback else None


def _decimal(valor: object) -> float:
    original = _texto(valor)
    if "," in original and "." in original:
        # O último separador normalmente é o decimal: aceita tanto
        # 1.234,56 (pt-BR) quanto 1,234.56 (formato internacional).
        if original.rfind(",") > original.rfind("."):
            texto = original.replace(".", "").replace(",", ".")
        else:
            texto = original.replace(",", "")
    elif "," in original:
        texto = original.replace(",", ".")
    else:
        texto = original
    try:
        return float(Decimal(texto or "0"))
    except (InvalidOperation, ValueError):
        return 0.0


def _normalizar_chave(chave: str) -> str:
    return _texto(chave, 60)


class ClienteJettax:
    """Cliente HTTP síncrono com timeout, paginação limitada e logs redigidos."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or settings.jettax_api_base_url).strip().rstrip("/")
        self.token = (token if token is not None else settings.jettax_api_token).strip()
        self.timeout = max(1.0, float(timeout if timeout is not None else settings.jettax_timeout_segundos))
        self._client = client
        if not self.token:
            raise JettaxNaoConfigurada()
        partes = urlparse(self.base_url)
        if partes.scheme not in {"http", "https"} or not partes.netloc:
            raise JettaxErro("JETTAX_API_BASE_URL inválida.", categoria="configuracao")

    @property
    def configurado(self) -> bool:
        return bool(self.token)

    def _url_segura(self, rota_ou_url: str) -> str:
        url = rota_ou_url if rota_ou_url.startswith(("http://", "https://")) else urljoin(self.base_url + "/", rota_ou_url.lstrip("/"))
        base = urlparse(self.base_url)
        destino = urlparse(url)
        # O link next vem do fornecedor. Nunca seguimos uma URL de outro host,
        # pois isso mandaria o header Authorization para fora da Jettax.
        if (destino.scheme, destino.netloc) != (base.scheme, base.netloc):
            raise JettaxErro("A Jettax retornou uma paginação fora do domínio configurado.", categoria="protocolo")
        return url

    def _requisitar(self, metodo: str, rota_ou_url: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> Any:
        cabecalhos = {
            "Authorization": self.token,
            "Accept": "application/vnd.morfeu.v2+json, application/json",
        }
        if self._client is not None:
            return self._tratar_resposta(self._client.request(metodo, self._url_segura(rota_ou_url), params=params, json=json, headers=cabecalhos))
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                resposta = client.request(
                    metodo, self._url_segura(rota_ou_url), params=params, json=json, headers=cabecalhos
                )
        except httpx.TimeoutException as exc:
            raise JettaxErro("Tempo esgotado ao comunicar com a Jettax.") from exc
        except httpx.TransportError as exc:
            raise JettaxErro("Não foi possível comunicar com a Jettax.") from exc
        return self._tratar_resposta(resposta)

    @staticmethod
    def _tratar_resposta(resposta: httpx.Response) -> Any:
        if resposta.status_code in (401, 403):
            raise JettaxErro("A Jettax recusou a autenticação do conector.", categoria="autenticacao", status_code=resposta.status_code)
        if resposta.status_code == 429 or resposta.status_code >= 500:
            raise JettaxErro("A Jettax está indisponível ou limitou temporariamente a consulta.", status_code=resposta.status_code)
        if 300 <= resposta.status_code < 400:
            # Redirecionamento não é seguido: o Authorization não pode sair do
            # host configurado, mesmo que o fornecedor responda Location.
            raise JettaxErro("A Jettax respondeu com redirecionamento inesperado.", categoria="protocolo", status_code=resposta.status_code)
        if resposta.status_code >= 400:
            raise JettaxErro("A Jettax rejeitou a solicitação do conector.", categoria="rejeitada", status_code=resposta.status_code)
        if not resposta.content:
            return {}
        try:
            dados = resposta.json()
        except ValueError as exc:
            raise JettaxErro("A Jettax respondeu em um formato não reconhecido.", categoria="protocolo") from exc
        if isinstance(dados, dict) and str(dados.get("status", "")).upper() == "ERROR":
            # O corpo pode conter dado operacional/credencial municipal. A
            # semântica chega à execução, mas o texto remoto não é propagado.
            raise JettaxErro("A Jettax reportou erro ao processar a solicitação.", categoria="rejeitada")
        return dados

    def criar_cliente(self, dados: dict[str, Any]) -> Any:
        return self._requisitar("POST", "/api/clients", json=dados)

    def atualizar_cliente(self, cnpj: str, dados: dict[str, Any]) -> Any:
        return self._requisitar("PUT", f"/api/clients/{_cnpj_jettax(cnpj)}", json=dados)

    def verificar_conexao(self, codigo_ibge: str | None = None) -> Any:
        # GET /api/nfse/cities é um endpoint documentado, de leitura e que
        # exige o mesmo Authorization das demais operações.
        params: dict[str, Any] = {"ibgeCode": _digitos(codigo_ibge)} if codigo_ibge else {}
        return self._requisitar("GET", "/api/nfse/cities", params=params)

    def _listar_paginas(self, rota: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rota_atual: str | None = rota
        parametros_atuais: dict[str, Any] | None = {chave: valor for chave, valor in params.items() if valor not in (None, "")}
        documentos: list[dict[str, Any]] = []
        visitadas: set[str] = set()
        limite = max(1, int(settings.jettax_max_paginas_por_execucao))

        for _ in range(limite):
            if not rota_atual:
                break
            url = self._url_segura(rota_atual)
            if url in visitadas:
                raise JettaxErro("A Jettax retornou paginação cíclica.", categoria="protocolo")
            visitadas.add(url)
            resposta = self._requisitar("GET", rota_atual, params=parametros_atuais)
            parametros_atuais = None  # links next já carregam a query própria
            if isinstance(resposta, list):
                pagina = resposta
                proxima = None
            elif isinstance(resposta, dict):
                pagina = resposta.get("data", [])
                meta = _dicionario(resposta.get("meta"))
                paginacao = _dicionario(meta.get("pagination"))
                links = _dicionario(paginacao.get("links"))
                proxima = links.get("next")
            else:
                raise JettaxErro("A Jettax retornou uma lista em formato não reconhecido.", categoria="protocolo")
            if not isinstance(pagina, list) or any(not isinstance(item, dict) for item in pagina):
                raise JettaxErro("A Jettax retornou documentos em formato não reconhecido.", categoria="protocolo")
            documentos.extend(pagina)
            rota_atual = str(proxima) if proxima else None
        else:
            raise JettaxErro(
                "Limite de páginas da Jettax atingido; reduza o período ou aumente JETTAX_MAX_PAGINAS_POR_EXECUCAO.",
                categoria="limite_local",
            )
        return documentos

    def listar_nfse(self, cnpj: str, *, last_id: str | None = None, numero: str | None = None, nota_situacao: str | None = None, tipo_nota: str | None = None, period: str | None = None) -> list[dict[str, Any]]:
        return self._listar_paginas(
            f"/api/nfse/invoices/{_cnpj_jettax(cnpj)}",
            {"lastId": last_id, "numero": numero, "notaSituacao": nota_situacao, "tipoNota": tipo_nota, "period": period},
        )

    def listar_nfes(self, cnpj: str, fluxo: str, *, ultimo_id: str | None = None, chave: str | None = None, data_inicial: date | None = None, data_final: date | None = None, cnpj_destinatario: str | None = None, cnpj_emitente: str | None = None) -> list[dict[str, Any]]:
        if fluxo not in _FLUXOS_DFE:
            raise JettaxErro("Fluxo NF-e não suportado pela integração.", categoria="configuracao")
        return self._listar_paginas(
            f"/api/nfes/clients/{_cnpj_jettax(cnpj)}/{fluxo}/",
            {
                "ultimoId": ultimo_id,
                "chave": chave,
                "dataInicial": data_inicial.isoformat() if data_inicial else None,
                "dataFinal": data_final.isoformat() if data_final else None,
                # O filtro também chega a uma rota Morfeu documentada somente
                # para CNPJ numérico. Não deixar letras virarem outro CNPJ.
                "cnpjDestinario": _cnpj_jettax(cnpj_destinatario) if cnpj_destinatario else None,
                "cnpjEmitente": _cnpj_jettax(cnpj_emitente) if cnpj_emitente else None,
            },
        )

def carga_cliente(empresa: Empresa, configuracao: JettaxConfiguracaoEmpresa, *, certificado_base64: str | None = None, senha_certificado: str | None = None) -> dict[str, Any]:
    """Monta o corpo publicado para Client sem jamais gravar/retornar segredos."""
    cnpj = _cnpj_jettax(empresa.cnpj_cpf)
    codigo_ibge = _digitos(empresa.codigo_ibge)
    ccm = _texto(empresa.inscricao_municipal, 100)
    faltantes = []
    if len(cnpj) != 14:
        faltantes.append("CNPJ de 14 dígitos")
    if len(codigo_ibge) != 7:
        faltantes.append("código IBGE")
    if not ccm:
        faltantes.append("inscrição municipal (CCM)")
    if not _texto(empresa.razao_social):
        faltantes.append("razão social")
    if faltantes:
        raise JettaxErro("Complete antes do registro Jettax: " + ", ".join(faltantes) + ".", categoria="cadastro")

    resultado: dict[str, Any] = {
        "razao_social": _texto(empresa.razao_social, 255),
        "codigo_ibge": codigo_ibge,
        "cnpj": cnpj,
        "ccm": ccm,
        "baixar_nfes": bool(configuracao.baixar_nfes),
        "baixar_nfes_enviadas": bool(configuracao.baixar_nfes_enviadas),
    }
    if certificado_base64 is not None and senha_certificado is not None:
        resultado["digital_certificate"] = certificado_base64
        resultado["digital_certificate_password"] = senha_certificado
    return resultado


def cursor_para(configuracao: JettaxConfiguracaoEmpresa, tipo: TipoDocumentoFiscal, fluxo: str) -> str | None:
    campos = {
        (TipoDocumentoFiscal.NFSE, _FLUXO_NFSE): "ultimo_id_nfse",
        (TipoDocumentoFiscal.NFE, "sales"): "ultimo_id_nfe_saida",
        (TipoDocumentoFiscal.NFE, "purchases"): "ultimo_id_nfe_entrada",
    }
    campo = campos.get((tipo, fluxo))
    if campo is None:
        raise JettaxErro("Cursor Jettax não definido para este tipo/fluxo.", categoria="configuracao")
    return getattr(configuracao, campo)


def atualizar_cursor(configuracao: JettaxConfiguracaoEmpresa, tipo: TipoDocumentoFiscal, fluxo: str, cursor: str) -> None:
    campos = {
        (TipoDocumentoFiscal.NFSE, _FLUXO_NFSE): "ultimo_id_nfse",
        (TipoDocumentoFiscal.NFE, "sales"): "ultimo_id_nfe_saida",
        (TipoDocumentoFiscal.NFE, "purchases"): "ultimo_id_nfe_entrada",
    }
    campo = campos.get((tipo, fluxo))
    if campo is None:
        raise JettaxErro("Cursor Jettax não definido para este tipo/fluxo.", categoria="configuracao")
    setattr(configuracao, campo, _texto(cursor, 100) or None)


def _maior_cursor(itens: Iterable[dict[str, Any]], anterior: str | None) -> str | None:
    candidatos = [_texto(_campo(item, "id", "ultimoId", "lastId"), 100) for item in itens]
    candidatos = [valor for valor in candidatos if valor]
    if not candidatos:
        return anterior
    # IDs da Morfeu são apresentados como números. Se a forma futura não for
    # numérica, manter o último retorno é mais seguro que uma ordenação lexical.
    if all(valor.isdigit() for valor in candidatos):
        return str(max(int(valor) for valor in candidatos))
    return candidatos[-1]


def _insert_sem_duplicar(db: Session, tabela, valores: dict[str, Any], *, constraint: str | None = None, index_elements: tuple[str, ...] = ()) -> bool:
    dialeto = db.get_bind().dialect.name
    if dialeto == "postgresql":
        comando = postgresql_insert(tabela).values(**valores).on_conflict_do_nothing(constraint=constraint)
    elif dialeto == "sqlite":
        comando = sqlite_insert(tabela).values(**valores).on_conflict_do_nothing(index_elements=index_elements)
    else:
        raise RuntimeError(f"Banco não suportado para inserção idempotente: {dialeto}.")
    return db.execute(comando).rowcount == 1


def registrar_proveniencia(db: Session, documento_id: int, origem: str, identificador_externo: str | None) -> None:
    """Guarda uma confirmação de origem sem expor ou alterar o documento base."""
    _insert_sem_duplicar(
        db,
        DocumentoFiscalFonte.__table__,
        {
            "documento_id": documento_id,
            "origem": _texto(origem, 30),
            "identificador_externo": _texto(identificador_externo, 100),
        },
        constraint="uq_documento_fonte_identificador",
        index_elements=("documento_id", "origem", "identificador_externo"),
    )


def _texto_documento(doc: DocumentoBaixado, campo: str, limite: int) -> str | None:
    return _texto(getattr(doc, campo, ""), limite) or None


def _persistir_xml(db: Session, empresa_id: int, tipo: TipoDocumentoFiscal, doc: DocumentoBaixado, *, identificador_externo: str) -> bool:
    chave = _normalizar_chave(doc.chave_acesso)
    if not chave or not doc.xml:
        raise ValueError("Documento Jettax sem chave fiscal ou XML.")
    pasta = os.path.join(settings.dados_dir, "xml", str(empresa_id), tipo.value)
    nome = "".join(caractere for caractere in chave if caractere.isalnum() or caractere in "-_") or f"jettax_{identificador_externo}"
    caminho = os.path.join(pasta, f"{nome}.xml")
    direcao = doc.direcao if doc.direcao in {"tomada", "prestada"} else "tomada"
    criado = _insert_sem_duplicar(
        db,
        DocumentoFiscal.__table__,
        {
            "empresa_id": empresa_id,
            "tipo": tipo,
            "direcao": DirecaoDocumento(direcao),
            "chave_acesso": chave,
            "nsu": _texto(doc.nsu, 20) or "0",
            "data_emissao": _data_hora(doc.data_emissao),
            "competencia": _competencia(doc.competencia, _data_hora(doc.data_emissao)),
            "valor_total": float(doc.valor_total or 0),
            "xml_path": caminho,
            "status": StatusDocumentoFiscal.NORMAL,
            "leiaute": _texto(doc.leiaute, 12) or "completo",
            "numero": _texto_documento(doc, "numero", 20),
            "serie": _texto_documento(doc, "serie", 10),
            "emitente_documento": _texto_documento(doc, "emitente_documento", 18),
            "emitente_nome": _texto_documento(doc, "emitente_nome", 255),
            "destinatario_documento": _texto_documento(doc, "destinatario_documento", 18),
            "destinatario_nome": _texto_documento(doc, "destinatario_nome", 255),
            "situacao": _texto_documento(doc, "status_autorizacao", 255),
            "origem": ORIGEM_JETTAX,
        },
        constraint="uq_documento_por_empresa",
        index_elements=("empresa_id", "chave_acesso"),
    )
    documento = db.query(DocumentoFiscal).filter(
        DocumentoFiscal.empresa_id == empresa_id, DocumentoFiscal.chave_acesso == chave
    ).first()
    if documento is None:
        raise RuntimeError("Não foi possível localizar o documento Jettax recém-gravado.")
    registrar_proveniencia(db, documento.id, ORIGEM_JETTAX, identificador_externo)
    if criado:
        os.makedirs(pasta, exist_ok=True)
        with open(caminho, "wb") as arquivo:
            arquivo.write(doc.xml)
    return criado


def _direcao_nfse(item: dict[str, Any], empresa: Empresa) -> str:
    tipo = _texto(_campo(item, "tipoNota")).lower()
    if tipo in {"emitida", "enviada", "prestada", "saida", "saída"}:
        return "prestada"
    if tipo in {"recebida", "tomada", "nfts"}:
        return "tomada"
    prestador = _dicionario(_campo(item, "prestadorServico", "prestador_servico"))
    identificacao = _dicionario(_campo(prestador, "identificacaoPrestador", "identificacao_prestador"))
    if _documento_preservado(_campo(identificacao, "cnpj", "cpfCnpj")) == _documento_preservado(empresa.cnpj_cpf):
        return "prestada"
    return "tomada"


def _persistir_nfse_metadados(db: Session, empresa: Empresa, item: dict[str, Any]) -> bool:
    identificador = _texto(_campo(item, "id"), 100)
    if not identificador:
        raise ValueError("NFS-e Jettax sem id do fornecedor.")
    chave = _normalizar_chave(f"jettax-nfse-{identificador}")
    servico = _dicionario(_campo(item, "servico"))
    valores_servico = _dicionario(_campo(servico, "valores"))
    prestador = _dicionario(_campo(item, "prestadorServico", "prestador_servico"))
    prestador_id = _dicionario(_campo(prestador, "identificacaoPrestador", "identificacao_prestador"))
    tomador = _dicionario(_campo(item, "tomadorServico", "tomador_servico"))
    tomador_id = _dicionario(_campo(tomador, "identificacaoTomador", "identificacao_tomador"))
    emissao = _data_hora(_campo(item, "dataEmissao", "data_emissao"))
    situacao = _texto(_campo(item, "notaSituacao", "situacao"), 255)
    criado = _insert_sem_duplicar(
        db,
        DocumentoFiscal.__table__,
        {
            "empresa_id": empresa.id,
            "tipo": TipoDocumentoFiscal.NFSE,
            "direcao": DirecaoDocumento(_direcao_nfse(item, empresa)),
            "chave_acesso": chave,
            "nsu": _texto(identificador, 20),
            "data_emissao": emissao,
            "competencia": _competencia(_campo(item, "dataCompetencia", "competencia"), emissao),
            "valor_total": _decimal(_campo(valores_servico, "valorLiquidoNfse", "valorServicos", "valorBase", "baseCalculo")),
            # A API documenta metadados e uma URL opcional, mas não documenta
            # contrato de download. Não gravar conteúdo não confirmado como XML.
            "xml_path": "",
            "status": StatusDocumentoFiscal.CANCELADA if situacao.lower() == "cancelada" else StatusDocumentoFiscal.NORMAL,
            "leiaute": "metadados",
            "numero": _texto(_campo(item, "numero"), 20) or None,
            "serie": _texto(_campo(item, "notaSerie", "serie"), 10) or None,
            "emitente_documento": _documento_preservado(_campo(prestador_id, "cnpj", "cpfCnpj"))[:18] or None,
            "emitente_nome": _texto(_campo(prestador, "razaoSocial", "razao_social"), 255) or None,
            "destinatario_documento": _documento_preservado(_campo(tomador_id, "cpfCnpj", "cnpj", "cpf"))[:18] or None,
            "destinatario_nome": _texto(_campo(tomador, "razaoSocial", "razao_social"), 255) or None,
            "situacao": situacao or None,
            "origem": ORIGEM_JETTAX,
        },
        constraint="uq_documento_por_empresa",
        index_elements=("empresa_id", "chave_acesso"),
    )
    documento = db.query(DocumentoFiscal).filter(
        DocumentoFiscal.empresa_id == empresa.id, DocumentoFiscal.chave_acesso == chave
    ).first()
    if documento is None:
        raise RuntimeError("Não foi possível localizar a NFS-e Jettax recém-gravada.")
    registrar_proveniencia(db, documento.id, ORIGEM_JETTAX, identificador)
    # O cancelamento pode chegar de uma fonte após a outra. Sempre preserva a
    # informação mais conservadora; não reativa documento por uma listagem velha.
    if situacao.lower() == "cancelada" and documento.status != StatusDocumentoFiscal.CANCELADA:
        documento.status = StatusDocumentoFiscal.CANCELADA
        documento.motivo_cancelamento = "Situação cancelada informada pela Jettax"
        documento.cancelado_em = emissao
    return criado


def _xml_gzip_base64(item: dict[str, Any]) -> bytes:
    conteudo = _campo(item, "xml", "XML")
    if not isinstance(conteudo, str) or not conteudo.strip():
        raise ValueError("Documento Jettax sem XML compactado.")
    try:
        return gzip.decompress(base64.b64decode(conteudo.strip(), validate=True))
    except (ValueError, OSError, EOFError) as exc:
        raise ValueError("XML compactado da Jettax é inválido.") from exc


def _converter_xml(tipo: TipoDocumentoFiscal, xml: bytes, identificador: str, cnpj: str) -> DocumentoBaixado:
    # Os conversores já consolidados do NotasFlow são namespace-agnósticos e
    # extraem chave, valor, emitente, destinatário e competência do XML. A
    # Jettax devolve o mesmo XML fiscal, apenas gzip+base64.
    if tipo == TipoDocumentoFiscal.NFE:
        resultado = ImportadorNFeSEFAZ()._converter(identificador, "procNFe", xml, cnpj)
    else:
        raise ValueError("Conversão XML Jettax indisponível para este tipo.")
    if resultado is None:
        raise ValueError("Não foi possível extrair a chave fiscal do XML Jettax.")
    return resultado


def _itens_para_execucao(cliente: ClienteJettax, empresa: Empresa, execucao: JettaxExecucao, filtros: dict[str, Any], cursor: str | None) -> list[dict[str, Any]]:
    if execucao.tipo == TipoDocumentoFiscal.NFSE:
        return cliente.listar_nfse(
            empresa.cnpj_cpf,
            last_id=cursor if execucao.avancar_cursor else None,
            numero=filtros.get("numero"),
            nota_situacao=filtros.get("nota_situacao"),
            tipo_nota=filtros.get("tipo_nota"),
            period=filtros.get("period"),
        )
    if execucao.tipo == TipoDocumentoFiscal.NFE:
        return cliente.listar_nfes(
            empresa.cnpj_cpf,
            execucao.fluxo,
            ultimo_id=cursor if execucao.avancar_cursor else None,
            chave=filtros.get("chave"),
            data_inicial=_para_data(filtros.get("data_inicial")),
            data_final=_para_data(filtros.get("data_final")),
            cnpj_destinatario=filtros.get("cnpj_destinatario"),
            cnpj_emitente=filtros.get("cnpj_emitente"),
        )
    raise JettaxErro("Tipo Jettax não suportado.", categoria="configuracao")


def executar_importacao(db: Session, execucao_id: int, filtros: dict[str, Any] | None = None) -> None:
    """Executa uma importação já enfileirada e atualiza o cursor só no commit."""
    execucao = db.get(JettaxExecucao, execucao_id)
    if execucao is None or execucao.status in {"concluida", "concluida_com_avisos"}:
        return
    empresa = db.get(Empresa, execucao.empresa_id)
    configuracao = db.query(JettaxConfiguracaoEmpresa).filter_by(empresa_id=execucao.empresa_id).first()
    agora = datetime.now(timezone.utc)
    if empresa is None or configuracao is None:
        if execucao is not None:
            execucao.status = "erro"
            execucao.mensagem_erro = "Empresa ou configuração Jettax não encontrada."
            execucao.finalizado_em = agora
            db.commit()
        return

    try:
        cursor = cursor_para(configuracao, execucao.tipo, execucao.fluxo)
        execucao.cursor_antes = cursor
        itens = _itens_para_execucao(ClienteJettax(), empresa, execucao, filtros or {}, cursor)
        proximo_cursor = _maior_cursor(itens, cursor)
        erros: list[str] = []
        criados = duplicados = ignorados = 0
        for item in itens:
            try:
                identificador = _texto(_campo(item, "id", "ultimoId", "lastId"), 100)
                if not identificador:
                    raise ValueError("Documento Jettax sem identificador do fornecedor.")
                if execucao.tipo == TipoDocumentoFiscal.NFSE:
                    criou = _persistir_nfse_metadados(db, empresa, item)
                else:
                    xml = _xml_gzip_base64(item)
                    documento = _converter_xml(execucao.tipo, xml, identificador, empresa.cnpj_cpf)
                    criou = _persistir_xml(
                        db, empresa.id, execucao.tipo, documento, identificador_externo=identificador
                    )
                if criou:
                    criados += 1
                else:
                    duplicados += 1
            except (ValueError, RuntimeError) as exc:
                ignorados += 1
                erros.append(_texto(str(exc), 180))

        execucao.documentos_importados = criados
        execucao.documentos_duplicados = duplicados
        execucao.documentos_ignorados = ignorados
        execucao.cursor_depois = proximo_cursor if not erros else cursor
        execucao.aviso = "\n".join(erros[:20]) or None
        # Cursor nunca avança diante de item não persistido: repetir duplicados
        # é seguro; perder uma nota por avançar um cursor quebrado não é.
        if execucao.avancar_cursor and not erros and proximo_cursor and proximo_cursor != cursor:
            atualizar_cursor(configuracao, execucao.tipo, execucao.fluxo, proximo_cursor)
        configuracao.ultima_sincronizacao_em = agora
        configuracao.ultimo_erro = None if not erros else f"{ignorados} item(ns) ignorado(s) nesta consulta."
        configuracao.falhas_seguidas = 0 if not erros else (configuracao.falhas_seguidas or 0) + 1
        configuracao.travado_em = None
        execucao.status = "concluida_com_avisos" if erros else "concluida"
        execucao.finalizado_em = agora
        db.commit()
    except JettaxErro as exc:
        execucao.status = "erro"
        execucao.mensagem_erro = _texto(str(exc), _MAX_TEXTO_ERRO)
        execucao.finalizado_em = agora
        configuracao.ultimo_erro = execucao.mensagem_erro
        configuracao.falhas_seguidas = (configuracao.falhas_seguidas or 0) + 1
        configuracao.travado_em = None
        db.commit()
    except Exception:  # noqa: BLE001 - nunca deixar uma execução/trava zumbi
        db.rollback()
        execucao = db.get(JettaxExecucao, execucao_id)
        configuracao = db.query(JettaxConfiguracaoEmpresa).filter_by(empresa_id=empresa.id).first()
        if execucao is not None:
            execucao.status = "erro"
            execucao.mensagem_erro = "Falha interna ao processar a resposta da Jettax."
            execucao.finalizado_em = datetime.now(timezone.utc)
        if configuracao is not None:
            configuracao.ultimo_erro = "Falha interna ao processar a resposta da Jettax."
            configuracao.falhas_seguidas = (configuracao.falhas_seguidas or 0) + 1
            configuracao.travado_em = None
        db.commit()
