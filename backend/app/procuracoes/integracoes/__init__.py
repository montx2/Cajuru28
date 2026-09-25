"""
Portas e adaptadores das fontes de situação de procuração.

O módulo nunca fala com um fornecedor específico: fala com `FonteProcuracoes`.
Trocar a origem remota — ou somar outra — é registrar outro adaptador, não
reescrever a sincronização. Origens sem API (como a lista do painel Jettax)
entram pelas fontes de texto (`planilha.py`), sem credencial.
"""
