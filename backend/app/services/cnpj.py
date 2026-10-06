"""Consulta pública de CNPJ para completar cadastros numéricos legados.

A BrasilAPI documenta a rota pública atual somente para CNPJ numérico. CNPJ
alfanumérico continua sendo um identificador local perfeitamente válido, mas
não pode ser convertido por remoção de letras nem enviado a uma fonte cujo
contrato ainda não confirma esse formato.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import httpx

from app.core.documentos import eh_cnpj_numerico, normalizar_cnpj


@dataclass(frozen=True)
class DadosCNPJ:
    documento: str
    razao_social: str = ""
    nome_fantasia: str = ""
    uf: str = ""
    municipio: str = ""
    codigo_ibge: str = ""
    fonte: str = "BrasilAPI"


_CACHE: dict[str, DadosCNPJ] = {}
_CACHE_MAX = 2048


def _extrair_padrao_brasilapi(documento: str, dados: dict, fonte: str) -> DadosCNPJ | None:
    uf = str(dados.get("uf") or "").strip().upper()
    razao = str(dados.get("razao_social") or dados.get("nome") or "").strip()
    fantasia = str(dados.get("nome_fantasia") or "").strip()
    razao = razao or fantasia
    municipio = str(dados.get("municipio") or "").strip()
    # BrasilAPI e MinhaReceita expõem o código de sete dígitos sob codigo_municipio_ibge.
    # Não confundir com codigo_municipio/TOM, que é outro cadastro.
    codigo_ibge = "".join(
        caractere for caractere in str(dados.get("codigo_municipio_ibge") or "") if caractere.isdigit()
    )
    if len(codigo_ibge) != 7:
        codigo_ibge = ""
    if not (uf or razao or fantasia):
        return None
    return DadosCNPJ(
        documento=documento,
        razao_social=razao,
        nome_fantasia=fantasia,
        uf=uf,
        municipio=municipio,
        codigo_ibge=codigo_ibge,
        fonte=fonte,
    )


def _extrair_cnpj_ws(documento: str, dados: dict) -> DadosCNPJ | None:
    estabelecimento = dados.get("estabelecimento")
    if not isinstance(estabelecimento, dict):
        estabelecimento = {}
    estado = estabelecimento.get("estado")
    if not isinstance(estado, dict):
        estado = {}
    cidade = estabelecimento.get("cidade")
    if not isinstance(cidade, dict):
        cidade = {}

    uf = str(estado.get("sigla") or dados.get("uf") or "").strip().upper()
    razao = str(dados.get("razao_social") or "").strip()
    fantasia = str(estabelecimento.get("nome_fantasia") or dados.get("nome_fantasia") or "").strip()
    razao = razao or fantasia
    municipio = str(cidade.get("nome") or "").strip()
    codigo_ibge = "".join(
        caractere for caractere in str(cidade.get("ibge_id") or "") if caractere.isdigit()
    )
    if len(codigo_ibge) != 7:
        codigo_ibge = ""
    if not (uf or razao or fantasia):
        return None
    return DadosCNPJ(
        documento=documento,
        razao_social=razao,
        nome_fantasia=fantasia,
        uf=uf,
        municipio=municipio,
        codigo_ibge=codigo_ibge,
        fonte="CNPJ.ws",
    )


def consultar_cnpj(cnpj: str) -> DadosCNPJ | None:
    """Consulta fontes públicas de CNPJ apenas quando o contrato numérico é aplicável.

    Retorna ``None`` para valor inválido, CPF ou CNPJ alfanumérico. Assim a UI
    pede razão social/UF manualmente em vez de transformar uma empresa em outra
    por um suposto "só dígitos". Falhas temporárias (timeout, 429) não ficam em
    cache para não travar novas tentativas do operador.
    """
    try:
        documento = normalizar_cnpj(cnpj)
    except ValueError:
        return None
    if not eh_cnpj_numerico(documento):
        return None

    em_cache = _CACHE.get(documento)
    if em_cache is not None:
        return em_cache

    fontes = (
        (f"https://brasilapi.com.br/api/cnpj/v1/{documento}", "BrasilAPI", _extrair_padrao_brasilapi),
        (f"https://minhareceita.org/{documento}", "MinhaReceita", _extrair_padrao_brasilapi),
        (f"https://publica.cnpj.ws/cnpj/{documento}", "CNPJ.ws", None),
    )

    melhor_parcial: DadosCNPJ | None = None
    try:
        with httpx.Client(timeout=5.0, follow_redirects=True) as client:
            for url, nome_fonte, extrator in fontes:
                try:
                    resposta = client.get(url, headers={"Accept": "application/json", "User-Agent": "NotasFlow/1.0"})
                    if resposta.status_code != 200:
                        continue
                    dados = resposta.json()
                    if not isinstance(dados, dict):
                        continue
                    resultado = (
                        extrator(documento, dados, nome_fonte)
                        if extrator is not None
                        else _extrair_cnpj_ws(documento, dados)
                    )
                    if resultado is None:
                        continue
                    if resultado.uf:
                        if len(_CACHE) >= _CACHE_MAX:
                            _CACHE.pop(next(iter(_CACHE)))
                        _CACHE[documento] = resultado
                        return resultado
                    if melhor_parcial is None:
                        melhor_parcial = resultado
                except Exception:  # noqa: BLE001 - consulta externa é opcional; tenta próxima fonte
                    continue
    except Exception:  # noqa: BLE001
        return melhor_parcial

    return melhor_parcial


consultar_cnpj.cache_clear = _CACHE.clear  # type: ignore[attr-defined]
