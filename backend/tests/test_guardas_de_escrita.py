"""Rede de segurança do controle de acesso (item A14 da auditoria).

A auditoria verificou que **hoje** todas as rotas de escrita relevantes exigem
`requer_escrita` ou `requer_papel(...)` — direto na assinatura ou por alias de
módulo (`SoAdmin = Depends(requer_papel("admin"))`). O que faltava era a trava
para o futuro: nada impedia que uma rota nova nascesse sem a guarda e só
falhasse na auditoria seguinte.

Este teste percorre a árvore de rotas do app (incluindo os routers aninhados do
FastAPI novo) e falha se alguma rota de escrita nova aparecer sem guarda. As
exceções são explícitas e justificadas uma a uma — incluir uma nova aqui é uma
decisão consciente, não um acidente.
"""

from __future__ import annotations

from fastapi.routing import APIRoute

from app.main import app

METODOS_DE_ESCRITA = {"POST", "PUT", "PATCH", "DELETE"}

# Rotas de escrita que NÃO precisam de guarda de escrita, por decisão:
# - sessão: login/renovação/logout acontecem antes (ou independentemente) de
#   existir usuário autenticado;
# - prévia de seleção: um POST por tamanho de corpo, mas só lê e devolve o que
#   seria exportado — não grava nada;
# - stubs desktop: respondem 409 (_somente_docker) em qualquer ambiente, então
#   não há o que proteger. Continuam aqui para que trocar um stub por
#   implementação real exija remover a exceção de propósito.
ROTAS_SEM_GUARDA_JUSTIFICADAS = {
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/renovar"),
    ("POST", "/importacoes/selecionadas/previa"),
    ("POST", "/sistema/abrir-pasta"),
    ("POST", "/sistema/atualizacao/verificar"),
    ("POST", "/sistema/encerrar"),
    ("POST", "/sistema/iniciar-com-windows"),
}


def _rotas(obj) -> list[APIRoute]:
    """APIRoutes do app, descendo nos routers aninhados do FastAPI."""
    if isinstance(obj, APIRoute):
        return [obj]
    contexto = getattr(obj, "include_context", None)
    if contexto is not None and getattr(contexto, "included_router", None) is not None:
        return _rotas(contexto.included_router)
    encontradas: list[APIRoute] = []
    for filho in getattr(obj, "routes", []) or []:
        encontradas.extend(_rotas(filho))
    return encontradas


def _dependencias(dependencia, achados: set[str]) -> None:
    chamavel = getattr(dependencia, "call", None)
    if chamavel is not None:
        achados.add(getattr(chamavel, "__qualname__", str(chamavel)))
    for filha in dependencia.dependencies:
        _dependencias(filha, achados)


def _exige_escrita(rota: APIRoute) -> bool:
    nomes: set[str] = set()
    _dependencias(rota.dependant, nomes)
    return any("requer_escrita" in nome or "requer_papel" in nome for nome in nomes)


def test_toda_rota_de_escrita_exige_permissao() -> None:
    faltando: list[tuple[str, str]] = []
    for rota in _rotas(app):
        metodos = rota.methods & METODOS_DE_ESCRITA
        if not metodos or _exige_escrita(rota):
            continue
        for metodo in sorted(metodos):
            if (metodo, rota.path) not in ROTAS_SEM_GUARDA_JUSTIFICADAS:
                faltando.append((metodo, rota.path))

    assert not faltando, (
        "Rota(s) de escrita sem requer_escrita/requer_papel na assinatura: "
        + ", ".join(f"{metodo} {caminho}" for metodo, caminho in sorted(faltando))
        + ". Adicione a guarda ou justifique a exceção em ROTAS_SEM_GUARDA_JUSTIFICADAS "
        "(e explique no comentário do módulo)."
    )


def test_a_arvore_de_rotas_e_percorrida_de_verdade() -> None:
    """Se o FastAPI mudar a forma de aninhar routers, o teste acima viraria vazio."""
    escritas = [
        rota for rota in _rotas(app) if rota.methods & METODOS_DE_ESCRITA
    ]
    assert len(escritas) >= 30, (
        "Poucas rotas de escrita encontradas: o percurso da árvore de rotas "
        "quebrou (FastAPI mudou?) e a rede de segurança passou a não ver nada."
    )
