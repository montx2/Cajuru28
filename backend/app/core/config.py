from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuração central. Tudo vem do .env — nenhum segredo fica hardcoded
    ou versionado no código.
    """

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    database_url: str = "postgresql://notasflow:notasflow@db:5432/notasflow"
    redis_url: str = "redis://redis:6379/0"

    secret_key: str = "troque-esta-chave-em-producao"
    access_token_expire_minutes: int = 480
    algorithm: str = "HS256"

    vault_master_key: str = ""

    dados_dir: str = "/data"

    # Origens permitidas no CORS (separadas por vírgula). Em Docker local o
    # painel sobe em :3000; em preview remoto acrescente a URL do front.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Ambiente fiscal dos importadores: "producao" | "homologacao"
    ambiente_fiscal: str = "producao"


settings = Settings()
