"""
Importador de NFe via SEFAZ — webservice nacional NFeDistribuicaoDFe,
operação nfeDistDFeInteresse.

Fontes:
- Nota Técnica 2014.002 + XSDs oficiais (distDFeInt / retDistDFeInt)
- nfephp-org/sped-nfe (docs/metodos/DistDFe.md) — produção consolidada
- TadaSoftware/PyNFe

cStat relevantes:
- 137: nenhum documento localizado (não é erro — dispara cooldown de 1h)
- 138: documentos localizados
- 656: consumo indevido (bloqueio temporário — tratar como erro de cooldown)

Cada docZip pode ser resumo (resNFe), documento completo (procNFe) ou
evento (procEventoNFe/resEvento). Eventos avançam o checkpoint mas não
viram DocumentoFiscal. Sem manifestação do destinatário, o que chega
geralmente é o resumo.
"""

from __future__ import annotations

import base64
import gzip
import xml.etree.ElementTree as ET

from app.services.importadores._distribuicao_dfe import (
    CODIGO_IBGE_POR_UF,
    NFE_DISTRIBUICAO_URL_HOMOLOGACAO,
    NFE_DISTRIBUICAO_URL_PRODUCAO,
    NFE_SOAP_ACTION,
    buscar,
    buscar_todos,
    chamar_com_retentativa,
    montar_envelope_nfe,
)
from app.services.importadores.base import DocumentoBaixado, ImportadorFiscal, LoteImportado
from app.services.importadores.eventos import EventoFiscal, classificar_evento_xml

# cStat 137 = nenhum documento (não é erro — dispara cooldown de 1h).
# cStat 656 = consumo indevido: SEFAZ bloqueou por 1h. Tratamos como ERRO
# explícito para o operador ver no painel (e o cooldown da próxima tentativa
# ainda protege se ele reimportar depois de concluir com 0 docs — mas 656
# em si deve falhar a execução, não fingir "concluída sem novidade").
CSTAT_SEM_DOCUMENTOS = {"137"}
CSTAT_CONSUMO_INDEVIDO = {"656"}


class ImportadorNFeSEFAZ(ImportadorFiscal):
    def __init__(self, ambiente: str = "producao"):
        # NOTA (sped-nfe): o serviço de distribuição NFe na prática só opera
        # em produção. Homologação existe no endpoint mas o comportamento
        # real depende do Ambiente Nacional.
        self.tp_amb = "1" if ambiente == "producao" else "2"
        self.url = (
            NFE_DISTRIBUICAO_URL_PRODUCAO
            if ambiente == "producao"
            else NFE_DISTRIBUICAO_URL_HOMOLOGACAO
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
                f"UF inválida ou ausente para consulta de NFe: {uf!r}. "
                "Cadastre a UF da empresa antes de importar NFe/CT-e."
            )
        cuf_autor = CODIGO_IBGE_POR_UF[uf.upper()]

        envelope = montar_envelope_nfe(cnpj, cuf_autor, self.tp_amb, ultimo_nsu)
        resposta_bytes = chamar_com_retentativa(
            envelope, self.url, cert_path, key_path, soap_action=NFE_SOAP_ACTION
        )
        raiz = ET.fromstring(resposta_bytes)

        ret = buscar(raiz, "retDistDFeInt")
        if ret is None:
            raise ValueError(
                "Resposta do SEFAZ não trouxe retDistDFeInt — formato inesperado "
                f"(primeiros 500 bytes: {resposta_bytes[:500]!r})"
            )

        cstat_el = buscar(ret, "cStat")
        cstat = (cstat_el.text or "").strip() if cstat_el is not None else ""
        x_motivo_el = buscar(ret, "xMotivo")
        x_motivo = x_motivo_el.text if x_motivo_el is not None else ""

        ult_nsu_el = buscar(ret, "ultNSU")
        ult_nsu_resp = (ult_nsu_el.text or ultimo_nsu or "0").strip() if ult_nsu_el is not None else (ultimo_nsu or "0")

        if cstat in CSTAT_SEM_DOCUMENTOS:
            return LoteImportado(
                documentos=[],
                proximo_nsu=str(int(ult_nsu_resp)) if ult_nsu_resp.isdigit() else (ult_nsu_resp.lstrip("0") or "0"),
                ha_mais_documentos=False,
            )

        if cstat in CSTAT_CONSUMO_INDEVIDO or cstat != "138":
            raise ConnectionError(f"SEFAZ retornou cStat={cstat}: {x_motivo}")

        max_nsu_el = buscar(ret, "maxNSU")
        max_nsu = (max_nsu_el.text or ult_nsu_resp).strip() if max_nsu_el is not None else ult_nsu_resp

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

        if ult_nsu_resp.isdigit():
            proximo = str(int(ult_nsu_resp))
        else:
            proximo = ult_nsu_resp.lstrip("0") or "0"

        return LoteImportado(
            documentos=documentos,
            proximo_nsu=proximo,
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
        chave_el = buscar(raiz_doc, "chNFe")
        if chave_el is not None and chave_el.text:
            chave = chave_el.text
        else:
            inf_nfe = buscar(raiz_doc, "infNFe")
            chave = inf_nfe.get("Id", "")[3:] if inf_nfe is not None else ""

        # ElementTree: Element sem filhos é falsy — sempre comparar com is not None
        emit_el = buscar(raiz_doc, "emit")
        emitente_cnpj = ""
        if emit_el is not None:
            emitente_cnpj_el = buscar(emit_el, "CNPJ")
            if emitente_cnpj_el is None:
                emitente_cnpj_el = buscar(emit_el, "CPF")
            emitente_cnpj = emitente_cnpj_el.text if emitente_cnpj_el is not None else ""
        else:
            emitente_cnpj_el = buscar(raiz_doc, "CNPJ")
            emitente_cnpj = emitente_cnpj_el.text if emitente_cnpj_el is not None else ""

        data_emissao_el = buscar(raiz_doc, "dhEmi")
        data_emissao = data_emissao_el.text if data_emissao_el is not None else ""

        valor_el = buscar(raiz_doc, "vNF")
        try:
            valor_total = float(valor_el.text) if valor_el is not None and valor_el.text else 0.0
        except ValueError:
            valor_total = 0.0

        cnpj_limpo = "".join(c for c in cnpj_consultado if c.isdigit())
        emit_limpo = "".join(c for c in (emitente_cnpj or "") if c.isdigit())
        direcao = "prestada" if emit_limpo and emit_limpo == cnpj_limpo else "tomada"

        if not chave:
            return None

        return DocumentoBaixado(
            chave_acesso=chave,
            nsu=nsu.lstrip("0") or nsu or "0",
            xml=xml_bytes,
            data_emissao=data_emissao,
            valor_total=valor_total,
            direcao=direcao,
        )
