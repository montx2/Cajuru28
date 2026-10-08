import os

from cryptography.fernet import Fernet

# Precisa estar setado ANTES de qualquer import de app.* (Settings lê do
# ambiente na importação do módulo).
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "chave-de-teste-nao-usar-em-producao")
os.environ.setdefault("VAULT_MASTER_KEY", Fernet.generate_key().decode())
os.environ.setdefault("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())

import pytest


@pytest.fixture(autouse=True)
def sem_cache_de_cadastro(monkeypatch):
    """Cada teste começa sem memória das consultas de CNPJ anteriores.

    Nome e UF por CNPJ são cacheados de propósito (um lote de 203 certificados
    não pode fazer 203 requisições por minuto ao Acessórias). Sem limpar entre
    testes, o CNPJ reusado de um teste devolve o resultado do anterior e o
    monkeypatch de `consultar_cnpj` passa a não ser chamado — o teste verde
    não estaria testando nada.
    """
    from app.services import cadastro, cnpj

    cadastro.limpar_cache()
    cnpj.consultar_cnpj.cache_clear()  # type: ignore[attr-defined]
    yield
    cadastro.limpar_cache()
    cnpj.consultar_cnpj.cache_clear()  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def fila_respondendo_nos_testes(monkeypatch):
    """
    Nos testes não existe broker: a checagem curta da fila diria "fora do ar"
    em toda chamada e nenhum caminho de enfileiramento seria exercitado.

    O comportamento da checagem tem teste próprio
    (`test_fila_fora_do_ar_nao_cria_execucao_nem_faz_nada_esperar`), que a
    desliga de propósito; aqui ela responde "sim" para o resto da suíte testar
    a decisão da fila, não a infraestrutura.
    """
    from app.services import fila

    monkeypatch.setattr(fila, "fila_respondendo", lambda: True)
