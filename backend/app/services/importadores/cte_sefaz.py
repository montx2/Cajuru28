"""
Importador de CT-e via SEFAZ — webservice nacional CTeDistribuicaoDFe,
operação cteDistDFeInteresse.

Fontes:
- Portal CT-e (cte.fazenda.gov.br) — URL AN:
  https://www1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx
- Nota Técnica 2015.002 + distDFeInt_v1.00.xsd (oficial)
- nfephp-org/sped-cte (src/Tools.php::sefazDistDFe)
- TadaSoftware/PyNFe (comunicacao.py::consulta_distribuicao CT-e)

Mesmo padrão da NFe (distDFeInt / retDistDFeInt / docZip), namespaces e
operação SOAP diferentes. Schemas dentro do docZip:
- resCTe — resumo
- procCTe — documento completo
- procEventoCTe / resEvento — eventos

Diferença que importa: o XSD do CT-e só oferece `distNSU` e `consNSU` — não
existe `consChNFe` para CT-e. Ou seja, a recuperação pontual aqui é por NSU.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from app.services.importadores._distribuicao_dfe import (
    CODIGO_IBGE_POR_UF,
    CSTAT_DOCUMENTOS_LOCALIZADOS,
    CTE_DADOS_MSG,
    CTE_DISTRIBUICAO_URL_HOMOLOGACAO,
    CTE_DISTRIBUICAO_URL_PRODUCAO,
    CTE_NS_PORTAL,
    CTE_NS_WSDL,
    CTE_OPERACAO,
    CTE_SOAP_ACTION,
    CTE_VERSAO_DIST,
    buscar,
    chamar_com_retentativa,
    competencia_de_texto,
    extrair_metadados,
    interpretar_resposta,
    montar_envelope,
    montar_envelope_cte,
    texto,
)
from app.services.importadores.base import (
    DocumentoBaixado,
    ImportadorFiscal,
    LoteImportado,
)
from app.services.importadores.eventos import EventoFiscal, classificar_evento_xml
from app.services.importadores.nfe_sefaz import _nsu_inteiro

CSTAT_SEM_DOCUMENTOS = {"137"}
CSTAT_CONSUMO_INDEVIDO = {"656"}


class ImportadorCTeSEFAZ(ImportadorFiscal):
    ambiente_nome = "SEFAZ CT-e"

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
        cuf_autor = self._cuf_autor(uf, "CT-e")
        envelope = montar_envelope_cte(cnpj, cuf_autor, self.tp_amb, ultimo_nsu)
        resposta_bytes = chamar_com_retentativa(
            envelope, self.url, cert_path, key_path, soap_action=CTE_SOAP_ACTION
        )
        return self._interpretar(resposta_bytes, cnpj, ultimo_nsu)

    def buscar_por_nsu(
        self, cnpj: str, cert_path: str, key_path: str, nsu: str, uf: str | None = None
    ) -> DocumentoBaixado | None:
        """`consNSU`: o XSD do CT-e não tem consulta por chave, só por NSU."""
        digitos = "".join(c for c in str(nsu) if c.isdigit()) or "0"
        cuf_autor = self._cuf_autor(uf, "CT-e")
        envelope = montar_envelope(
            cnpj,
            cuf_autor,
            self.tp_amb,
            "0",
            ns_wsdl=CTE_NS_WSDL,
            ns_portal=CTE_NS_PORTAL,
            operacao=CTE_OPERACAO,
            dados_msg=CTE_DADOS_MSG,
            versao=CTE_VERSAO_DIST,
            consulta_especifica=("consNSU", f"<NSU>{digitos.zfill(15)}</NSU>"),
        )
        resposta_bytes = chamar_com_retentativa(
            envelope, self.url, cert_path, key_path, soap_action=CTE_SOAP_ACTION
        )
        resposta = interpretar_resposta(resposta_bytes, ambiente=self.ambiente_nome)
        if resposta.inexistente or not resposta.documentos:
            return None
        for nsu_item, schema, xml_bytes in resposta.documentos:
            documento = self._converter(nsu_item, schema, xml_bytes, cnpj)
            if documento is not None:
                return documento
        return None

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _cuf_autor(uf: str | None, rotulo: str) -> str:
        if not uf or uf.upper() not in CODIGO_IBGE_POR_UF:
            raise ValueError(
                f"UF inválida ou ausente para consulta de {rotulo}: {uf!r}. "
                "Cadastre a UF da empresa antes de importar NFe/CT-e."
            )
        return CODIGO_IBGE_POR_UF[uf.upper()]

    def _interpretar(self, resposta_bytes: bytes, cnpj: str, ultimo_nsu: str) -> LoteImportado:
        resposta = interpretar_resposta(resposta_bytes, ambiente=self.ambiente_nome)

        if resposta.sem_novidade:
            return LoteImportado(
                documentos=[],
                proximo_nsu=_nsu_inteiro(resposta.ultimo_nsu, ultimo_nsu),
                ha_mais_documentos=False,
                max_nsu=_nsu_inteiro(resposta.max_nsu, resposta.ultimo_nsu),
                sem_novidade=True,
            )

        if resposta.cstat != CSTAT_DOCUMENTOS_LOCALIZADOS:
            raise ValueError(
                f"SEFAZ CT-e retornou cStat={resposta.cstat}: {resposta.x_motivo}"
            )

        documentos: list[DocumentoBaixado] = []
        eventos: list[EventoFiscal] = []
        eventos_nao_reconhecidos = 0
        erros: list[str] = []

        for nsu, schema, xml_bytes in resposta.documentos:
            if not xml_bytes:
                erros.append(f"NSU {nsu}: docZip ilegível (gzip/base64 inválido)")
                continue
            try:
                raiz = ET.fromstring(xml_bytes)
            except ET.ParseError as exc:
                erros.append(f"NSU {nsu}: XML malformado ({exc})")
                continue

            # Eventos (cancelamento, CC-e…) não viram documento fiscal, mas
            # NUNCA podem sumir: são devolvidos no lote para o worker aplicar.
            evento = classificar_evento_xml(
                xml_bytes, schema=schema, nsu=_nsu_inteiro(nsu, "0")
            )
            if evento is not None:
                eventos.append(evento)
                if not evento.eh_cancelamento:
                    eventos_nao_reconhecidos += 1
                continue

            documento = self._converter(nsu, schema, xml_bytes, cnpj, raiz=raiz)
            if documento is None:
                erros.append(f"NSU {nsu}: documento sem chave de acesso — não pode ser gravado")
                continue
            documentos.append(documento)

        proximo = _nsu_inteiro(resposta.ultimo_nsu, ultimo_nsu)
        max_nsu = _nsu_inteiro(resposta.max_nsu, resposta.ultimo_nsu)

        return LoteImportado(
            documentos=documentos,
            proximo_nsu=proximo,
            ha_mais_documentos=int(proximo) < int(max_nsu),
            eventos=eventos,
            eventos_nao_reconhecidos=eventos_nao_reconhecidos,
            erros=erros,
            max_nsu=max_nsu,
        )

    def _converter(
        self,
        nsu: str,
        schema: str,
        xml_bytes: bytes,
        cnpj_consultado: str,
        raiz: ET.Element | None = None,
    ) -> DocumentoBaixado | None:
        if not xml_bytes:
            return None
        if raiz is None:
            try:
                raiz = ET.fromstring(xml_bytes)
            except ET.ParseError:
                return None

        # Chave: chCTe no resumo, ou Id de infCte ("CTe" + 44 dígitos) no completo
        chave_el = buscar(raiz, "chCTe")
        chave = (chave_el.text or "").strip() if chave_el is not None else ""
        if not chave:
            inf_cte = buscar(raiz, "infCte") or buscar(raiz, "infCTe")
            raw_id = (inf_cte.get("Id", "") or "") if inf_cte is not None else ""
            chave = raw_id[3:] if raw_id.upper().startswith("CTE") else raw_id
        if not chave:
            return None
        chave = "".join(c for c in chave if c.isdigit()) or chave

        metadados = extrair_metadados(raiz)
        try:
            # Valor: vTPrest (total da prestação); fallback vTRec / vCarga.
            valor_total = float(str(metadados.get("valor") or "0").replace(",", "."))
        except ValueError:
            valor_total = 0.0

        cnpj_limpo = "".join(c for c in cnpj_consultado if c.isdigit())
        emit_limpo = "".join(c for c in (metadados.get("emit_doc") or "") if c.isdigit())
        # CT-e: emitente = transportadora. Se o CNPJ consultado é o emitente,
        # a nota é "prestada"; caso contrário, "tomada" (remetente/destinatário).
        direcao = "tomada"
        if emit_limpo and emit_limpo == cnpj_limpo:
            direcao = "prestada"

        data_emissao = metadados.get("data_emissao") or texto(raiz, "dRec") or ""

        return DocumentoBaixado(
            chave_acesso=chave,
            nsu=_nsu_inteiro(nsu, "0"),
            xml=xml_bytes,
            data_emissao=data_emissao,
            valor_total=valor_total,
            direcao=direcao,
            competencia=competencia_de_texto(metadados.get("competencia", ""), data_emissao),
            leiaute="resumo" if schema.lower().startswith("res") else "completo",
            numero=metadados.get("numero", ""),
            serie=metadados.get("serie", ""),
            emitente_documento=metadados.get("emit_doc", ""),
            emitente_nome=metadados.get("emit_nome", ""),
            destinatario_documento=metadados.get("dest_doc", ""),
            destinatario_nome=metadados.get("dest_nome", ""),
            status_autorizacao=metadados.get("situacao", ""),
        )
