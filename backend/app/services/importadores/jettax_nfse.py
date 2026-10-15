"""Importação NFS-e Jettax pelo pipeline XML existente, com checkpoint por nota."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy.orm import Session
from billiard.exceptions import SoftTimeLimitExceeded

from app.models import DocumentoFiscal, Empresa, StatusDocumentoFiscal, TipoDocumentoFiscal
from app.services.jettax import ClienteJettax, JettaxErro
from .xml_manual import (
    casar_com_empresas, classificar_xml, converter_xml,
    documento_com_direcao, gravar_documento,
)


@dataclass
class ResultadoJettax:
    recebidos: int = 0
    importados: int = 0
    duplicados: int = 0
    cancelados: int = 0
    erros: int = 0
    sem_empresa: int = 0
    empresa_ausente_jettax: bool = False
    consulta_completa: bool = False
    motivos_erros: dict[str, int] = field(default_factory=dict)

    def erro(self, mensagem: str):
        self.erros += 1
        self.motivos_erros[mensagem] = self.motivos_erros.get(mensagem, 0) + 1

    def dados(self):
        return asdict(self)


def importar_nfse(db: Session, cliente: ClienteJettax, escritorio_id: int,
                  empresa_id: int, competencia: str, resultado: ResultadoJettax | None = None,
                  progresso=None) -> ResultadoJettax:
    resultado = resultado if resultado is not None else ResultadoJettax()
    empresa = db.query(Empresa).filter_by(id=empresa_id, escritorio_id=escritorio_id, ativa=True).first()
    if empresa is None:
        raise JettaxErro("Empresa não encontrada ou inativa neste escritório.", 404)
    cnpj = empresa.cnpj_cpf
    if not cliente.empresa_cadastrada(cnpj):
        resultado.empresa_ausente_jettax = True
        return resultado
    for pagina in cliente.paginas_nfse(cnpj, competencia):
        for item in pagina:
            resultado.recebidos += 1
            try:
                identificador = item.get("id")
                situacao_bruta = item.get("notaSituacao")
                situacao = situacao_bruta.strip().lower() if isinstance(situacao_bruta, str) else None
                if (not isinstance(identificador, str) or not 1 <= len(identificador) <= 100
                        or situacao not in ("autorizada", "cancelada")):
                    raise ValueError("Metadados de nota não reconhecidos")
                conteudo = cliente.baixar_xml(item.get("url"))
                if classificar_xml(conteudo) != "nfse":
                    raise ValueError("Arquivo não é XML de NFS-e suportado")
                doc = converter_xml(conteudo, "nfse")
                if doc is None:
                    raise ValueError("XML não convertido")
                casamentos = casar_com_empresas(db, escritorio_id, doc)
                # A empresa consultada deve ser parte do XML. Não aceitar um arquivo
                # alheio só porque outra empresa do mesmo escritório aparece nele.
                if not any(cadastrada.id == empresa_id for cadastrada, _ in casamentos):
                    resultado.sem_empresa += 1
                    db.rollback()
                    continue
                importados = duplicados = cancelados = 0
                # Uma transação por XML: erro na segunda cópia desfaz ambas as cópias.
                for cadastrada, direcao in casamentos:
                    status = gravar_documento(
                        db, cadastrada, TipoDocumentoFiscal.NFSE,
                        documento_com_direcao(doc, direcao), identificador, origem="jettax",
                    )
                    if status in ("sem_chave", "sem_data"):
                        raise ValueError("XML sem identidade ou data utilizável")
                    if status in ("importado", "completada"):
                        importados += 1
                    else:
                        duplicados += 1
                    if situacao == "cancelada":
                        from app.worker.tasks import _normalizar_chave
                        existente = db.query(DocumentoFiscal).filter_by(
                            empresa_id=cadastrada.id, chave_acesso=_normalizar_chave(doc.chave_acesso),
                        ).first()
                        if existente is not None and existente.status != StatusDocumentoFiscal.CANCELADA:
                            existente.status = StatusDocumentoFiscal.CANCELADA
                            existente.motivo_cancelamento = "Cancelamento informado pela Jettax."
                            cancelados += 1
                db.commit()
                resultado.importados += importados
                resultado.duplicados += duplicados
                resultado.cancelados += cancelados
            except JettaxErro as exc:
                db.rollback()
                if exc.status_code in (401, 429):
                    raise  # limite/token afetam o lote: não insistir nos próximos XMLs
                resultado.erro(str(exc))
            except SoftTimeLimitExceeded:
                db.rollback()
                raise
            except Exception:
                # Exceções de SQL/conversão podem conter conteúdo fiscal ou URL.
                # Nunca registrar str(exc), traceback nem item da API.
                db.rollback()
                resultado.erro("XML ou metadados incompatíveis, ou falha local ao gravar o documento.")
            finally:
                if progresso is not None:
                    progresso(resultado)
    resultado.consulta_completa = True
    return resultado
