from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings

# SQLite precisa de check_same_thread=False para funcionar com threads (desktop mode)
# e StaticPool para evitar problemas de conexão em modo arquivo único
if settings.database_url.strip().lower().startswith("sqlite"):
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool if ":memory:" in settings.database_url else None,
    )
else:
    engine = create_engine(settings.database_url, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_engine():
    """Para uso em migrações e scripts que precisam do engine atual"""
    return engine
