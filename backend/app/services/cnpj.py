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


@lru_cache(maxsize=2048)
def consultar_cnpj(cnpj: str) -> DadosCNPJ | None:
    """Consulta a BrasilAPI apenas quando o contrato numérico é aplicável.

    Retorna ``None`` para valor inválido, CPF ou CNPJ alfanumérico. Assim a UI
    pede razão social/UF manualmente em vez de transformar uma empresa em outra
    por um suposto "só dígitos".
    """
    try:
        documento = normalizar_cnpj(cnpj)
    except ValueError:
        return None
    if not eh_cnpj_numerico(documento):
        return None

    url = f"https://brasilapi.com.br/api/cnpj/v1/{documento}"
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as client:
            resposta = client.get(url, headers={"Accept": "application/json"})
        if resposta.status_code == 404:
            return None
        resposta.raise_for_status()
        dados = resposta.json()
    except Exception:  # noqa: BLE001 - consulta externa é opcional
        return None

    uf = str(dados.get("uf") or "").strip().upper()
    razao = str(dados.get("razao_social") or dados.get("nome") or "").strip()
    fantasia = str(dados.get("nome_fantasia") or "").strip()
    municipio = str(dados.get("municipio") or "").strip()
    # BrasilAPI expõe o código de sete dígitos sob codigo_municipio_ibge.
    # Não confundir com codigo_municipio/TOM, que é outro cadastro.
    codigo_ibge = "".join(caractere for caractere in str(dados.get("codigo_municipio_ibge") or "") if caractere.isdigit())
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
    )
