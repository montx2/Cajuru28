"""
Importador de NFe via SEFAZ — webservice nacional NFeDistribuicaoDFe,
operação nfeDistDFeInteresse.

Fontes:
- Nota Técnica 2014.002 v1.12 + XSDs oficiais (distDFeInt / retDistDFeInt)
- nfephp-org/sped-nfe (docs/metodos/DistDFe.md) — prática validada em produção
- TadaSoftware/PyNFe

cStat relevantes:
- 137: nenhum documento localizado (não é erro — é o sinal para esperar 1h)
- 138: documentos localizados
- 656: consumo indevido (CNPJ bloqueado por 1h — levanta `ConsumoIndevido`
  com o ultNSU/maxNSU que o ambiente devolveu, para o worker realinhar)

Cada docZip pode ser resumo (resNFe), documento completo (procNFe) ou evento
(procEventoNFe/resEvento). Eventos avançam o checkpoint mas não viram
DocumentoFiscal.

Sobre o "só veio o resumo": é comportamento oficial, não bug. Enquanto o
destinatário não registrar a Ciência da Operação (210210), o Ambiente Nacional
distribui só o `resNFe`. `consChNFe` NÃO contorna isso: para o destinatário ele
também exige manifestação prévia (NT 2014.002). Depois da Ciência, o `procNFe`
chega pelo próprio fluxo de NSU (ver `_promover_resumo` no worker);
`buscar_por_chave()` (20 consultas/h) fica como reserva.

Sobre "prestadas": o emitente **não** recebe os próprios documentos pela
distribuição (tabela oficial do sped-nfe). NFe emitida pela empresa aparece
aqui só quando ela também é destinatária/transportador/autXML.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from app.core.documentos import normalizar_documento
from app.services.importadores._distribuicao_dfe import (
    CODIGO_IBGE_POR_UF,
    CSTAT_DOCUMENTOS_LOCALIZADOS,
    NFE_DISTRIBUICAO_URL_HOMOLOGACAO,
    NFE_DISTRIBUICAO_URL_PRODUCAO,
    NFE_SOAP_ACTION,
    buscar,
    chamar_com_retentativa,
    competencia_de_texto,
    extrair_metadados,
    interpretar_resposta,
    metadados_da_chave,
    montar_envelope,
    montar_envelope_nfe,
    texto,
)
from app.services.importadores.base import (
    DocumentoBaixado,
    ImportadorFiscal,
    LoteImportado,
)
from app.services.importadores.eventos import EventoFiscal, classificar_evento_xml

# Reexportados: os testes antigos e chamadores legados importam daqui.
CSTAT_SEM_DOCUMENTOS = {"137"}
CSTAT_CONSUMO_INDEVIDO = {"656"}


class ImportadorNFeSEFAZ(ImportadorFiscal):
    ambiente_nome = "SEFAZ NFe"

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

    # -- API pública ---------------------------------------------------------

    def buscar_lote(
        self,
        cnpj: str,
        cert_path: str,
        key_path: str,
        ultimo_nsu: str,
        uf: str | None = None,
    ) -> LoteImportado:
        cuf_autor = self._cuf_autor(uf, "NFe")
        envelope = montar_envelope_nfe(cnpj, cuf_autor, self.tp_amb, ultimo_nsu)
        resposta_bytes = chamar_com_retentativa(
            envelope, self.url, cert_path, key_path, soap_action=NFE_SOAP_ACTION
        )
        return self._interpretar(resposta_bytes, cnpj, ultimo_nsu)

    def buscar_por_chave(
        self, cnpj: str, cert_path: str, key_path: str, chave_acesso: str, uf: str | None = None
    ) -> DocumentoBaixado | None:
        """`consChNFe`: recupera a NFe completa pela chave (20 consultas/h)."""
        digitos = "".join(c for c in chave_acesso if c.isdigit())
        if len(digitos) != 44:
            raise ValueError(f"Chave de acesso de NFe deve ter 44 dígitos, veio {len(digitos)}.")
        cuf_autor = self._cuf_autor(uf, "NFe")
        envelope = montar_envelope(
            cnpj,
            cuf_autor,
            self.tp_amb,
            "0",
            consulta_especifica=("consChNFe", f"<chNFe>{digitos}</chNFe>"),
        )
        resposta_bytes = chamar_com_retentativa(
            envelope, self.url, cert_path, key_path, soap_action=NFE_SOAP_ACTION
        )
        resposta = interpretar_resposta(resposta_bytes, ambiente=self.ambiente_nome)
        if resposta.inexistente or not resposta.documentos:
            return None
        for nsu, schema, xml_bytes in resposta.documentos:
            documento = self._converter(nsu, schema, xml_bytes, cnpj)
            if documento is not None:
                return documento
        return None

    def buscar_por_nsu(
        self, cnpj: str, cert_path: str, key_path: str, nsu: str, uf: str | None = None
    ) -> DocumentoBaixado | None:
        """`consNSU`: fecha uma lacuna pontual na sequência de NSU."""
        digitos = "".join(c for c in str(nsu) if c.isdigit()) or "0"
        cuf_autor = self._cuf_autor(uf, "NFe")
        envelope = montar_envelope(
            cnpj,
            cuf_autor,
            self.tp_amb,
            "0",
            consulta_especifica=("consNSU", f"<NSU>{digitos.zfill(15)}</NSU>"),
        )
        resposta_bytes = chamar_com_retentativa(
            envelope, self.url, cert_path, key_path, soap_action=NFE_SOAP_ACTION
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
                f"SEFAZ NFe retornou cStat={resposta.cstat}: {resposta.x_motivo}"
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
            # `ultNSU < maxNSU` é a regra oficial para "ainda há mais".
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

        chave_el = buscar(raiz, "chNFe")
        chave = (chave_el.text or "").strip() if chave_el is not None else ""
        if not chave:
            inf_nfe = buscar(raiz, "infNFe")
            if inf_nfe is not None:
                chave = (inf_nfe.get("Id", "") or "")[3:]
        if not chave:
            return None
        chave = "".join(c for c in chave if c.isdigit()) or chave

        metadados = extrair_metadados(raiz)
        try:
            valor_total = float(str(metadados.get("valor") or "0").replace(",", "."))
        except ValueError:
            valor_total = 0.0

        try:
            cnpj_canonico = normalizar_documento(cnpj_consultado)
        except ValueError:
            cnpj_canonico = str(cnpj_consultado or "").strip().upper()
        try:
            emit_canonico = normalizar_documento(metadados.get("emit_doc") or "")
        except ValueError:
            emit_canonico = str(metadados.get("emit_doc") or "").strip().upper()
        direcao = "tomada"
        if emit_canonico and emit_canonico == cnpj_canonico:
            direcao = "prestada"

        data_emissao = metadados.get("data_emissao") or texto(raiz, "dRec") or ""

        # O `resNFe` não traz nNF/serie — o XSD simplesmente não tem esses
        # campos. Sem derivar da chave, toda nota ainda em resumo aparecia na
        # listagem sem número nem série, que é como o contador identifica a
        # nota. A chave tem formato fixo (MOC), então isto é leitura, não
        # adivinhação.
        da_chave = metadados_da_chave(chave)

        return DocumentoBaixado(
            chave_acesso=chave,
            nsu=_nsu_inteiro(nsu, "0"),
            xml=xml_bytes,
            data_emissao=data_emissao,
            valor_total=valor_total,
            direcao=direcao,
            competencia=competencia_de_texto(metadados.get("competencia", ""), data_emissao)
            or da_chave.get("competencia", ""),
            leiaute="resumo" if schema.lower().startswith("res") else "completo",
            numero=metadados.get("numero") or da_chave.get("numero", ""),
            serie=metadados.get("serie") or da_chave.get("serie", ""),
            emitente_documento=metadados.get("emit_doc", ""),
            emitente_nome=metadados.get("emit_nome", ""),
            destinatario_documento=metadados.get("dest_doc", ""),
            destinatario_nome=metadados.get("dest_nome", ""),
            status_autorizacao=metadados.get("situacao", ""),
        )


def _nsu_inteiro(valor: str | None, padrao: str | None) -> str:
    """Normaliza NSU para inteiro em string (o ambiente devolve com zeros à esquerda)."""
    digitos = "".join(c for c in str(valor if valor not in (None, "") else padrao or "0") if c.isdigit())
    if not digitos:
        digitos = "".join(c for c in str(padrao or "0") if c.isdigit()) or "0"
    return str(int(digitos))
