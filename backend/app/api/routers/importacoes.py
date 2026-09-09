from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual
from app.db.session import get_db
from app.models import (
    Certificado,
    Empresa,
    ExecucaoImportacao,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.schemas import ExecucaoImportacaoResposta, ImportacaoSolicitar, ItemImportacaoLote
from app.worker.tasks import importar_documentos

router = APIRouter(prefix="/importacoes", tags=["importações"])

# Depois que o ADN diz "não há nada novo", esperar antes de perguntar de
# novo — existe para não sinalizar a um CNPJ como consumo indevido. Ver
# docs/ARQUITETURA.md.
COOLDOWN_SEM_NOVIDADE = timedelta(hours=1)


def _fim_do_cooldown(
    db: Session, empresa_id: int, tipo: TipoDocumentoFiscal
) -> datetime | None:
    """
    Retorna o horário em que a empresa volta a poder ser consultada, ou
    None se pode importar agora. Só entra em cooldown quando a última
    execução concluída não trouxe nenhum documento novo — se trouxe, é
    sinal de que ainda há (ou havia) coisa relevante acontecendo, e não faz
    sentido bloquear.
    """
    ultima = (
        db.query(ExecucaoImportacao)
        .filter(
            ExecucaoImportacao.empresa_id == empresa_id,
            ExecucaoImportacao.tipo == tipo,
            ExecucaoImportacao.status == StatusExecucao.CONCLUIDA,
        )
        .order_by(ExecucaoImportacao.finalizado_em.desc())
        .first()
    )
    if ultima is None or ultima.documentos_importados > 0 or ultima.finalizado_em is None:
        return None

    finalizado_em = ultima.finalizado_em
    if finalizado_em.tzinfo is None:
        # Alguns drivers/bancos devolvem datetime "naive" mesmo com a coluna
        # marcada como timezone=True; como tudo aqui é gravado com
        # datetime.now(timezone.utc), assumir UTC é seguro.
        finalizado_em = finalizado_em.replace(tzinfo=timezone.utc)

    fim = finalizado_em + COOLDOWN_SEM_NOVIDADE
    return fim if fim > datetime.now(timezone.utc) else None


def _enfileirar(db: Session, empresa_id: int, tipo: TipoDocumentoFiscal) -> ExecucaoImportacao:
    # Evita enfileirar duas vezes a mesma empresa+tipo enquanto ainda roda
    em_andamento = (
        db.query(ExecucaoImportacao)
        .filter(
            ExecucaoImportacao.empresa_id == empresa_id,
            ExecucaoImportacao.tipo == tipo,
            ExecucaoImportacao.status == StatusExecucao.EM_ANDAMENTO,
        )
        .first()
    )
    if em_andamento is not None:
        return em_andamento

    execucao = ExecucaoImportacao(
        empresa_id=empresa_id, tipo=tipo, status=StatusExecucao.EM_ANDAMENTO
    )
    db.add(execucao)
    db.commit()
    db.refresh(execucao)
    importar_documentos.delay(empresa_id=empresa_id, tipo=tipo.value, execucao_id=execucao.id)
    return execucao


@router.post("", response_model=ExecucaoImportacaoResposta, status_code=202)
def solicitar_importacao(
    dados: ImportacaoSolicitar,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Enfileira a importação de UMA empresa e retorna imediatamente — o
    processamento roda no worker. Para as 30 empresas de uma vez, use
    POST /importacoes/lote.
    """
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == dados.empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    if not dados.forcar:
        fim_cooldown = _fim_do_cooldown(db, dados.empresa_id, dados.tipo)
        if fim_cooldown:
            raise HTTPException(
                status_code=429,
                detail=(
                    "O ADN foi consultado recentemente e não havia nada novo. "
                    f"Para não arriscar bloqueio do CNPJ, aguarde até {fim_cooldown.isoformat()} "
                    "ou envie forcar=true para pular esta proteção."
                ),
            )

    return _enfileirar(db, dados.empresa_id, dados.tipo)


@router.post("/lote", response_model=list[ItemImportacaoLote])
def solicitar_importacao_em_lote(
    tipo: TipoDocumentoFiscal,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Dispara a importação de TODAS as empresas ativas do escritório de uma
    vez — o equivalente ao 'sincronizar --todas' do Importarnotas original.
    Cada empresa vira uma task independente na fila: uma travar ou falhar
    não afeta as outras. Empresas sem certificado ou em cooldown são
    reportadas, não enfileiradas.
    """
    empresas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .all()
    )

    resultados: list[ItemImportacaoLote] = []
    for empresa in empresas:
        tem_certificado = (
            db.query(Certificado)
            .filter(Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True))
            .first()
        )
        if tem_certificado is None:
            resultados.append(
                ItemImportacaoLote(
                    empresa_id=empresa.id, razao_social=empresa.razao_social, status="sem_certificado"
                )
            )
            continue

        fim_cooldown = _fim_do_cooldown(db, empresa.id, tipo)
        if fim_cooldown:
            resultados.append(
                ItemImportacaoLote(
                    empresa_id=empresa.id,
                    razao_social=empresa.razao_social,
                    status="em_cooldown",
                    disponivel_em=fim_cooldown,
                )
            )
            continue

        execucao = _enfileirar(db, empresa.id, tipo)
        resultados.append(
            ItemImportacaoLote(
                empresa_id=empresa.id,
                razao_social=empresa.razao_social,
                status="enfileirada",
                execucao_id=execucao.id,
            )
        )

    return resultados


@router.get("", response_model=list[ExecucaoImportacaoResposta])
def listar_execucoes(
    empresa_id: int | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Histórico de execuções — usado pela tela de Importações no painel."""
    consulta = (
        db.query(ExecucaoImportacao).join(Empresa).filter(Empresa.escritorio_id == escritorio_id)
    )
    if empresa_id is not None:
        consulta = consulta.filter(ExecucaoImportacao.empresa_id == empresa_id)

    execucoes = consulta.order_by(ExecucaoImportacao.iniciado_em.desc()).limit(limit).all()

    respostas = []
    for execucao in execucoes:
        resposta = ExecucaoImportacaoResposta.model_validate(execucao)
        resposta.empresa_razao_social = execucao.empresa.razao_social
        respostas.append(resposta)
    return respostas


@router.get("/{execucao_id}", response_model=ExecucaoImportacaoResposta)
def consultar_execucao(
    execucao_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    execucao = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(ExecucaoImportacao.id == execucao_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if execucao is None:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    resposta = ExecucaoImportacaoResposta.model_validate(execucao)
    resposta.empresa_razao_social = execucao.empresa.razao_social
    return resposta
