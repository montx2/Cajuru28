from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuração central. Tudo vem do .env — nenhum segredo fica hardcoded
    ou versionado no código.
    """

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    database_url: str = "postgresql://notasflow:notasflow@db:5432/notasflow"
    redis_url: str = "redis://redis:6379/0"

    # Modo desktop: quando True, usa SQLite local, fila em thread, sem Redis/Celery.
    # Ativado automaticamente pelo launcher Electron ou por DESKTOP_MODE=true no .env
    modo_desktop: bool = False
    desktop_mode: bool = False  # alias para compatibilidade com env var DESKTOP_MODE

    secret_key: str = "troque-esta-chave-em-producao"
    access_token_expire_minutes: int = 480
    algorithm: str = "HS256"

    vault_master_key: str = ""
    # Chaves usadas antes de uma rotação, separadas por vírgula. São aceitas
    # somente para decifrar certificados já gravados; novas senhas sempre
    # usam `vault_master_key`.
    vault_previous_master_keys: str = ""

    dados_dir: str = "/data"

    # Origens permitidas no CORS (separadas por vírgula).
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Ambiente fiscal dos importadores: "producao" | "homologacao"
    ambiente_fiscal: str = "producao"

    # ---------------- Consumo consciente (regras SEFAZ/ADN) ----------------
    # Regra oficial: depois de "nada novo" (cStat 137), aguardar 1 hora.
    cooldown_horas: int = 1
    # Margem extra: o relógio do ambiente nunca bate com o nosso e chegar
    # adiantado vale um novo bloqueio de 1h.
    margem_cooldown_minutos: int = 6
    # Consultas pontuais (consChNFe/consNSU): teto oficial de 20 por hora.
    limite_consultas_pontuais_por_hora: int = 20
    # Intervalo mínimo entre páginas do mesmo lote (recomendação sped-nfe: 2s).
    espera_entre_lotes_segundos: float = 2.0
    # Trava de segurança por varredura (o próprio sped-nfe recomenda 50).
    max_lotes_por_execucao: int = 50
    # Falha de rede/5xx: tentar de novo já (não queima cota), com teto.
    max_tentativas_transporte: int = 4
    # Documentos ficam disponíveis na distribuição por ~90 dias.
    dias_disponiveis_na_distribuicao: int = 90

    # ---------------- Automação (Celery Beat) ----------------
    # Com isso ligado ninguém precisa apertar botão: o agendador varre as
    # empresas dentro das janelas de consumo, sozinha, para sempre.
    sincronismo_automatico: bool = True
    sincronismo_intervalo_minutos: int = 5
    # Quantas empresas o agendador libera por varredura (dilui a carga e o
    # risco de bater no limite de consultas do certificado ao mesmo tempo).
    sincronismo_lote_empresas: int = 20
    # Recuperação dos XMLs que chegaram só em resumo (consChNFe): a cada quantas
    # horas o sistema gasta a cota de 20 consultas pontuais por CNPJ.
    completar_xmls_a_cada_horas: int = 6

    # ---------------- Celery ----------------
    # O broker Redis reentrega mensagens "em voo" mais velhas que isto. Precisa
    # ser maior que o maior countdown usado (bloqueio de ~1h + margem), senão o
    # reagendamento vira execução duplicada — e duplicata é 656 na certa.
    broker_visibility_timeout_segundos: int = 21600
    limite_tempo_task_segundos: int = 1800

    # ---------------- Download em massa ----------------
    limite_documentos_por_exportacao: int = 25000

    # Bootstrap do primeiro usuário (opcional). Se BOOTSTRAP_EMAIL e
    # BOOTSTRAP_SENHA estiverem preenchidos e não existir nenhum usuário,
    # a API cria o escritório + admin no startup.
    bootstrap_escritorio: str = "Escritorio Cajuru"
    bootstrap_nome: str = "Administrador"
    bootstrap_email: str = ""
    bootstrap_senha: str = ""

    @property
    def is_desktop(self) -> bool:
        """True se estiver rodando no modo desktop (Electron/.exe)"""
        return bool(self.modo_desktop or self.desktop_mode)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.strip().lower().startswith("sqlite")


settings = Settings()
# Compat: se DESKTOP_MODE=true mas MODO_DESKTOP não foi setado, espelha
if settings.desktop_mode and not settings.modo_desktop:
    settings.modo_desktop = True
# Se rodando com SQLite e sem Redis configurado explicitamente, assume desktop
if settings.is_sqlite and "sqlite" in settings.database_url:
    # não força modo_desktop automaticamente, mas facilita
    pass
