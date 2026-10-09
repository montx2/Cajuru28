"""Cadastro da empresa pelo CNPJ: Acessórias primeiro, fonte pública depois.

A importação em massa de certificados precisa de dois dados que o `.pfx` nem
sempre entrega: a **razão social** e a **UF**. Antes, a consulta externa só
acontecia quando a UF estava faltando — de modo que um lote com a UF na
planilha guardava o nome que o certificado trazia (e um A1 traz, quase sempre,
a marca da cadeia: "ICP-Brasil"). Um lote de 203 certificados virou 203
empresas com o mesmo nome.

A precedência aqui é a que o escritório espera:

1. **Acessórias** — o cadastro do próprio escritório é a fonte mais atual e é
   onde a razão social já está conferida com o contrato social;
2. **Fontes públicas da Receita** (BrasilAPI → MinhaReceita → CNPJ.ws) — para
   quem ainda não está no Acessórias. Como a consulta pública é o que também
   entrega a UF, a mesma chamada preenche os dois campos.

Resultados são cacheados por escritório+CNPJ (inclusive os "não achei") para um
lote grande não esgotar o limite de 100 requisições/minuto do Acessórias.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.documentos import normalizar_documento
from app.core.nomes import nome_usavel

UFS_VALIDAS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)

# Sucesso vale um dia; ausência vale pouco tempo, para que uma empresa
# cadastrada no Acessórias cinco minutos depois apareça na próxima importação
# sem exigir reinício do processo.
_TTL_SUCESSO = 24 * 3600.0
_TTL_VAZIO = 15 * 60.0
# Depois de uma falha de rede/limite, o Acessórias fica de fora por ~2 minutos:
# 600 certificados batendo em 429 virariam 600 atrasos em cascata.
_PAUSA_ACESSORIAS = 120.0
_CACHE_MAX = 4096

_CADASTRO: dict[str, tuple[float, "CadastroEmpresa"]] = {}
_ACESSORIAS_PAUSADO_ATE: dict[int, float] = {}


@dataclass(frozen=True)
class CadastroEmpresa:
    """O que se sabe de uma empresa pelo CNPJ — e de onde veio."""

    documento: str
    razao_social: str = ""
    nome_fantasia: str = ""
    uf: str = ""
    municipio: str = ""
    codigo_ibge: str = ""
    fonte: str = ""

    @property
    def completo(self) -> bool:
        return bool(self.razao_social and self.uf)


def _chave(escritorio_id: int, documento: str) -> str:
    return f"{escritorio_id}:{documento}"


def _guardar(chave: str, valor: CadastroEmpresa | None, ttl: float) -> None:
    if len(_CADASTRO) >= _CACHE_MAX:
        for antiga in list(_CADASTRO)[: max(1, len(_CADASTRO) // 4)]:
            if antiga != chave:
                _CADASTRO.pop(antiga, None)
            if len(_CADASTRO) < _CACHE_MAX:
                break
    _CADASTRO[chave] = (time.monotonic() + ttl, valor)


def _recuperar(chave: str) -> tuple[bool, CadastroEmpresa | None]:
    guardado = _CADASTRO.get(chave)
    if guardado is None:
        return False, None
    expira, valor = guardado
    if expira < time.monotonic():
        _CADASTRO.pop(chave, None)
        return False, None
    return True, valor


def limpar_cache() -> None:
    """Esquece tudo — usado pelos testes e depois de trocar a credencial."""
    _CADASTRO.clear()
    _ACESSORIAS_PAUSADO_ATE.clear()


def _texto(valor: Any) -> str:
    return str(valor or "").strip()


def _do_acessorias(dados: dict[str, Any], documento: str) -> CadastroEmpresa:
    """Mapeia a ficha do Acessórias (`Razao`, `Fantasia`, `UF`) para o cadastro."""
    uf = _texto(dados.get("UF")).upper()
    return CadastroEmpresa(
        documento=documento,
        razao_social=nome_usavel(dados.get("Razao") or dados.get("Fantasia"), documento=documento),
        nome_fantasia=nome_usavel(dados.get("Fantasia"), documento=documento),
        uf=uf if uf in UFS_VALIDAS else "",
        fonte="Acessórias",
    )


def _mesclar(base: CadastroEmpresa | None, complemento: CadastroEmpresa | None) -> CadastroEmpresa | None:
    """Mantém o que a primeira fonte achou e completa o resto com a segunda."""
    if base is None:
        return complemento
    if complemento is None:
        return base
    return replace(
        base,
        razao_social=base.razao_social or complemento.razao_social,
        nome_fantasia=base.nome_fantasia or complemento.nome_fantasia,
        uf=base.uf or complemento.uf,
        municipio=base.municipio or complemento.municipio,
        codigo_ibge=base.codigo_ibge or complemento.codigo_ibge,
        fonte=f"{base.fonte} + {complemento.fonte}" if base.fonte != complemento.fonte else base.fonte,
    )


def _publica(consultar: Callable[[str], Any], documento: str) -> CadastroEmpresa | None:
    resultado = consultar(documento)
    if resultado is None:
        return None
    uf = _texto(getattr(resultado, "uf", "")).upper()
    return CadastroEmpresa(
        documento=documento,
        razao_social=nome_usavel(getattr(resultado, "razao_social", ""), documento=documento),
        nome_fantasia=nome_usavel(getattr(resultado, "nome_fantasia", ""), documento=documento),
        uf=uf if uf in UFS_VALIDAS else "",
        municipio=_texto(getattr(resultado, "municipio", "")),
        codigo_ibge=_texto(getattr(resultado, "codigo_ibge", "")),
        fonte=_texto(getattr(resultado, "fonte", "")) or "Receita",
    )


def _credencial(db: Session, escritorio_id: int) -> Any | None:
    from app.models import AcessoriasCredencial  # import local: serviços não dependem do ciclo api→models

    return db.query(AcessoriasCredencial).filter_by(escritorio_id=escritorio_id).first()


def acessorias_configurado(db: Session | None, escritorio_id: int) -> bool:
    """Há token de Acessórias para este escritório (sem verificar o valor)."""
    if db is None:
        return False
    return _credencial(db, escritorio_id) is not None


def cliente_acessorias(db: Session | None, escritorio_id: int) -> tuple[Any | None, str]:
    """Cliente autenticado do Acessórias deste escritório, ou ``None`` + motivo."""
    from app.services.acessorias import ClienteAcessorias

    if db is None:
        return None, "Sem conexão com o banco: o Acessórias não foi consultado."
    credencial = _credencial(db, escritorio_id)
    if credencial is None:
        return None, "O Acessórias não está configurado neste escritório."
    if _ACESSORIAS_PAUSADO_ATE.get(escritorio_id, 0.0) > time.monotonic():
        return None, "O Acessórias foi consultado demais nesta rodada e está sendo poupado."
    from app.core.vault import decifrar_segredo

    try:
        return ClienteAcessorias(credencial.base_url, decifrar_segredo(credencial.token_cifrado)), ""
    except Exception:  # noqa: BLE001 — credencial inválida não derruba a importação
        return None, "O token do Acessórias não pôde ser usado; foi tentada a fonte pública."


def _ficha_acessorias(
    cliente: Any | None, documento: str, *, escritorio_id: int = 0
) -> CadastroEmpresa | None:
    """Ficha do Acessórias para um CNPJ/CPF já normalizado, ou ``None``.

    Falha de rede, token recusado ou limite de 100 requisições/minuto pausam o
    Acessórias para o resto da rodada: melhor completar pela fonte pública do
    que segurar um lote inteiro esperando.
    """
    if cliente is None:
        return None
    from app.services.acessorias import AcessoriasErro

    try:
        ficha = cliente.obter_empresa(documento)
    except AcessoriasErro:
        if escritorio_id:
            _ACESSORIAS_PAUSADO_ATE[escritorio_id] = time.monotonic() + _PAUSA_ACESSORIAS
        return None
    return _do_acessorias(ficha, documento) if ficha else None


def consultar_cadastro(
    db: Session | None,
    escritorio_id: int,
    cnpj_cpf: str,
    *,
    consultar_publica: Callable[[str], Any] | None = None,
    forcar: bool = False,
    cliente: Any | None = ...,
    buscar_ibge: bool = False,
) -> CadastroEmpresa | None:
    """Razão social + UF de um CNPJ/CPF, começando pelo cadastro do escritório.

    Retorna ``None`` quando nem o Acessórias nem as fontes públicas disseram
    algo aproveitável — o chamador decide entre pedir o dado ao operador ou
    manter o nome provisório do certificado.

    `cliente` existe para uma rota que resolve muitos CNPJs de uma vez (o
    reparo de cadastros) reusar a mesma conexão autenticada; passe `None` para
    dispensar o Acessórias de propósito. A fonte pública é chamada quando o
    escritório não respondeu, quando respondeu incompleto, ou quando o chamador
    quer o código IBGE do município (`buscar_ibge`) — o Acessórias não expõe.
    """
    from app.services.cnpj import consultar_cnpj as consultar_cnpj_padrao

    try:
        documento = normalizar_documento(cnpj_cpf)
    except ValueError:
        return None

    chave = _chave(escritorio_id, documento)
    if not forcar:
        presente, guardado = _recuperar(chave)
        if presente:
            return guardado

    if cliente is ...:
        cliente, _motivo = cliente_acessorias(db, escritorio_id) if db is not None else (None, "")
    resultado = _ficha_acessorias(cliente, documento, escritorio_id=escritorio_id)

    if (
        resultado is None
        or not resultado.completo
        or (buscar_ibge and not resultado.codigo_ibge)
    ):
        publico = _publica(consultar_publica or consultar_cnpj_padrao, documento)
        if resultado is None:
            resultado = publico
        elif publico is not None:
            resultado = _mesclar(resultado, publico)

    if resultado is not None and (resultado.razao_social or resultado.uf):
        _guardar(chave, resultado, _TTL_SUCESSO)
        return resultado
    # Nada aproveitable. Um lote de 203 certificados não pode insistir em cada
    # linha: a ausência fica cacheada por um minuto curto o bastante para uma
    # empresa cadastrada no Acessórias entre uma rodada e outra aparecer.
    _guardar(chave, None, _TTL_VAZIO)
    return None
