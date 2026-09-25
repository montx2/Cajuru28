"""Configuração central e validação de segurança por ambiente.

Configurações de desenvolvimento são convenientes; configurações de produção
precisam falhar fechadas. Este módulo mantém os dois cenários explícitos para
que um `.env` local nunca vire, por acidente, a configuração de um servidor
com dados fiscais reais.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict

# Endereços locais de desenvolvimento. A validação de produção abaixo rejeita
# todos eles; eles nunca são uma alternativa silenciosa para um deploy real.
_URL_BANCO_DESENVOLVIMENTO = "postgresql://notasflow:notasflow@db:5432/notasflow"
_URL_REDIS_DESENVOLVIMENTO = "redis://redis:6379/0"
_CHAVE_PADRAO_INSEGURA = "troque-esta-chave-em-producao"
_ARQUIVO_ENV = os.environ.get("NOTASFLOW_ENV_FILE", ".env")


class ErroConfiguracaoProducao(RuntimeError):
    """A implantação tentou iniciar sem os controles mínimos de produção."""


def _senha_da_url(url: str) -> str:
    try:
        return unquote(urlparse(url).password or "")
    except ValueError:
        return ""


class Settings(BaseSettings):
    """Tudo vem do ambiente/secret manager; nenhuma credencial é versionada."""

    model_config = SettingsConfigDict(
        env_file=_ARQUIVO_ENV, case_sensitive=False, extra="ignore"
    )

    # development = máquina local; test = suíte; production = servidor exposto.
    app_env: Literal["development", "test", "production"] = "development"

    database_url: str = _URL_BANCO_DESENVOLVIMENTO
    redis_url: str = _URL_REDIS_DESENVOLVIMENTO

    secret_key: str = _CHAVE_PADRAO_INSEGURA
    access_token_expire_minutes: int = 20
    algorithm: str = "HS256"
    jwt_issuer: str = "notasflow"
    jwt_audience: str = "notasflow-web"
    session_cookie_name: str = "notasflow_session"
    session_cookie_samesite: Literal["lax", "strict"] = "lax"

    vault_master_key: str = ""
    # Chaves usadas antes de uma rotação, separadas por vírgula. São aceitas
    # somente para decifrar dados já gravados; novas gravações usam a atual.
    vault_previous_master_keys: str = ""

    dados_dir: str = "/data"

    # Origens permitidas, separadas por vírgula. Não existe modo wildcard.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Hosts HTTP aceitos pela API (separados por vírgula). Em produção informe
    # o domínio público e o nome interno do serviço usado pelo proxy.
    trusted_hosts: str = "localhost,127.0.0.1,testserver"

    # Limites de abuso. Em produção o Redis é obrigatório para que o contador
    # seja compartilhado pelo processo da API; em dev/test há fallback local.
    rate_limit_ativo: bool = True
    rate_limit_login_por_minuto: int = 8
    rate_limit_login_por_hora: int = 30
    rate_limit_mutacoes_por_minuto: int = 120

    # Ambiente fiscal dos importadores: "producao" | "homologacao"
    ambiente_fiscal: str = "producao"

    # Observabilidade: produção usa JSON para permitir correlação entre API,
    # worker e proxy sem precisar acessar o banco manualmente.
    log_level: str = "INFO"
    log_json: bool = True

    # ---------------- Consumo consciente (regras SEFAZ/ADN) ----------------
    cooldown_horas: int = 1
    margem_cooldown_minutos: int = 6
    limite_consultas_pontuais_por_hora: int = 20
    espera_entre_lotes_segundos: float = 2.0
    max_lotes_por_execucao: int = 50
    max_tentativas_transporte: int = 4
    dias_disponiveis_na_distribuicao: int = 90

    # ---------------- Automação (Celery Beat) ----------------
    sincronismo_automatico: bool = True
    sincronismo_intervalo_minutos: int = 5
    sincronismo_lote_empresas: int = 20
    completar_xmls_a_cada_horas: int = 1

    # ---------------- Celery ----------------
    broker_visibility_timeout_segundos: int = 21600
    limite_tempo_task_segundos: int = 1800

    # ---------------- Download em massa ----------------
    limite_documentos_por_exportacao: int = 25000

    # ---------------- Alertas externos ----------------
    alerta_webhook_url: str = ""
    alerta_webhook_min_nivel: str = "atencao"
    alerta_webhook_cooldown_minutos: int = 120
    alerta_webhook_intervalo_minutos: int = 15

    # Bootstrap só é útil para primeira instalação. Em produção deve ser uma
    # senha forte entregue por secret manager e removida depois do primeiro boot.
    bootstrap_escritorio: str = "Escritório Principal"
    bootstrap_nome: str = "Administrador"
    bootstrap_email: str = ""
    bootstrap_senha: str = ""

    # ---------------- Procurações RFB ----------------
    # Interruptor geral do módulo. Desligado, nenhuma task periódica roda e
    # nenhuma estação recebe trabalho — é o "scheduler desligável" exigido
    # para manutenção do portal ou período de apuração crítico.
    procuracoes_ativo: bool = True
    # Manutenção automática (varredura de leases, vencimentos, nonces).
    procuracoes_manutencao_a_cada_minutos: int = 10
    # Sincronização automática com as fontes configuradas (hora local do
    # escritório vem da configuração por escritório; aqui é só o gatilho).
    procuracoes_sincronizacao_a_cada_horas: int = 6
    # Evidências de execução (captura de tela/HTML). Prazo de retenção: são
    # dado pessoal com finalidade operacional, não trilha de auditoria — a
    # trilha (procuracao_job_eventos) nunca é expurgada.
    procuracoes_evidencia_retencao_dias: int = 180
    procuracoes_evidencia_max_mb: int = 8
    # Teto de jobs entregues por ciclo em todo o escritório. Protege o portal
    # da RFB de rajada e o escritório de abrir 50 navegadores ao mesmo tempo.
    procuracoes_max_jobs_por_ciclo: int = 20

    # ---------------- Backup recuperável ----------------
    backup_ativo: bool = True
    backup_hora: int = 3
    backup_retencao: int = 14
    backup_alerta_horas: int = 26
    # Não fica sob DADOS_DIR: o compose de produção monta este caminho em
    # volume próprio. Mesmo assim, o S3 compatível é obrigatório em produção.
    # Vazio usa DADOS_DIR/backups no modo local. Produção deve apontar para o
    # volume dedicado /backups configurado no compose de produção.
    backup_dir: str = ""
    # Chave Fernet distinta do cofre dos certificados. É obrigatória para
    # toda execução de backup: o pacote inteiro é cifrado antes de persistir.
    backup_encryption_key: str = ""
    # Chaves anteriores só decifram pacotes já existentes; novas gravações
    # usam sempre BACKUP_ENCRYPTION_KEY. Separe por vírgula durante rotação.
    backup_previous_encryption_keys: str = ""
    backup_s3_bucket: str = ""
    backup_s3_prefix: str = "notasflow"
    backup_s3_region: str = "us-east-1"
    backup_s3_endpoint_url: str = ""
    backup_s3_access_key_id: str = ""
    backup_s3_secret_access_key: str = ""
    # AWS KMS ou equivalente S3 compatível. Vazio usa SSE-S3 além da cifra local.
    backup_s3_kms_key_id: str = ""

    @property
    def usando_sqlite(self) -> bool:
        return self.database_url.strip().lower().startswith("sqlite")

    @property
    def em_producao(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origens_lista(self) -> list[str]:
        return [origem.strip().rstrip("/") for origem in self.cors_origins.split(",") if origem.strip()]

    @property
    def cookie_secure(self) -> bool:
        return self.em_producao

    @property
    def pasta_backup(self) -> Path:
        return Path(self.backup_dir) if self.backup_dir.strip() else Path(self.dados_dir) / "backups"

    def validar_producao(self) -> None:
        """Recusa deploy inseguro com mensagens acionáveis e sem segredos."""
        if not self.em_producao:
            return

        problemas: list[str] = []
        chave = (self.secret_key or "").strip()
        if len(chave) < 32 or chave == _CHAVE_PADRAO_INSEGURA or "troque" in chave.lower():
            problemas.append("SECRET_KEY ausente, previsível ou curta")

        try:
            Fernet((self.vault_master_key or "").strip().encode())
            for chave_anterior in self.vault_previous_master_keys.split(","):
                if chave_anterior.strip():
                    Fernet(chave_anterior.strip().encode())
        except (TypeError, ValueError):
            problemas.append("VAULT_MASTER_KEY ou VAULT_PREVIOUS_MASTER_KEYS inválida")
        if self.backup_ativo:
            try:
                Fernet((self.backup_encryption_key or "").strip().encode())
                for chave_anterior in self.backup_previous_encryption_keys.split(","):
                    if chave_anterior.strip():
                        Fernet(chave_anterior.strip().encode())
            except (TypeError, ValueError):
                problemas.append("BACKUP_ENCRYPTION_KEY ou BACKUP_PREVIOUS_ENCRYPTION_KEYS inválida")

        banco = (self.database_url or "").strip()
        senha_banco = _senha_da_url(banco)
        if not banco.startswith(("postgresql://", "postgresql+psycopg2://")):
            problemas.append("DATABASE_URL deve apontar para PostgreSQL em produção")
        if len(senha_banco) < 16 or senha_banco.lower() in {"notasflow", "postgres", "password", "senha"}:
            problemas.append("DATABASE_URL usa senha ausente, fraca ou de exemplo")

        redis_url = (self.redis_url or "").strip()
        senha_redis = _senha_da_url(redis_url)
        if not redis_url.startswith(("redis://", "rediss://")) or len(senha_redis) < 16:
            problemas.append("REDIS_URL deve ter autenticação forte em produção")

        origens = self.cors_origens_lista
        if not origens or any("*" in origem for origem in origens):
            problemas.append("CORS_ORIGINS não pode ser vazio nem conter wildcard")
        elif any(not origem.startswith("https://") for origem in origens):
            problemas.append("CORS_ORIGINS deve conter somente origens HTTPS exatas")
        hosts = [host.strip().lower() for host in self.trusted_hosts.split(",") if host.strip()]
        if not hosts or any(host == "*" for host in hosts):
            problemas.append("TRUSTED_HOSTS não pode ser vazio nem conter wildcard")
        elif any(host in {"localhost", "127.0.0.1", "testserver"} for host in hosts):
            problemas.append("TRUSTED_HOSTS não pode conter hosts de desenvolvimento")

        if self.algorithm != "HS256":
            problemas.append("ALGORITHM deve ser HS256 em produção")
        if not 1 <= self.access_token_expire_minutes <= 60:
            problemas.append("ACCESS_TOKEN_EXPIRE_MINUTES deve ficar entre 1 e 60 em produção")
        if not self.rate_limit_ativo:
            problemas.append("RATE_LIMIT_ATIVO não pode ser desativado em produção")
        if not 0 <= self.backup_hora <= 23 or self.backup_retencao < 1:
            problemas.append("BACKUP_HORA ou BACKUP_RETENCAO inválidos")
        if self.backup_ativo:
            if not self.backup_s3_bucket.strip():
                problemas.append("BACKUP_S3_BUCKET é obrigatório para backup externo em produção")
            if not self.backup_dir.strip():
                problemas.append("BACKUP_DIR deve apontar para volume dedicado em produção")
            else:
                pasta_dados = Path(self.dados_dir).resolve()
                pasta_backup = self.pasta_backup.resolve()
                if not Path(self.backup_dir).is_absolute() or pasta_backup == pasta_dados or pasta_dados in pasta_backup.parents:
                    problemas.append("BACKUP_DIR deve ser absoluto e separado de DADOS_DIR")
        if self.backup_s3_endpoint_url and not self.backup_s3_endpoint_url.startswith("https://"):
            problemas.append("BACKUP_S3_ENDPOINT_URL deve usar HTTPS em produção")
        if self.alerta_webhook_url and not self.alerta_webhook_url.startswith("https://"):
            problemas.append("ALERTA_WEBHOOK_URL deve usar HTTPS")
        if self.procuracoes_ativo:
            if not 1 <= self.procuracoes_manutencao_a_cada_minutos <= 1440:
                problemas.append(
                    "PROCURACOES_MANUTENCAO_A_CADA_MINUTOS deve ficar entre 1 e 1440"
                )
            if not 1 <= self.procuracoes_sincronizacao_a_cada_horas <= 168:
                problemas.append(
                    "PROCURACOES_SINCRONIZACAO_A_CADA_HORAS deve ficar entre 1 e 168"
                )
            if not 1 <= self.procuracoes_evidencia_max_mb <= 32:
                problemas.append("PROCURACOES_EVIDENCIA_MAX_MB deve ficar entre 1 e 32")
            if not 1 <= self.procuracoes_evidencia_retencao_dias <= 3650:
                problemas.append(
                    "PROCURACOES_EVIDENCIA_RETENCAO_DIAS deve ficar entre 1 e 3650: "
                    "evidência do portal é dado pessoal e não pode ser eterna"
                )
            if not 1 <= self.procuracoes_max_jobs_por_ciclo <= 500:
                problemas.append("PROCURACOES_MAX_JOBS_POR_CICLO deve ficar entre 1 e 500")
            if not self.vault_master_key.strip():
                problemas.append(
                    "VAULT_MASTER_KEY é obrigatória com o módulo de procurações ativo: "
                    "credenciais de integração e evidências são cifradas com ela"
                )
        if self.bootstrap_senha and (len(self.bootstrap_senha) < 14 or self.bootstrap_senha == "troque-esta-senha"):
            problemas.append("BOOTSTRAP_SENHA configurada é fraca")

        if problemas:
            raise ErroConfiguracaoProducao(
                "Configuração de produção recusada: " + "; ".join(problemas) + "."
            )


settings = Settings()
# Também protege worker/beat: não basta a API recusar a configuração enquanto
# processos assíncronos continuariam manipulando certificados e documentos.
settings.validar_producao()
