"""
Importador de CT-e via SEFAZ — Distribuição DFe.

STATUS: esqueleto (Fase 3 do roadmap). Agora que app/services/importadores/
nfe_sefaz.py está implementado, isto fica bem mais mecânico: mesmo
webservice (NFeDistribuicaoDFe), mesmo envelope, mesma lógica de cStat —
o módulo compartilhado (`_distribuicao_dfe.py`) já cobre tudo isso.

O que muda de verdade em relação a nfe_sefaz.py:
- O schema dentro do docZip é diferente (algo como "resCTe.../procCTe..."
  em vez de "resNFe"/"procNFe" — confirmar o nome exato contra um docZip
  real antes de fixar no código, não adivinhar).
- Os nomes dos campos de valor/data dentro do XML do CT-e são diferentes
  dos da NFe (CT-e não tem exatamente `vNF`/`dhEmi` na mesma estrutura —
  precisa checar o schema do CT-e especificamente).

Ou seja: dá para copiar a estrutura de `ImportadorNFeSEFAZ` quase inteira
(reaproveitando `montar_envelope`/`chamar_com_retentativa` de
`_distribuicao_dfe.py`) e só reescrever `_converter_doc_zip` para o schema
do CT-e.
"""

from app.services.importadores.base import ImportadorFiscal, LoteImportado


class ImportadorCTeSEFAZ(ImportadorFiscal):
    def buscar_lote(
        self,
        cnpj: str,
        cert_path: str,
        key_path: str,
        ultimo_nsu: str,
        uf: str | None = None,
    ) -> LoteImportado:
        raise NotImplementedError(
            "Importador de CT-e ainda não implementado — ver docstring deste arquivo e docs/ROADMAP.md (Fase 3)."
        )
