"""
Consulta pública de CNPJ para completar cadastro de empresas.

A UF da empresa é necessária para NFe/CT-e (cUFAutor). Antes o operador
precisava escolher isso manualmente; agora o sistema tenta buscar a UF no
cadastro público do CNPJ e só pede preenchimento manual se a consulta externa
não responder.

A consulta é sempre *melhor esforço*: indisponibilidade, 404, timeout ou campo
faltando não derrubam a tela — apenas voltam como "não encontrado" para a API
poder pedir a UF manualmente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import httpx


@dataclass(frozen=True)
class DadosCNPJ:
    documento: str
    razao_social: str = ""
    nome_fantasia: str = ""
    uf: str = ""
    municipio: str = ""
    fonte: str = "BrasilAPI"


def apenas_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


@lru_cache(maxsize=2048)
def consultar_cnpj(cnpj: str) -> DadosCNPJ | None:
    """
    Retorna dados cadastrais básicos do CNPJ ou ``None``.

    Usa BrasilAPI porque é pública e não exige chave. O timeout curto evita que
    um serviço externo instável deixe o cadastro lento; o operador ainda pode
    informar a UF manualmente quando a busca não estiver disponível.
    """
    documento = apenas_digitos(cnpj)
    if len(documento) != 14:
        return None

    url = f"https://brasilapi.com.br/api/cnpj/v1/{documento}"
    try:
        with httpx.Client(timeout=5.0) as client:
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
    if not (uf or razao or fantasia):
        return None
    return DadosCNPJ(
        documento=documento,
        razao_social=razao,
        nome_fantasia=fantasia,
        uf=uf,
        municipio=municipio,
    )
