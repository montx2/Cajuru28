"""
Importador de CT-e via SEFAZ — webservice nacional CTeDistribuicaoDFe,
operação cteDistDFeInteresse.

Fontes:
- Portal CT-e (cte.fazenda.gov.br) — URL AN:
  https://www1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx
- nfephp-org/sped-cte (src/Tools.php::sefazDistDFe)
- TadaSoftware/PyNFe (comunicacao.py::consulta_distribuicao CT-e)

Mesmo padrão da NFe (distDFeInt / retDistDFeInt / docZip), namespaces e
operação SOAP diferentes. Schemas dentro do docZip:
- resCTe — resumo
- procCTe — documento completo
- procEventoCTe / resEvento — eventos (ignorados como documento fiscal)
"""

from __future__ import annotations

import base64
import gzip
import xml.etree.ElementTree as ET

from app.services.importadores._distribuicao_dfe import (
    CODIGO_IBGE_POR_UF,
    CTE_DISTRIBUICAO_URL_HOMOLOGACAO,
    CTE_DISTRIBUICAO_URL_PRODUCAO,
    CTE_SOAP_ACTION,
    buscar,
    buscar_todos,
    chamar_com_retentativa,
    montar_envelope_cte,
)
from app.services.importadores.base import DocumentoBaixado, ImportadorFiscal, LoteImportado
from app.services.importadores.eventos import EventoFiscal, classificar_evento_xml

CSTAT_SEM_DOCUMENTOS = {"137"}
CSTAT_CONSUMO_INDEVIDO = {"656"}


