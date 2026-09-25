"""
Módulo **Procurações RFB** — governança das Autorizações de Acesso da Receita
Federal (antigas procurações eletrônicas).

Este pacote é o primeiro de uma família de módulos de automação fiscal do
Cajuru28. A fronteira é deliberada:

- `estados.py`      — máquina de estados, classificação de erro e política.
- `modelos.py`      — persistência (SQLAlchemy), isolada por escritório.
- `esquemas.py`     — contratos de entrada/saída (Pydantic), sem segredo.
- `servicos/`       — regras de negócio puras, testáveis sem HTTP.
- `integracoes/`    — portas e adaptadores para fontes externas.
- `api/`            — routers FastAPI (operador e Agent têm superfícies distintas).

Leia `docs/PROCURACOES_RFB.md` antes de alterar o fluxo: há restrição
normativa vigente (IN RFB nº 2.320/2026) sobre automação do ato de outorga.
"""
