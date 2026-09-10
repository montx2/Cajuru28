"""
Entry point para o modo Desktop (.exe)

- Usa SQLite local (arquivo no user data dir)
- Roda FastAPI com uvicorn em thread principal
- Roda scheduler de sincronização automática em thread separada (sem Celery/Redis)
- Gera chaves automaticamente se não existirem
- Cria usuário inicial se não existir

Variáveis de ambiente esperadas do launcher Electron:
  DATABASE_URL=sqlite:////caminho/para/notasflow.db
  DADOS_DIR=/caminho/para/dados
  DESKTOP_MODE=true
  SECRET_KEY=...
  VAULT_MASTER_KEY=...
  BOOTSTRAP_EMAIL=...
  BOOTSTRAP_SENHA=...
"""

import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Garantir que o diretório do app está no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("notasflow.desktop")

# Forçar modo desktop se não estiver setado
os.environ.setdefault("MODO_DESKTOP", "true")
os.environ.setdefault("DESKTOP_MODE", "true")

# Se DATABASE_URL não foi passado, usar SQLite no diretório de dados padrão
if "DATABASE_URL" not in os.environ:
    dados_dir = os.environ.get("DADOS_DIR", "./data_desktop")
    Path(dados_dir).mkdir(parents=True, exist_ok=True)
    db_path = Path(dados_dir) / "notasflow.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

if "DADOS_DIR" not in os.environ:
    os.environ["DADOS_DIR"] = "./data_desktop"

# Agora importar settings (vai ler as env vars acima)
from app.core.config import settings  # noqa: E402
from app.db.base import criar_tabelas  # noqa: E402
from app.bootstrap import garantir_usuario_inicial  # noqa: E402


def _garantir_diretorios():
    """Cria estrutura de diretórios necessária"""
    base = Path(settings.dados_dir)
    for sub in ["certificados", "xml"]:
        (base / sub).mkdir(parents=True, exist_ok=True)
    log.info(f"Diretórios garantidos em: {base}")


def _iniciar_scheduler():
    """
    Scheduler simples que roda sincronização automática a cada N minutos.
    Substitui o Celery Beat no modo desktop.
    """
    from app.worker.executor import executar_sincronizacao_automatica

    intervalo = max(1, int(settings.sincronismo_intervalo_minutos)) * 60

    def loop():
        log.info(f"Scheduler desktop iniciado: intervalo {intervalo//60} min")
        # Esperar um pouco antes da primeira execução (deixar API subir)
        time.sleep(10)
        while True:
            try:
                if settings.sincronismo_automatico:
                    resultado = executar_sincronizacao_automatica()
                    if resultado.get("enfileiradas", 0) > 0:
                        log.info(f"Scheduler: {resultado}")
                # Verificar execuções aguardando que venceram (a cada ciclo)
                from app.db.session import SessionLocal
                from app.models import ExecucaoImportacao, StatusExecucao
                from app.services import sincronizacao, fila

                db = SessionLocal()
                try:
                    agora = datetime.now(timezone.utc)
                    vencidas = (
                        db.query(ExecucaoImportacao)
                        .filter(
                            ExecucaoImportacao.status == StatusExecucao.AGUARDANDO,
                            ExecucaoImportacao.bloqueado_ate.isnot(None),
                            ExecucaoImportacao.bloqueado_ate <= agora,
                        )
                        .limit(20)
                        .all()
                    )
                    for execucao in vencidas:
                        lib = sincronizacao.liberacao_para(db, execucao.empresa_id, execucao.tipo)
                        if lib.pode:
                            fila.retomar(db, execucao)
                            log.info(f"Retomada automática: empresa {execucao.empresa_id} tipo {execucao.tipo.value}")
                    db.commit()
                except Exception as e:
                    log.warning(f"Erro no scheduler ao retomar: {e}")
                    db.rollback()
                finally:
                    db.close()

            except Exception as e:
                log.exception(f"Erro no scheduler desktop: {e}")

            time.sleep(intervalo)

    thread = threading.Thread(target=loop, daemon=True, name="desktop-scheduler")
    thread.start()
    return thread


def main():
    log.info("=== NotasFlow Desktop ===")
    log.info(f"Modo desktop: {settings.is_desktop}")
    log.info(f"Database: {settings.database_url[:50]}...")
    log.info(f"Dados dir: {settings.dados_dir}")

    _garantir_diretorios()

    # Criar tabelas e usuário inicial
    log.info("Criando/verificando tabelas...")
    criar_tabelas()
    garantir_usuario_inicial()
    log.info("Banco pronto")

    # Iniciar scheduler
    _iniciar_scheduler()

    # Iniciar API
    import uvicorn

    # Porta pode vir do env (Electron passa)
    port = int(os.environ.get("PORT", os.environ.get("API_PORT", "8000")))
    host = os.environ.get("HOST", "127.0.0.1")

    log.info(f"Iniciando API em http://{host}:{port}")
    log.info(f"Docs: http://{host}:{port}/docs")
    log.info(f"Saude: http://{host}:{port}/saude")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        log_level="info",
        reload=False,
        access_log=True,
    )


if __name__ == "__main__":
    main()
