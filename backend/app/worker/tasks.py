import os
from datetime import datetime, timezone

from dateutil import parser as date_parser
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.core.vault import decifrar_segredo
from app.db.session import SessionLocal
from app.models import (
    Certificado,
    DirecaoDocumento,
    DocumentoFiscal,
    Empresa,
    ExecucaoImportacao,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.services.importadores import obter_importador
from app.services.mtls import sessao_mtls
from app.worker.celery_app import celery_app

TAMANHO_MAXIMO_LOTE_POR_EXECUCAO = 50  # trava de segurança: no máx. 50 lotes por chamada de task


def _parse_data_emissao(valor: str | datetime | None) -> datetime:
    """
    Converte a data de emissão (string ISO do XML fiscal, datetime, ou vazio)
    para datetime timezone-aware. Fallback: agora em UTC — nunca deixa a
    gravação quebrar por um campo opcional malformado.
    """
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            return valor.replace(tzinfo=timezone.utc)
        return valor
    if not valor or not str(valor).strip():
        return datetime.now(timezone.utc)
    try:
        dt = date_parser.isoparse(str(valor).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError, OverflowError):
        try:
            dt = date_parser.parse(str(valor).strip())
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError, OverflowError):
            return datetime.now(timezone.utc)


@celery_app.task(name="importar_documentos", bind=True, max_retries=0)
def importar_documentos(self, empresa_id: int, tipo: str, execucao_id: int) -> None:
    """
    Executa a importação completa de uma empresa até não haver mais
    documento novo, gravando o progresso a cada lote — se o worker cair no
    meio, a próxima execução retoma do último NSU salvo (mesmo princípio de
    checkpoint do Importarnotas original).
    """
    db = SessionLocal()
    tipo_doc = TipoDocumentoFiscal(tipo)

    try:
        execucao = db.get(ExecucaoImportacao, execucao_id)
        empresa = db.get(Empresa, empresa_id)
        if execucao is None or empresa is None:
            return

        certificado = (
            db.query(Certificado)
            .filter(Certificado.empresa_id == empresa_id, Certificado.ativo.is_(True))
            .first()
        )

        if certificado is None:
            _marcar_erro(db, execucao, "Nenhum certificado ativo para esta empresa")
            return

        # Checkpoint: retoma do maior NSU já conhecido para esta empresa+tipo
        # (última execução, ou o NSU desta execução se já avançou em reentrada).
        ultimo_nsu = _resolver_nsu_inicial(db, empresa_id, tipo_doc, execucao)

        senha = decifrar_segredo(certificado.senha_cifrada)
        with open(certificado.arquivo_path, "rb") as f:
            pfx_bytes = f.read()

        importador = obter_importador(tipo_doc)
        total_importado = execucao.documentos_importados or 0

        with sessao_mtls(pfx_bytes, senha) as (cert_path, key_path):
            for _ in range(TAMANHO_MAXIMO_LOTE_POR_EXECUCAO):
                lote = importador.buscar_lote(
                    cnpj=empresa.cnpj_cpf,
                    cert_path=cert_path,
                    key_path=key_path,
                    ultimo_nsu=ultimo_nsu,
                    uf=empresa.uf,
                )

                for doc in lote.documentos:
                    # A fonte pode reenviar documentos de um NSU já visitado.
                    # A contagem representa apenas o que entrou agora no banco.
                    if _gravar_documento(db, empresa_id, tipo_doc, doc):
                        total_importado += 1

                ultimo_nsu = lote.proximo_nsu
                execucao.ultimo_nsu = ultimo_nsu
                execucao.documentos_importados = total_importado
                db.commit()  # checkpoint a cada lote — nada se perde numa queda

                if not lote.ha_mais_documentos:
                    break
            else:
                # Esgotou as 50 iterações sem "acabou" — reenfileira a MESMA
                # execução para continuar do checkpoint, sem mentir "concluída".
                importar_documentos.delay(
                    empresa_id=empresa_id, tipo=tipo, execucao_id=execucao_id
                )
                return

        execucao.status = StatusExecucao.CONCLUIDA
        execucao.finalizado_em = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:  # noqa: BLE001 — task de background: captura, registra, não derruba o worker
        db.rollback()
        execucao = db.get(ExecucaoImportacao, execucao_id)
        _marcar_erro(db, execucao, str(exc))
    finally:
        db.close()


