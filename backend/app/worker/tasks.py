import os
from datetime import datetime, timezone

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


@celery_app.task(name="importar_documentos")
def importar_documentos(empresa_id: int, tipo: str, execucao_id: int) -> None:
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
        certificado = (
            db.query(Certificado)
            .filter(Certificado.empresa_id == empresa_id, Certificado.ativo.is_(True))
            .first()
        )

        if certificado is None:
            _marcar_erro(db, execucao, "Nenhum certificado ativo para esta empresa")
            return

        senha = decifrar_segredo(certificado.senha_cifrada)
        with open(certificado.arquivo_path, "rb") as f:
            pfx_bytes = f.read()

        importador = obter_importador(tipo_doc)
        ultimo_nsu = execucao.ultimo_nsu or "0"
        total_importado = 0

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
                    _gravar_documento(db, empresa_id, tipo_doc, doc)
                    total_importado += 1

                ultimo_nsu = lote.proximo_nsu
                execucao.ultimo_nsu = ultimo_nsu
                execucao.documentos_importados = total_importado
                db.commit()  # checkpoint a cada lote — nada se perde numa queda

                if not lote.ha_mais_documentos:
                    break
            else:
                # O loop esgotou as 50 iterações sem o ADN dizer "acabou" —
                # ainda há mais para importar (comum na primeira importação
                # de uma empresa com muito histórico). Reenfileira a MESMA
                # execução para continuar do checkpoint salvo, em vez de
                # mentir que terminou. Isso também devolve o worker para a
                # fila entre uma leva e outra, então uma empresa com
                # histórico gigante não segura as outras 29 esperando.
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


def _gravar_documento(db, empresa_id: int, tipo: TipoDocumentoFiscal, doc) -> None:
    ja_existe = (
        db.query(DocumentoFiscal)
        .filter(
            DocumentoFiscal.empresa_id == empresa_id,
            DocumentoFiscal.chave_acesso == doc.chave_acesso,
        )
        .first()
    )
    if ja_existe:
        return  # idempotente: reprocessar o mesmo NSU não duplica documento

    pasta = os.path.join(settings.dados_dir, "xml", str(empresa_id), tipo.value)
    os.makedirs(pasta, exist_ok=True)
    xml_path = os.path.join(pasta, f"{doc.chave_acesso}.xml")
    with open(xml_path, "wb") as f:
        f.write(doc.xml)

    db.add(
        DocumentoFiscal(
            empresa_id=empresa_id,
            tipo=tipo,
            direcao=DirecaoDocumento(doc.direcao),
            chave_acesso=doc.chave_acesso,
            nsu=doc.nsu,
            data_emissao=doc.data_emissao,
            valor_total=doc.valor_total,
            xml_path=xml_path,
        )
    )


def _marcar_erro(db, execucao: ExecucaoImportacao | None, mensagem: str) -> None:
    if execucao is None:
        return
    execucao.status = StatusExecucao.ERRO
    execucao.mensagem_erro = mensagem
    execucao.finalizado_em = datetime.now(timezone.utc)
    db.commit()
