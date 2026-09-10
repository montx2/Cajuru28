import logging
import os

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("notasflow.config")

# O endereço do banco na implantação em servidor (docker-compose). É também o
# valor padrão do campo abaixo, e é o que o modo desktop precisa *nunca* usar:
# `db` é o nome do serviço dentro da rede do Docker. Fora dela, esse endereço
# não resolve — foi exatamente o que fazia a primeira abertura de uma
# instalação nova falhar com "could not translate host name db".
_URL_BANCO_SERVIDOR = "postgresql://notasflow:notasflow@db:5432/notasflow"

# O `.env` do modo desktop mora na pasta de dados do usuário, que só é conhecida
# em tempo de execução — por isso o caminho é passado por variável de ambiente
# antes de importar este módulo. Sem isso, o programa instalado leria o `.env`
# do "diretório atual", que no Windows é imprevisível (o `C:\Windows\System32`
# quando o atalho é criado de certas formas).
_ARQUIVO_ENV = os.environ.get("NOTASFLOW_ENV_FILE", ".env")


class Settings(BaseSettings):
    """
    Configuração central. Tudo vem do .env — nenhum segredo fica hardcoded
    ou versionado no código.

    As variáveis de ambiente do processo têm prioridade sobre o `.env`, o que
    permite ao programa instalado apontar para a pasta de dados do usuário sem
    reescrever o arquivo de configuração.
    """

    model_config = SettingsConfigDict(
        env_file=_ARQUIVO_ENV, case_sensitive=False, extra="ignore"
    )

    database_url: str = _URL_BANCO_SERVIDOR
    redis_url: str = "redis://redis:6379/0"

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

    # ---------------- Modo desktop (programa instalado) ----------------
    # Com `MODO_DESKTOP=true`, a fila deixa de ser Redis+Celery e passa a ser
    # em processo, o painel web é servido pela própria API e o programa abre
    # uma janela. O mesmo código atende os dois modos — ver app/desktop/.
    modo_desktop: bool = False
    # 127.0.0.1 de propósito: o painel e os certificados são de uso local.
    # Expor isso numa rede sem TLS entregaria senha de certificado na rede.
    notasflow_host: str = "127.0.0.1"
    notasflow_porta: int = 8765
    notasflow_concorrencia: int = 4
    notasflow_abrir_janela: bool = True
    notasflow_bandeja: bool = True
    # Libera o painel para outras máquinas do escritório (host 0.0.0.0).
    # Desligado por padrão: o banco local guarda senha de certificado, e
    # publicar isso numa rede sem TLS só se for decisão consciente.
    # IMPORTANTE: com isso ligado, os outros computadores usam o painel NO
    # NAVEGADOR — não instalam o programa. Duas instalações sincronizando os
    # mesmos CNPJs fazem a SEFAZ bloquear por consumo indevido.
    notasflow_permitir_rede: bool = False

    # ---------------- Atualização automática ----------------
    # Vazio = usa o repositório oficial abaixo. Aceita também uma pasta de rede
    # (ex.: \\SERVIDOR\NotasFlow) ou uma URL própria com o arquivo `latest.json`.
    notasflow_update_manifest: str = ""
    notasflow_repo: str = "montx2/Cajuru28"
    # Só necessário se o repositório for privado (o GitHub exige token).
    notasflow_update_token: str = ""
    notasflow_verificar_atualizacao_ao_abrir: bool = True
    # De quanto em quanto tempo o programa (que fica aberto na bandeja por
    # semanas) volta a perguntar se há versão nova. 6 horas é o meio do caminho
    # entre "chega rápido" e "não incomoda um servidor público".
    notasflow_verificar_atualizacao_horas: float = 6.0

    @model_validator(mode="after")
    def _nunca_usar_o_banco_do_servidor_no_desktop(self) -> "Settings":
        """
        Rede de segurança do programa instalado.

        O caminho normal é o `.env` da pasta de dados já trazer
        `DATABASE_URL=sqlite:///...` (criado por `ambiente.preparar_primeira_execucao`).
        Mas existem três situações em que ele não existe: a primeiríssima
        abertura, um usuário que apagou o arquivo sem querer e um comando de
        suporte (`--console`, `--diagnostico`) rodado antes da configuração.

        Em qualquer uma delas, o padrão do `database_url` apontaria para o
        PostgreSQL do Docker — um serviço que não existe no computador do
        contador — e o programa morreria no startup com um erro de rede que não
        diz nada a quem está olhando. Aqui isso é impossível: em modo desktop,
        o banco do servidor nunca é usado.

        Só o valor **padrão exato** é substituído. Quem monta uma implantação
        em desktop apontando de propósito para um PostgreSQL (rede do
        escritório) continua sendo respeitado.
        """
        if not self.modo_desktop or self.database_url.strip() != _URL_BANCO_SERVIDOR:
            return self

        # Import local: `caminhos` não importa mais nada do projeto, então não
        # há ciclo — e manter o import aqui deixa `config` utilizável sozinho.
        from app.desktop import caminhos

        self.database_url = f"sqlite:///{caminhos.caminho_banco().as_posix()}"
        if not self.dados_dir or self.dados_dir == "/data":
            self.dados_dir = str(caminhos.pasta_dados() / "dados")
        log.info("Modo desktop sem .env: usando o banco local em %s", self.database_url)
        return self

    @property
    def usando_sqlite(self) -> bool:
        return self.database_url.strip().lower().startswith("sqlite")

    @property
    def sincronismo_embutido(self) -> bool:
        """Em modo desktop o relógio é o processo local, não o serviço `beat`."""
        return bool(self.modo_desktop)


settings = Settings()
