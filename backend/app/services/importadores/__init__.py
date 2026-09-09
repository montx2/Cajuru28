from app.core.config import settings
from app.models import TipoDocumentoFiscal
from app.services.importadores.base import ImportadorFiscal
from app.services.importadores.cte_sefaz import ImportadorCTeSEFAZ
from app.services.importadores.nfe_sefaz import ImportadorNFeSEFAZ
from app.services.importadores.nfse_adn import ImportadorNFSeADN

_IMPORTADORES: dict[TipoDocumentoFiscal, type[ImportadorFiscal]] = {
    TipoDocumentoFiscal.NFSE: ImportadorNFSeADN,
    TipoDocumentoFiscal.NFE: ImportadorNFeSEFAZ,
    TipoDocumentoFiscal.CTE: ImportadorCTeSEFAZ,
}


def obter_importador(tipo: TipoDocumentoFiscal) -> ImportadorFiscal:
    """
    Instancia o importador do tipo pedido no ambiente fiscal configurado
    (AMBIENTE_FISCAL=producao|homologacao no .env).
    """
    ambiente = (settings.ambiente_fiscal or "producao").strip().lower()
    if ambiente not in ("producao", "homologacao"):
        ambiente = "producao"
    cls = _IMPORTADORES[tipo]
    # Todos os três aceitam ambiente= no __init__
    return cls(ambiente=ambiente)
