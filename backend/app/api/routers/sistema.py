"""Informações operacionais do ambiente em execução."""

from datetime import datetime, timezone
from pathlib import Path
import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import MetaData, Table, func, inspect, select, text

from app.db.base import Base
from app.db.session import get_db

from app.services import fila
from app.api.deps import requer_escrita, requer_papel, usuario_atual
from app.core.plural import contagem
from app.core.config import settings
from app.models import (
    AcessoriasCredencial,
    BackupRegistro,
    Certificado,
    DocumentoFiscal,
    DocumentoFiscalFonte,
    Empresa,
    EventoFiscalPendente,
    ExecucaoImportacao,
    SincronizacaoDFe,
    StatusExecucao,
    Usuario,
)
from app.schemas import BackupRegistroResposta, ResetGeralResposta, SaudeBackupResposta
from app.services import auditoria, backup as svc_backup
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/sistema", tags=["sistema"])


def _ha_dados_legados_vinculados(db, empresa_ids: list[int]) -> bool:
    """Evita excluir empresas referenciadas por tabelas não carregadas pelo app.

    O schema pode conter tabelas de versões anteriores que o código atual não
    conhece. Elas não entram em migrações automáticas nem são apagadas junto
    com uma limpeza geral: nesse caso a operação para antes de alterar dados.
    """
    conexao = db.get_bind()
    inspetor = inspect(conexao)
    tabelas_mapeadas = set(Base.metadata.tables)
    metadata = MetaData()

    for nome_tabela in inspetor.get_table_names():
        if nome_tabela in tabelas_mapeadas:
            continue
        for chave in inspetor.get_foreign_keys(nome_tabela):
            if chave.get("referred_table") != "empresas":
                continue
            colunas = chave.get("constrained_columns") or []
            referidas = chave.get("referred_columns") or []
            colunas_empresa = [
                coluna
                for coluna, referida in zip(colunas, referidas)
                if referida == "id"
            ]
            if not colunas_empresa:
                continue
            tabela = Table(nome_tabela, metadata, autoload_with=conexao)
            for coluna in colunas_empresa:
                if coluna not in tabela.c:
                    continue
                encontrados = db.execute(
                    select(func.count())
                    .select_from(tabela)
                    .where(tabela.c[coluna].in_(empresa_ids))
                ).scalar_one()
                if encontrados:
                    return True
    return False


_ROTULO_MODO = {
    "development": "Desenvolvimento",
    "test": "Teste",
    "production": "Produção",
}
_ROTULO_AGENDA = {
    "varrer-alertas-webhook": "Alertas externos",
    "backup-diario": "Backup diário",
    "sincronizar-tudo": "Captura fiscal automática",
    "completar-xmls-pendentes": "XMLs pendentes",
}
_ROTULO_TAREFA = {
    "varrer_alertas_webhook": "Enviar alertas configurados",
    "backup_agendado": "Criar backup diário",
    "sincronizar_tudo": "Consultar documentos fiscais",
    "completar_xmls_pendentes": "Completar XMLs fiscais",
}


