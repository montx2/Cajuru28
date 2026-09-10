"""
Conexão com o banco.

Dois bancos, um código:

- **PostgreSQL** — implantação em servidor (Docker Compose), vários usuários
  simultâneos, um banco central para o escritório inteiro;
- **SQLite** — usado apenas nos testes automatizados. É o mesmo schema e as mesmas consultas; o que muda é que o arquivo
  precisa ser configurado para aguentar **escrita concorrente de várias
  threads** (a API responde enquanto o worker grava XML em paralelo).

O ajuste que faz o SQLite se comportar aqui é o trio WAL + busy_timeout +
`synchronous=NORMAL`:

- **WAL** (write-ahead log) permite leitura e escrita ao mesmo tempo — sem ele,
  uma gravação bloqueia toda leitura e a tela trava do nada;
- **busy_timeout** faz a segunda escrita *esperar* em vez de falhar com
  "database is locked" (erro clássico de quem só testou o SQLite com um
  usuário);
- **synchronous=NORMAL** é a recomendação oficial do SQLite com WAL: mantém a
  durabilidade contra queda do processo e troca um ganho grande de velocidade
  por um risco pequeno e aceitável (queda de energia) em um arquivo que o
  próprio usuário faz backup.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

_OPCOES: dict = {"pool_pre_ping": True}

if settings.usando_sqlite:
    _OPCOES["connect_args"] = {
        # A API atende em várias threads e o pool empresta conexões entre elas;
        # sem isso o sqlite3 recusa ("SQLite objects created in a thread...").
        "check_same_thread": False,
        # Tempo (em segundos) que uma escrita espera antes de desistir. É o
        # mesmo papel do busy_timeout, em duas camadas — cinto e suspensório.
        "timeout": 30.0,
    }

engine = create_engine(settings.database_url, **_OPCOES)


if settings.usando_sqlite:

    @event.listens_for(engine, "connect")
    def _configurar_sqlite(conexao, _registro):  # pragma: no cover - depende do driver
        cursor = conexao.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            # Chaves estrangeiras ligadas: o SQLite ignora isso por padrão, e
            # o cascade de certificados/execuções depende disso.
            cursor.execute("PRAGMA foreign_keys=ON")
            # Guarda em memória ~8 MB de índice: o filtro por competência usa
            # o índice o tempo todo.
            cursor.execute("PRAGMA cache_size=-8000")
        finally:
            cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
