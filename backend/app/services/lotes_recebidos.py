"""Checkpoint durável de respostas fiscais, antes de consumir seus NSUs.

Só permanece no volume o lote que não pôde ser processado por inteiro. Uma
nova execução pode relê-lo SEM repetir a consulta à SEFAZ/ADN. Os arquivos
ficam no mesmo volume persistente dos XMLs, isolados por empresa e tipo.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.models import TipoDocumentoFiscal


@dataclass(frozen=True)
class LoteRecebido:
    arquivo: Path
    cnpj: str
    nsu_anterior: str
    conteudo: bytes
    recebido_em: datetime


def _pasta(empresa_id: int, tipo: TipoDocumentoFiscal) -> Path:
    return Path(settings.dados_dir) / "xml" / ".lotes_pendentes" / str(int(empresa_id)) / tipo.value


def arquivos_pendentes(empresa_id: int, tipo: TipoDocumentoFiscal) -> list[Path]:
    return sorted(_pasta(empresa_id, tipo).glob("*.json"))


def quantidade_pendente(empresa_id: int, tipo: TipoDocumentoFiscal) -> int:
    return len(arquivos_pendentes(empresa_id, tipo))


def salvar(empresa_id: int, tipo: TipoDocumentoFiscal, cnpj: str, nsu_anterior: str, conteudo: bytes | None, *, escritorio_id: int | None = None) -> Path | None:
    if conteudo is None:
        return None
    pasta = _pasta(empresa_id, tipo)
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    identidade = hashlib.sha256(str(nsu_anterior).encode() + b"\0" + conteudo).hexdigest()
    destino = pasta / f"{int(nsu_anterior):020d}_{identidade}.json"
    registro = {
        "versao": 1,
        "recebido_em": datetime.now(timezone.utc).isoformat(),
        "empresa_id": empresa_id,
        "escritorio_id": escritorio_id,
        "tipo": tipo.value,
        "ambiente": settings.ambiente_fiscal,
        "cnpj": cnpj,
        "nsu_anterior": str(nsu_anterior),
        "conteudo": base64.b64encode(conteudo).decode("ascii"),
    }
    fd, temporario = tempfile.mkstemp(prefix=".lote-", dir=pasta)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            json.dump(registro, arquivo, ensure_ascii=False)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)
    return destino


def ler(arquivo: Path, empresa_id: int, tipo: TipoDocumentoFiscal, *, escritorio_id: int | None = None) -> LoteRecebido:
    registro = json.loads(arquivo.read_text(encoding="utf-8"))
    if registro.get("versao") != 1 or registro.get("empresa_id") != empresa_id or registro.get("tipo") != tipo.value:
        raise ValueError("Lote recebido não corresponde à empresa/tipo da execução.")
    if escritorio_id is not None and registro.get("escritorio_id") != escritorio_id:
        raise ValueError("Lote recebido não corresponde ao escritório da execução.")
    if registro.get("ambiente") != settings.ambiente_fiscal:
        raise ValueError("Lote recebido pertence a outro ambiente fiscal; não será misturado ao acervo atual.")
    return LoteRecebido(
        arquivo=arquivo,
        cnpj=registro["cnpj"],
        nsu_anterior=registro["nsu_anterior"],
        conteudo=base64.b64decode(registro["conteudo"], validate=True),
        recebido_em=datetime.fromisoformat(registro["recebido_em"]) if registro.get("recebido_em") else datetime.fromtimestamp(arquivo.stat().st_mtime, timezone.utc),
    )


def confirmar(arquivo: Path | None) -> None:
    """Chamar SOMENTE depois do commit dos documentos e do checkpoint."""
    if arquivo is not None:
        arquivo.unlink(missing_ok=True)
