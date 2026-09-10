"""Informações operacionais da implantação Docker."""

from datetime import datetime, timezone
from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text

from app.db.session import get_db

from app.api.deps import usuario_atual
from app.core.config import settings
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/sistema", tags=["sistema"])


@router.get("/info")
def informacao_do_sistema(_usuario=Depends(usuario_atual)):
    """Expõe apenas dados úteis para diagnosticar os serviços Docker."""
    agenda = {
        nome: {"tarefa": item.get("task")}
        for nome, item in celery_app.conf.beat_schedule.items()
    }
    return {
        "modo": "docker",
        "modo_desktop": False,
        "modo_servidor": True,
        "banco": "postgresql",
        "dados_dir": settings.dados_dir,
        "fila": {"modo": "celery", "agenda": agenda},
        "hora_do_servidor": datetime.now(timezone.utc).isoformat(),
        "iniciar_com_windows": False,
        "pode_iniciar_com_windows": False,
    }


@router.get("/saude-detalhada")
def saude_detalhada(db=Depends(get_db), _usuario=Depends(usuario_atual)):
    """Verifica banco, cofre e espaço no volume persistente."""
    problemas: list[str] = []
    banco_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # diagnóstico deve responder mesmo com o banco indisponível
        banco_ok = False
        problemas.append(f"Banco de dados inacessível: {str(exc)[:200]}")

    if not settings.vault_master_key:
        problemas.append("VAULT_MASTER_KEY não configurada — certificados não podem ser gravados.")

    pasta = Path(settings.dados_dir)
    disco_livre = None
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        disco_livre = shutil.disk_usage(pasta).free
        if disco_livre < 500 * 1024 * 1024:
            problemas.append("Menos de 500 MB livres no volume de dados.")
    except OSError as exc:
        problemas.append(f"Volume de dados inacessível: {str(exc)[:200]}")

    return {
        "ok": not problemas,
        "problemas": problemas,
        "banco_ok": banco_ok,
        "disco_livre_bytes": disco_livre,
        "pasta_dados": str(pasta),
    }


def _somente_docker() -> None:
    raise HTTPException(
        status_code=409,
        detail="Esta função não se aplica ao Docker. Gerencie o sistema com Docker Compose.",
    )


@router.post("/iniciar-com-windows")
def inicio_windows_indisponivel(_usuario=Depends(usuario_atual)):
    _somente_docker()


@router.get("/atualizacao")
def atualizacao_docker(_usuario=Depends(usuario_atual)):
    return {
        "etapa": "docker",
        "mensagem": "Atualize com git pull e docker compose up --build -d.",
        "erro": None,
        "baixado": 0,
        "total": 0,
        "verificado_em": None,
        "versao_atual": "docker",
        "disponivel": None,
    }


@router.post("/atualizacao/verificar")
def verificar_atualizacao_docker(_usuario=Depends(usuario_atual)):
    return {"iniciado": False, "mensagem": "Atualizações são feitas pelo Docker Compose."}


@router.post("/atualizacao/aplicar")
def aplicar_atualizacao_docker(_usuario=Depends(usuario_atual)):
    _somente_docker()


@router.post("/encerrar")
def encerrar_indisponivel(_usuario=Depends(usuario_atual)):
    _somente_docker()


@router.post("/abrir-pasta")
def abrir_pasta_indisponivel(_usuario=Depends(usuario_atual)):
    _somente_docker()


@router.post("/backup")
def backup_indisponivel(_usuario=Depends(usuario_atual)):
    raise HTTPException(
        status_code=409,
        detail="Faça backup dos volumes db_data, certificados e xml_saida do Docker.",
    )
