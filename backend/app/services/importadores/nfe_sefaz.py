"""
Importador de NFe via SEFAZ — webservice nacional NFeDistribuicaoDFe,
operação nfeDistDFeInteresse.

DE ONDE VEIO ISSO: não existe um ambiente de teste real com certificado A1
verdadeiro disponível para mim neste ambiente (sem acesso de rede a
nfe.fazenda.gov.br, sem certificado de cliente real). A estrutura abaixo
foi construída a partir de:
- Nota Técnica 2014.002 (schema oficial de distDFeInt/retDistDFeInt);
- XSDs oficiais (distDFeInt_v1.01.xsd, retDistDFeInt_v1.00.xsd);
- exemplos reais de request/response de produção replicados por
  bibliotecas open-source consolidadas e amplamente usadas em produção
  por terceiros (sped-nfe, DFe.NET, Java_NFe, xml-nfe.io).

O que isso significa na prática: a forma da mensagem (envelope, campos,
schema de resposta) está verificada contra documentação e exemplos reais.
O que ainda NÃO foi testado contra o SEFAZ de verdade: comportamento em
casos de borda (rejeições específicas, throttling, timeout sob carga) —
trate a primeira rodada em homologação (tp_amb="2") como validação, não
como certeza de que está pronto para produção.

Diferenças confirmadas em relação ao NFS-e/ADN:
- Protocolo SOAP 1.2, não REST.
- Não há assinatura XML na consulta — só o certificado A1 via mTLS no
  transporte (confirmado nos exemplos: nenhum deles assina o distDFeInt).
- cStat "137" (nenhum documento localizado) não é erro — é resposta válida
  de "nada novo". cStat "138" é sucesso com documentos. Qualquer outro
  cStat é tratado como erro, com a mensagem do próprio SEFAZ (xMotivo)
  repassada — não tentei adivinhar a tabela completa de códigos.
- Cada `docZip` pode ser um RESUMO (schema="resNFe...") ou o documento
  COMPLETO (schema="procNFe...") ou um EVENTO (schema="procEventoNFe..."
  ou "resEvento..."). Isso é uma particularidade real da Distribuição
  DFe: sem "manifestação do destinatário" prévia, o que chega geralmente
  é o resumo, não a NFe completa. Eventos são ignorados por ora (não são
  nota fiscal) — ver TODO abaixo.

TODO (não faz parte desta rodada):
- Endpoint de manifestação do destinatário (RecepcaoEvento) — necessário
  para muitas empresas passarem a receber o documento completo (procNFe)
  em vez de só o resumo (resNFe).
- Decidir o que fazer com eventos (procEventoNFe/resEvento) no modelo de
  dados — hoje eles avançam o checkpoint mas não viram DocumentoFiscal.
"""

import base64
import gzip
import xml.etree.ElementTree as ET

from app.services.importadores._distribuicao_dfe import (
    CODIGO_IBGE_POR_UF,
    DISTRIBUICAO_DFE_URL_HOMOLOGACAO,
    DISTRIBUICAO_DFE_URL_PRODUCAO,
    buscar,
    buscar_todos,
    chamar_com_retentativa,
    montar_envelope,
)
from app.services.importadores.base import DocumentoBaixado, ImportadorFiscal, LoteImportado


class ImportadorNFeSEFAZ(ImportadorFiscal):
    def __init__(self, ambiente: str = "producao"):
        self.tp_amb = "1" if ambiente == "producao" else "2"
        self.url = DISTRIBUICAO_DFE_URL_PRODUCAO if ambiente == "producao" else DISTRIBUICAO_DFE_URL_HOMOLOGACAO

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

        envelope = montar_envelope(cnpj, cuf_autor, self.tp_amb, ultimo_nsu)
        resposta_bytes = chamar_com_retentativa(envelope, self.url, cert_path, key_path)
        raiz = ET.fromstring(resposta_bytes)

        ret = buscar(raiz, "retDistDFeInt")
        if ret is None:
            raise ValueError(
                "Resposta do SEFAZ não trouxe retDistDFeInt — formato inesperado "
                f"(primeiros 500 bytes: {resposta_bytes[:500]!r})"
            )

        cstat = buscar(ret, "cStat").text
        x_motivo_el = buscar(ret, "xMotivo")
        x_motivo = x_motivo_el.text if x_motivo_el is not None else ""
        ult_nsu_resp = buscar(ret, "ultNSU").text

        if cstat == "137":  # nenhum documento localizado — não é erro
            return LoteImportado(documentos=[], proximo_nsu=ult_nsu_resp, ha_mais_documentos=False)

        if cstat != "138":
            raise ConnectionError(f"SEFAZ retornou cStat={cstat}: {x_motivo}")

        max_nsu_el = buscar(ret, "maxNSU")
        max_nsu = max_nsu_el.text if max_nsu_el is not None else ult_nsu_resp

        documentos = []
        for doc_zip in buscar_todos(ret, "docZip"):
            documento = self._converter_doc_zip(doc_zip, cnpj)
            if documento is not None:
                documentos.append(documento)

        ha_mais = int(ult_nsu_resp) < int(max_nsu)
        return LoteImportado(documentos=documentos, proximo_nsu=ult_nsu_resp, ha_mais_documentos=ha_mais)

    def _converter_doc_zip(self, doc_zip_elemento, cnpj_consultado: str) -> DocumentoBaixado | None:
        nsu = doc_zip_elemento.get("NSU", "")
        schema = doc_zip_elemento.get("schema", "")
        xml_bytes = gzip.decompress(base64.b64decode(doc_zip_elemento.text))

        if schema.startswith("procEventoNFe") or schema.startswith("resEvento"):
            # Evento (manifestação, cancelamento, ciência) — não é uma nota
            # em si. Avança o checkpoint (nsu já foi consumido no loop
            # chamador) mas não vira DocumentoFiscal. Ver TODO no topo do
            # arquivo.
            return None

        raiz_doc = ET.fromstring(xml_bytes)
        chave_el = buscar(raiz_doc, "chNFe")
        if chave_el is not None:
            chave = chave_el.text
        else:
            # Fallback para o documento completo: a chave também aparece
            # no atributo Id de infNFe, no formato "NFe" + 44 dígitos.
            inf_nfe = buscar(raiz_doc, "infNFe")
            chave = inf_nfe.get("Id", "")[3:] if inf_nfe is not None else ""

        emit_el = buscar(raiz_doc, "emit")
        if emit_el is not None:
            emitente_cnpj = buscar(emit_el, "CNPJ")
            emitente_cnpj = emitente_cnpj.text if emitente_cnpj is not None else ""
        else:
            # No resumo (resNFe), o CNPJ do emitente vem direto na raiz.
            emitente_cnpj_el = buscar(raiz_doc, "CNPJ")
            emitente_cnpj = emitente_cnpj_el.text if emitente_cnpj_el is not None else ""

        data_emissao_el = buscar(raiz_doc, "dhEmi")
        data_emissao = data_emissao_el.text if data_emissao_el is not None else ""

        valor_el = buscar(raiz_doc, "vNF")
        valor_total = float(valor_el.text) if valor_el is not None else 0.0

        direcao = "prestada" if emitente_cnpj == cnpj_consultado else "tomada"

        return DocumentoBaixado(
            chave_acesso=chave,
            nsu=nsu,
            xml=xml_bytes,
            data_emissao=data_emissao,
            valor_total=valor_total,
            direcao=direcao,
        )