def _resolver_nsu_inicial(
    db, empresa_id: int, tipo: TipoDocumentoFiscal, execucao: ExecucaoImportacao
) -> str:
    """
    Ponto de retomada: se esta execução já tem NSU (reentrada após cap de 50
    lotes), usa ele; senão, pega o maior NSU de qualquer execução anterior
    concluída/em andamento do mesmo empresa+tipo — evita rebaixar do zero a
    cada clique em "Importar".
    """
    if execucao.ultimo_nsu:
        return execucao.ultimo_nsu

    anterior = (
        db.query(ExecucaoImportacao)
        .filter(
            ExecucaoImportacao.empresa_id == empresa_id,
            ExecucaoImportacao.tipo == tipo,
            ExecucaoImportacao.id != execucao.id,
            ExecucaoImportacao.ultimo_nsu.isnot(None),
        )
        .order_by(ExecucaoImportacao.id.desc())
        .first()
    )
    if anterior and anterior.ultimo_nsu:
        return anterior.ultimo_nsu
    return "0"


def _normalizar_chave(chave: str | None) -> str:
    """A coluna tem 60 chars; chaves iguais após o corte colidem no unique."""
    if not chave:
        return ""
    return str(chave).strip()[:60]


def _inserir_documento_sem_duplicar(db, valores: dict) -> bool:
    """
    Insere um documento de forma atômica e retorna se uma linha foi criada.

    Consultar antes de inserir não é suficiente: dois workers podem consultar
    ao mesmo tempo, ambos concluírem que a chave não existe e um deles receber
    `psycopg2.errors.UniqueViolation`. O `ON CONFLICT DO NOTHING` deixa o
    próprio PostgreSQL arbitrar essa corrida sem abortar a importação.

    SQLite usa a mesma sintaxe para manter os testes locais fiéis ao banco de
    produção. A aplicação é suportada em PostgreSQL; outro dialeto recebe um
    erro explícito, em vez de voltar ao padrão inseguro de consulta + insert.
    """
    dialeto = db.get_bind().dialect.name
    tabela = DocumentoFiscal.__table__

    if dialeto == "postgresql":
        comando = postgresql_insert(tabela).values(**valores).on_conflict_do_nothing(
            constraint="uq_documento_por_empresa"
        )
    elif dialeto == "sqlite":
        comando = sqlite_insert(tabela).values(**valores).on_conflict_do_nothing(
            index_elements=("empresa_id", "chave_acesso")
        )
    else:
        raise RuntimeError(
            f"Banco não suportado para importação idempotente: {dialeto}. Use PostgreSQL."
        )

    resultado = db.execute(comando)
    return resultado.rowcount == 1


def _gravar_documento(db, empresa_id: int, tipo: TipoDocumentoFiscal, doc) -> bool:
    """
    Persiste um documento de forma idempotente.

    A mesma nota pode voltar em uma consulta posterior ou chegar a workers em
    paralelo. A restrição `uq_documento_por_empresa` continua sendo a regra
    final, mas o insert atômico absorve o conflito e a task segue normalmente.
    Retorna True somente quando uma nota nova foi gravada.
    """
    chave = _normalizar_chave(getattr(doc, "chave_acesso", None))
    if not chave:
        return False

    pasta = os.path.join(settings.dados_dir, "xml", str(empresa_id), tipo.value)
    nome_seguro = "".join(c for c in chave if c.isalnum() or c in "-_") or f"nsu_{doc.nsu}"
    xml_path = os.path.join(pasta, f"{nome_seguro}.xml")
    direcao = doc.direcao if doc.direcao in ("tomada", "prestada") else "tomada"

    valores = {
        "empresa_id": empresa_id,
        "tipo": tipo,
        "direcao": DirecaoDocumento(direcao),
        "chave_acesso": chave,
        "nsu": str(doc.nsu),
        "data_emissao": _parse_data_emissao(doc.data_emissao),
        "valor_total": float(doc.valor_total or 0),
        "xml_path": xml_path,
    }
    if not _inserir_documento_sem_duplicar(db, valores):
        return False

    # Só grava o XML depois de vencer a disputa no banco. Assim uma
    # reimportação não sobrescreve o arquivo já associado à nota existente.
    os.makedirs(pasta, exist_ok=True)
    with open(xml_path, "wb") as f:
        f.write(doc.xml)
    return True


def _marcar_erro(db, execucao: ExecucaoImportacao | None, mensagem: str) -> None:
    if execucao is None:
        return
    execucao.status = StatusExecucao.ERRO
    execucao.mensagem_erro = mensagem[:4000] if mensagem else "Erro desconhecido"
    execucao.finalizado_em = datetime.now(timezone.utc)
    db.commit()
