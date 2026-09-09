from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuração central. Tudo vem do .env — nenhum segredo fica hardcoded
    ou versionado no código.
    """

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    database_url: str
    redis_url: str

    secret_key: str
    access_token_expire_minutes: int = 480
    algorithm: str = "HS256"

    vault_master_key: str

    dados_dir: str = "/data"


settings = Settings()
