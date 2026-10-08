"""Mede a largura mínima declarada das tabelas do Fluxa, a partir do código.

Sem navegador não há como medir pixel na tela; o que dá para medir com precisão
é o piso que cada coluna impõe — `largura` explícita ou o padrão de
`components/ui/Tabela.tsx` (`min-w-32` numérica, `min-w-24` de texto) — somado
ao padding de célula (`px-3` = 24px) e às colunas fixas de seleção/ações.

Uso: python3 scripts/medir_tabelas.py   (raiz: frontend/)
"""

from __future__ import annotations

import re
from pathlib import Path

# Tailwind: 1 unidade de espaçamento = 4px.
ESPACO = 4
PADDING_CELULA = 24  # px-3
COLUNA_SELECAO = 40  # w-10 + px-2


def px(classe: str) -> int:
    """min-w-28 → 112, w-16 → 64, min-w-[14rem] → 224."""
    rem = re.fullmatch(r"(?:min-)?w-\[(\d+(?:\.\d+)?)rem\]", classe)
    if rem:
        return round(float(rem.group(1)) * 16)
    conta = re.fullmatch(r"(?:min-)?w-(\d+)", classe)
    if conta:
        return int(conta.group(1)) * ESPACO
    return 0


def largura_minima(classe: str) -> int:
    return max((px(parte) for parte in classe.split()), default=0)


def colunas_do_arquivo(caminho: Path) -> list[dict]:
    """Lê o array `colunas` de uma tela: id, largura, flags e numerica."""
    texto = caminho.read_text(encoding="utf-8")
    inicio = texto.find("const colunas")
    if inicio < 0:
        return []
    trecho = texto[inicio:]
    colunas: list[dict] = []
    for bloco in re.split(r"\n      \{\n", trecho):
        id_coluna = re.search(r'id: "([^"]+)"', bloco)
        if not id_coluna:
            continue
        largura = re.search(r'largura: "([^"]+)"', bloco)
        colunas.append(
            {
                "id": id_coluna.group(1),
                "largura": largura.group(1) if largura else None,
                "numerica": bool(re.search(r"numerica: true", bloco)),
                "oculta": bool(re.search(r"ocultaPorPadrao: true", bloco)),
                "fixa": bool(re.search(r"\n        fixa: true", bloco)),
            }
        )
        if "];" in bloco[: bloco.find("celula")] if "celula" in bloco else False:
            break
        if len(colunas) > 20:
            break
    return colunas


def medir(caminho: Path, selecao: bool) -> tuple[int, list[str]]:
    total = COLUNA_SELECAO if selecao else 0
    linhas = []
    for coluna in colunas_do_arquivo(caminho):
        if coluna["oculta"] and not coluna["fixa"]:
            continue
        classe = coluna["largura"] or ("min-w-32" if coluna["numerica"] else "min-w-24")
        largura = largura_minima(classe) + PADDING_CELULA
        total += largura
        linhas.append(f"  {coluna['id']:<14} {classe:<12} {largura:>4}px")
    return total, linhas


def main() -> None:
    raiz = Path(__file__).resolve().parent.parent
    telas = [
        ("Documentos", raiz / "app/dashboard/documentos/Documentos.tsx", True),
        ("Empresas", raiz / "app/dashboard/empresas/Empresas.tsx", False),
        ("Execuções", raiz / "app/dashboard/execucoes/Execucoes.tsx", False),
        ("Certificados", raiz / "app/dashboard/certificados/Certificados.tsx", False),
        ("Usuários", raiz / "app/dashboard/usuarios/Usuarios.tsx", False),
        ("Auditoria", raiz / "app/dashboard/auditoria/Auditoria.tsx", False),
    ]
    # Larguras úteis de conteúdo: viewport − sidebar (256) − padding (lg:px-8 = 64).
    larguras = {1280: 960, 1366: 1046, 1440: 1120, 1920: 1600}

    for nome, caminho, selecao in telas:
        if not caminho.exists():
            print(f"{nome}: arquivo não encontrado ({caminho})")
            continue
        total, linhas = medir(caminho, selecao)
        print(f"\n{nome} — piso declarado: {total}px (padrão: conteúdo 1600px)")
        print("\n".join(linhas))
        for viewport, util in sorted(larguras.items()):
            limite = min(util, 1600)
            situacao = "cabe" if total <= limite else f"rola {total - limite}px"
            print(f"  {viewport}px de tela → {limite}px úteis: {situacao}")


if __name__ == "__main__":
    main()
