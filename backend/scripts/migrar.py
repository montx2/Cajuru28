"""
Migra um banco existente para o schema atual (colunas/status de cancelamento).

O startup da API já chama isto automaticamente; este script serve para rodar
antes do deploy ou quando quiser executar manualmente:

    docker compose exec api python scripts/migrar.py
"""

from app.db.base import criar_tabelas


def main() -> None:
    criar_tabelas()
    print("[migrar] OK — banco atualizado; tabelas novas criadas e colunas novas adicionadas.")


if __name__ == "__main__":
    main()
