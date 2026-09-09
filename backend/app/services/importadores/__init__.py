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
    return _IMPORTADORES[tipo]()
