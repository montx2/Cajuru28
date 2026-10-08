"""
Mascaramento e redação de dados sensíveis.

Função transversal de segurança: é usada pela trilha de auditoria, pelos logs
estruturados, pelos relatórios exportados e pelo diagnóstico. Uma função transversal como esta precisa de lugar óbvio, para evitar que
cada módulo reimplemente a sua própria versão (e esqueça uma chave).

Duas operações distintas, que não devem ser confundidas:

- `sanitizar()` — **redige**: a chave sensível some do dicionário, substituída
  por `[redigido]`. Usada antes de persistir ou logar qualquer contexto
  técnico. É irreversível de propósito.
- `mascarar_documento()` / `mascarar_serial()` — **ofusca parcialmente**:
  mantém o suficiente para uma pessoa reconhecer o registro na tela sem
  expor o dado inteiro. Usado em relatório e exibição.

Regra que não muda: senha, PIN e chave privada não têm versão mascarada.
Eles não aparecem — nem parcialmente, nem em relatório, nem em tela.
"""

from __future__ import annotations

from typing import Any, Mapping

#: Chaves que nunca podem ser persistidas nem logadas, venham de onde vierem.
#: A comparação é por substring em minúsculas com `-` normalizado para `_`,
#: então `X-Auth-Token`, `clientSecret` e `senha_do_certificado` caem todos
#: no filtro sem precisar estar listados um a um.
CHAVES_PROIBIDAS: frozenset[str] = frozenset(
    {
        "senha",
        "password",
        "passwd",
        "pin",
        "pfx",
        "p12",
        "chave_privada",
        "private_key",
        "privatekey",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "bearer",
        "authorization",
        "cookie",
        "cookies",
        "set-cookie",
        "secret",
        "segredo",
        "consumer_secret",
        "client_secret",
        "senha_certificado",
        "credencial",
        "credential",
        "hmac",
        "assinatura_hmac",
        "api_key",
        "apikey",
        "chave_mestra",
        "master_key",
    }
)

#: Marcador único. Grepável: se isso aparecer num relatório entregue ao
#: cliente, é porque a redação funcionou — e não que faltou dado.
REDIGIDO = "[redigido]"

_PROFUNDIDADE_MAXIMA = 6
_LIMITE_TEXTO = 500
_LIMITE_LISTA = 50


def _chave_e_sensivel(chave: Any) -> bool:
    normalizada = str(chave).lower().replace("-", "_")
    return any(proibida in normalizada for proibida in CHAVES_PROIBIDAS)


def sanitizar(dados: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove chaves sensíveis em qualquer profundidade e limita o tamanho.

    O limite de profundidade e de tamanho não é estético: um contexto técnico
    vindo de uma estação é entrada não confiável, e um dicionário
    auto-referente ou gigante viraria um `INSERT` de megabytes na trilha.
    """
    if not dados:
        return {}

    def _limpar(valor: Any, profundidade: int = 0) -> Any:
        if profundidade > _PROFUNDIDADE_MAXIMA:
            return "…"
        if isinstance(valor, Mapping):
            saida: dict[str, Any] = {}
            for chave, item in valor.items():
                texto_chave = str(chave)
                if _chave_e_sensivel(texto_chave):
                    saida[texto_chave] = REDIGIDO
                    continue
                saida[texto_chave] = _limpar(item, profundidade + 1)
            return saida
        if isinstance(valor, (list, tuple)):
            return [_limpar(item, profundidade + 1) for item in valor[:_LIMITE_LISTA]]
        if isinstance(valor, str):
            return valor[:_LIMITE_TEXTO]
        if isinstance(valor, (int, float, bool)) or valor is None:
            return valor
        return str(valor)[:_LIMITE_TEXTO]

    return _limpar(dict(dados))


def mascarar_documento(documento: str | None) -> str:
    """CNPJ/CPF com o miolo oculto, preservando início e fim.

    Por que preservar as pontas: o operador precisa conferir na tela que está
    olhando a empresa certa, e os dígitos verificadores finais são o que ele
    usa para isso. Ocultar tudo transformaria o relatório em uma lista de
    linhas indistinguíveis.

    >>> mascarar_documento("12345678000199")
    '12.***.***/0001-99'
    >>> mascarar_documento("11122233344")
    '111.***.***-44'
    """
    digitos = "".join(caractere for caractere in str(documento or "") if caractere.isdigit())
    if len(digitos) == 14:
        return f"{digitos[:2]}.***.***/{digitos[8:12]}-{digitos[12:]}"
    if len(digitos) == 11:
        return f"{digitos[:3]}.***.***-{digitos[9:]}"
    if len(digitos) > 4:
        return f"{digitos[:2]}{'*' * (len(digitos) - 4)}{digitos[-2:]}"
    return "*" * len(digitos)


def mascarar_serial(valor: str | None) -> str:
    """Número de série / thumbprint: mantém os 8 últimos caracteres.

    Oito caracteres bastam para distinguir dois certificados da mesma empresa
    numa tela de desempate, e não bastam para identificar o certificado fora
    do contexto do escritório.
    """
    texto = str(valor or "").strip()
    if len(texto) <= 8:
        return texto
    return f"…{texto[-8:]}"


__all__ = [
    "CHAVES_PROIBIDAS",
    "REDIGIDO",
    "sanitizar",
    "mascarar_documento",
    "mascarar_serial",
]