class ImportadorCTeSEFAZ(ImportadorFiscal):
    def __init__(self, ambiente: str = "producao"):
        self.tp_amb = "1" if ambiente == "producao" else "2"
        self.url = (
            CTE_DISTRIBUICAO_URL_PRODUCAO
            if ambiente == "producao"
            else CTE_DISTRIBUICAO_URL_HOMOLOGACAO
        )

    def buscar_lote(
        self,
        cnpj: str,
        cert_path: str,
        key_path: str,
        ultimo_nsu: str,
        uf: str | None = None,
    ) -> LoteImportado:
        if not uf or uf.upper() not in CODIGO_IBGE_POR_UF:
            raise ValueError(
                f"UF inválida ou ausente para consulta de CT-e: {uf!r}. "
                "Cadastre a UF da empresa antes de importar NFe/CT-e."
            )
        cuf_autor = CODIGO_IBGE_POR_UF[uf.upper()]

        envelope = montar_envelope_cte(cnpj, cuf_autor, self.tp_amb, ultimo_nsu)
        resposta_bytes = chamar_com_retentativa(
            envelope, self.url, cert_path, key_path, soap_action=CTE_SOAP_ACTION
        )
        raiz = ET.fromstring(resposta_bytes)

        ret = buscar(raiz, "retDistDFeInt")
        if ret is None:
            raise ValueError(
                "Resposta do SEFAZ CT-e não trouxe retDistDFeInt — formato inesperado "
                f"(primeiros 500 bytes: {resposta_bytes[:500]!r})"
            )

        cstat_el = buscar(ret, "cStat")
        cstat = (cstat_el.text or "").strip() if cstat_el is not None else ""
        x_motivo_el = buscar(ret, "xMotivo")
        x_motivo = x_motivo_el.text if x_motivo_el is not None else ""

        ult_nsu_el = buscar(ret, "ultNSU")
        ult_nsu_resp = (
            (ult_nsu_el.text or ultimo_nsu or "0").strip()
            if ult_nsu_el is not None
            else (ultimo_nsu or "0")
        )

        if cstat in CSTAT_SEM_DOCUMENTOS:
            return LoteImportado(
                documentos=[],
                proximo_nsu=str(int(ult_nsu_resp)) if ult_nsu_resp.isdigit() else (ult_nsu_resp.lstrip("0") or "0"),
                ha_mais_documentos=False,
            )

        if cstat in CSTAT_CONSUMO_INDEVIDO or cstat != "138":
            raise ConnectionError(f"SEFAZ CT-e retornou cStat={cstat}: {x_motivo}")

        max_nsu_el = buscar(ret, "maxNSU")
        max_nsu = (
            (max_nsu_el.text or ult_nsu_resp).strip()
            if max_nsu_el is not None
            else ult_nsu_resp
        )

        documentos: list[DocumentoBaixado] = []
        eventos: list[EventoFiscal] = []
        eventos_nao_reconhecidos = 0
        erros: list[str] = []
        for doc_zip in buscar_todos(ret, "docZip"):
            nsu = doc_zip.get("NSU", "")
            schema = (doc_zip.get("schema", "") or "").lower()
            if not doc_zip.text:
                continue
            try:
                xml_bytes = gzip.decompress(base64.b64decode(doc_zip.text))
            except Exception as exc:  # noqa: BLE001 — item corrompido não derruba o lote
                erros.append(f"NSU {nsu}: docZip ilegível ({exc})")
                continue

            # Eventos (cancelamento, CC-e…) não viram documento fiscal, mas
            # NUNCA podem sumir: são devolvidos no lote para o worker aplicar.
            evento = classificar_evento_xml(xml_bytes, schema=schema, nsu=nsu.lstrip("0") or "0")
            if evento is not None:
                eventos.append(evento)
                if not evento.eh_cancelamento:
                    eventos_nao_reconhecidos += 1
                continue

            documento = self._converter_doc_zip(doc_zip, cnpj, xml_bytes)
            if documento is None:
                erros.append(f"NSU {nsu}: documento sem chave de acesso — não pode ser gravado")
                continue
            documentos.append(documento)

        try:
            ha_mais = int(ult_nsu_resp) < int(max_nsu)
        except ValueError:
            ha_mais = False  # sem maxNSU confiável, a página decide

        return LoteImportado(
            documentos=documentos,
            proximo_nsu=str(int(ult_nsu_resp)) if ult_nsu_resp.isdigit() else ult_nsu_resp,
            ha_mais_documentos=ha_mais,
            eventos=eventos,
            eventos_nao_reconhecidos=eventos_nao_reconhecidos,
            erros=erros,
        )

    def _converter_doc_zip(
        self, doc_zip_elemento, cnpj_consultado: str, xml_bytes: bytes
    ) -> DocumentoBaixado | None:
        nsu = doc_zip_elemento.get("NSU", "")
        raiz_doc = ET.fromstring(xml_bytes)

        # Chave: chCTe no resumo, ou Id de infCte ("CTe" + 44 dígitos) no completo
        chave_el = buscar(raiz_doc, "chCTe")
        if chave_el is not None and chave_el.text:
            chave = chave_el.text
        else:
            inf_cte = buscar(raiz_doc, "infCte") or buscar(raiz_doc, "infCTe")
            raw_id = inf_cte.get("Id", "") if inf_cte is not None else ""
            chave = raw_id[3:] if raw_id.upper().startswith("CTE") else raw_id

        # Emitente (transportadora). Element é falsy sem filhos — usar is not None.
        emit_el = buscar(raiz_doc, "emit")
        emitente = ""
        if emit_el is not None:
            emit_doc_el = buscar(emit_el, "CNPJ")
            if emit_doc_el is None:
                emit_doc_el = buscar(emit_el, "CPF")
            emitente = emit_doc_el.text if emit_doc_el is not None else ""
        else:
            emit_doc_el = buscar(raiz_doc, "CNPJ")
            emitente = emit_doc_el.text if emit_doc_el is not None else ""

        data_el = buscar(raiz_doc, "dhEmi")
        data_emissao = data_el.text if data_el is not None else ""

        # Valor: vTPrest (total da prestação) no CT-e; fallback vTRec / vCarga.
        # ATENÇÃO: ElementTree Element é falsy quando não tem filhos — nunca
        # use `a or b` com Element; compare com `is not None`.
        valor_el = buscar(raiz_doc, "vTPrest")
        if valor_el is None:
            valor_el = buscar(raiz_doc, "vTRec")
        if valor_el is None:
            valor_el = buscar(raiz_doc, "vCarga")
        try:
            valor_total = float(valor_el.text) if valor_el is not None and valor_el.text else 0.0
        except ValueError:
            valor_total = 0.0

        cnpj_limpo = "".join(c for c in cnpj_consultado if c.isdigit())
        emit_limpo = "".join(c for c in (emitente or "") if c.isdigit())
        # CT-e: emitente = transportadora. Se o CNPJ consultado é o emitente,
        # a nota é "prestada" (serviço de transporte prestado por ele);
        # caso contrário, "tomada" (ele é remetente/destinatário/tomador).
        direcao = "prestada" if emit_limpo and emit_limpo == cnpj_limpo else "tomada"

        if not chave:
            return None

        return DocumentoBaixado(
            chave_acesso=chave,
            nsu=(nsu.lstrip("0") or nsu or "0"),
            xml=xml_bytes,
            data_emissao=data_emissao,
            valor_total=valor_total,
            direcao=direcao,
        )