@router.get("/info")
def informacao_do_sistema(_usuario=Depends(usuario_atual)):
    """Expõe diagnóstico útil sem revelar nomes internos do agendador."""
    agenda: dict[str, dict[str, str]] = {}
    for indice, (nome, item) in enumerate(celery_app.conf.beat_schedule.items(), start=1):
        rotulo = _ROTULO_AGENDA.get(nome, f"Outra rotina {indice}")
        tarefa = _ROTULO_TAREFA.get(item.get("task"), "Rotina do sistema")
        agenda[rotulo] = {"tarefa": tarefa}
    usando_sqlite = settings.usando_sqlite
    return {
        "modo": _ROTULO_MODO.get(settings.app_env, "Desconhecido"),
        "modo_desktop": usando_sqlite,
        "modo_servidor": not usando_sqlite,
        "banco": "SQLite" if usando_sqlite else "PostgreSQL",
        "dados_dir": settings.dados_dir,
        "fila": {"modo": "Em segundo plano", "tecnologia": "Celery", "agenda": agenda},
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
    """
    Verifica banco, cofre, fila e espaço no volume persistente.

    A fila entrou aqui porque o cartão "Situação geral" da tela de Saúde diz
    que verifica "processamento em segundo plano" — e sem esta checagem ele
    respondia "Operacional" com o Redis fora do ar, enquanto o cartão de
    componentes, logo abaixo, mostrava a fila em erro.
    """
    problemas: list[str] = []
    banco_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # diagnóstico deve responder mesmo com o banco indisponível
        banco_ok = False
        problemas.append(f"Banco de dados inacessível: {str(exc)[:200]}")

    if not fila.fila_respondendo():
        problemas.append(
            "A fila de processamento não responde (Redis fora do ar): nenhuma "
            "captura sai, automática ou manual."
        )

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
def aplicar_atualizacao_docker(_admin: Usuario = Depends(requer_papel("admin"))):
    _somente_docker()


@router.post("/encerrar")
def encerrar_indisponivel(_usuario=Depends(usuario_atual)):
    _somente_docker()


@router.post("/abrir-pasta")
def abrir_pasta_indisponivel(_usuario=Depends(usuario_atual)):
    _somente_docker()


@router.post("/reset-geral", response_model=ResetGeralResposta)
def reset_geral(
    confirmar: str,
    remover_integracoes: bool = False,
    forcar: bool = False,
    db=Depends(get_db),
    usuario: Usuario = Depends(requer_papel("admin")),
):
    """
    Limpa o escritório logado para começar do zero: empresas, certificados,
    XMLs, execuções, cursores/bloqueios e pendências locais.

    Mantém o usuário, o escritório, auditoria e backups. Para evitar clique
    acidental a tela/API precisa enviar `confirmar=APAGAR TUDO` — a mesma
    frase que a tela exige digitar no DialogoConfirmacao (exigirTexto="APAGAR
    TUDO" em Configurações). Se houver importação realmente em andamento,
    bloqueia por padrão; `forcar=true` existe para recuperar um ambiente que
    ficou preso e precisa ser zerado.
    """
    if confirmar.strip().upper() != "APAGAR TUDO":
        raise HTTPException(status_code=422, detail="Digite/enviar confirmar=APAGAR TUDO para executar a limpeza geral.")

    escritorio_id = usuario.escritorio_id
    empresa_ids = [linha[0] for linha in db.query(Empresa.id).filter(Empresa.escritorio_id == escritorio_id).all()]
    if empresa_ids and _ha_dados_legados_vinculados(db, empresa_ids):
        raise HTTPException(
            status_code=409,
            detail=(
                "A limpeza foi interrompida para preservar registros legados "
                "associados às empresas. Nenhuma alteração foi realizada; "
                "a migração desses dados exige um procedimento separado."
            ),
        )
    if empresa_ids and not forcar:
        em_andamento = (
            db.query(ExecucaoImportacao.id)
            .filter(
                ExecucaoImportacao.empresa_id.in_(empresa_ids),
                ExecucaoImportacao.status == StatusExecucao.EM_ANDAMENTO,
            )
            .first()
        )
        if em_andamento:
            raise HTTPException(
                status_code=409,
                detail="Há importação em andamento. Aguarde terminar ou repita com forcar=true para zerar mesmo assim.",
            )

    from app.models import TipoDocumentoFiscal
    from app.services import lotes_recebidos
    caminhos_lotes = [str(arquivo) for empresa_id in empresa_ids for tipo in TipoDocumentoFiscal
        for arquivo in lotes_recebidos.arquivos_pendentes(empresa_id, tipo)]
    caminhos_xml = [linha[0] for linha in db.query(DocumentoFiscal.xml_path).filter(DocumentoFiscal.empresa_id.in_(empresa_ids or [-1])).all()]
    caminhos_cert = [linha[0] for linha in db.query(Certificado.arquivo_path).filter(Certificado.empresa_id.in_(empresa_ids or [-1])).all()]

    documentos = db.query(DocumentoFiscal).filter(DocumentoFiscal.empresa_id.in_(empresa_ids or [-1])).count()
    certificados = db.query(Certificado).filter(Certificado.empresa_id.in_(empresa_ids or [-1])).count()
    execucoes = db.query(ExecucaoImportacao).filter(ExecucaoImportacao.empresa_id.in_(empresa_ids or [-1])).count()
    sincronizacoes = db.query(SincronizacaoDFe).filter(SincronizacaoDFe.empresa_id.in_(empresa_ids or [-1])).count()
    empresas = len(empresa_ids)

    if empresa_ids:
        ids_documentos = select(DocumentoFiscal.id).where(DocumentoFiscal.empresa_id.in_(empresa_ids))
        db.query(EventoFiscalPendente).filter(EventoFiscalPendente.empresa_id.in_(empresa_ids)).delete(synchronize_session=False)
        db.query(DocumentoFiscalFonte).filter(DocumentoFiscalFonte.documento_id.in_(ids_documentos)).delete(synchronize_session=False)
        db.query(DocumentoFiscal).filter(DocumentoFiscal.empresa_id.in_(empresa_ids)).delete(synchronize_session=False)
        db.query(ExecucaoImportacao).filter(ExecucaoImportacao.empresa_id.in_(empresa_ids)).delete(synchronize_session=False)
        db.query(SincronizacaoDFe).filter(SincronizacaoDFe.empresa_id.in_(empresa_ids)).delete(synchronize_session=False)
        db.query(Certificado).filter(Certificado.empresa_id.in_(empresa_ids)).delete(synchronize_session=False)
        db.query(Empresa).filter(Empresa.id.in_(empresa_ids), Empresa.escritorio_id == escritorio_id).delete(synchronize_session=False)

    integracoes = 0
    if remover_integracoes:
        integracoes += db.query(AcessoriasCredencial).filter(AcessoriasCredencial.escritorio_id == escritorio_id).delete(synchronize_session=False)
        integracoes += db.query(CredencialIntegracao).filter(CredencialIntegracao.escritorio_id == escritorio_id).delete(synchronize_session=False)

    auditoria.registrar(
        db,
        usuario,
        "reset_geral",
        detalhe=(
            f"{contagem(empresas, 'empresa', 'empresas')}, {contagem(documentos, 'documento', 'documentos')}, {contagem(certificados, 'certificado', 'certificados')}, "
            f"{contagem(execucoes, 'execução', 'execuções')}, {contagem(sincronizacoes, 'sincronização', 'sincronizações')}; "
            f"integracoes_removidas={integracoes}"
        ),
    )
    db.commit()

    arquivos_removidos = _remover_arquivos_locais(caminhos_xml + caminhos_cert + caminhos_lotes)
    return ResetGeralResposta(
        empresas=empresas,
        documentos=documentos,
        certificados=certificados,
        execucoes=execucoes,
        sincronizacoes=sincronizacoes,
        arquivos_removidos=arquivos_removidos,
        integracoes=integracoes,
    )


def _remover_arquivos_locais(caminhos: list[str | None]) -> int:
    removidos = 0
    vistos: set[str] = set()
    for caminho in caminhos:
        if not caminho or caminho in vistos:
            continue
        vistos.add(caminho)
        try:
            arquivo = Path(caminho)
            if arquivo.is_file():
                arquivo.unlink()
                removidos += 1
        except OSError:
            # A limpeza do banco é a parte crítica; arquivo ausente/travado fica
            # para remoção manual ou próxima limpeza do volume.
            continue
    return removidos


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
