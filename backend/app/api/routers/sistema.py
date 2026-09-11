"""Informações operacionais da implantação Docker."""

from datetime import datetime, timezone
from pathlib import Path
import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import text

from app.db.session import get_db

from app.api.deps import requer_escrita, usuario_atual
from app.core.config import settings
from app.models import BackupRegistro, Usuario
from app.schemas import BackupRegistroResposta, SaudeBackupResposta
from app.services import auditoria, backup as svc_backup
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
        "webhook": {
            "configurado": bool((settings.alerta_webhook_url or "").strip()),
            "nivel_minimo": settings.alerta_webhook_min_nivel,
            "intervalo_minutos": settings.alerta_webhook_intervalo_minutos,
        },
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


@router.post("/backup", response_model=BackupRegistroResposta, status_code=202)
def executar_backup(
    plano: BackgroundTasks,
    db=Depends(get_db),
    usuario: Usuario = Depends(requer_escrita),
):
    """
    Dispara um backup completo AGORA (banco + manifesto + espelho de XMLs).

    Roda em plano de fundo na própria API — não depende do worker, então
    funciona mesmo com os contêineres de fila parados (que, aliás, é quando
    mais se quer um backup). Acompanhe o resultado na Saúde do sistema.
    """
    if not settings.backup_ativo:
        raise HTTPException(status_code=409, detail="Backup desativado nas configurações.")

    registro = BackupRegistro(tipo="manual", status=svc_backup.StatusBackup.EM_ANDAMENTO)
    db.add(registro)
    db.commit()
    db.refresh(registro)

    # O serviço cria o próprio registro com contagens; este aqui é o "placeholder"
    # visível na fila da UI. Para não duplicar linhas, o serviço reaproveita
    # este registro passando o id.
    plano.add_task(_rodar_backup_em_fundo, registro.id)

    auditoria.registrar(db, usuario, "backup_disparado", detalhe="Backup manual em plano de fundo")
    db.commit()
    return registro


def _rodar_backup_em_fundo(registro_id: int) -> None:
    """Executa o backup reaproveitando o registro criado pelo endpoint."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        svc_backup.executar_backup(db, tipo="manual", registro_id=registro_id)
    finally:
        db.close()


@router.get("/backups", response_model=dict)
def listar_backups(
    db=Depends(get_db),
    _usuario=Depends(usuario_atual),
):
    """Histórico + retrato de saúde do backup (último, próximo, teste)."""
    registros = (
        db.query(BackupRegistro)
        .order_by(BackupRegistro.id.desc())
        .limit(max(1, settings.backup_retencao))
        .all()
    )
    return {
        "saude": SaudeBackupResposta(**svc_backup.saude_do_backup(db)),
        "registros": [BackupRegistroResposta.model_validate(r) for r in registros],
    }


@router.post("/backups/{backup_id}/testar", response_model=dict)
def testar_restauracao(
    backup_id: int,
    db=Depends(get_db),
    usuario: Usuario = Depends(requer_escrita),
):
    """
    O teste que transforma backup em plano: extrai o pacote, recria o schema
    num banco de prova, recarrega os registros e confere as contagens.
    """
    ok, detalhe = svc_backup.testar_restauracao(db, backup_id)
    auditoria.registrar(
        db,
        usuario,
        "backup_testado",
        entidade="backup",
        entidade_id=backup_id,
        detalhe=f"ok={ok} · {detalhe[:300]}",
    )
    db.commit()
    return {"ok": ok, "detalhe": detalhe}
