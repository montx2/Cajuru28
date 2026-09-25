"""
Evidências de execução: captura de tela, HTML e recibo do portal.

Por que existem: quando um job para, a pergunta do operador é sempre "o que
apareceu na tela?". Sem evidência, a resposta é reconstrução de memória; com
evidência, é fato. E quando a Receita muda o portal, a captura é o que prova
que a mudança aconteceu e onde.

Três regras que valem para todo arquivo aqui:

1. **Fora do banco.** O binário vai para o volume de dados; a linha guarda
   ponteiro, tamanho e `sha256` do conteúdo original. Banco de dados não é
   sistema de arquivos.
2. **Cifrado em repouso.** Uma captura do e-CAC mostra dados do contribuinte.
   Usa-se o cofre Fernet já existente (`app.core.vault`) — nada de cifra
   caseira.
3. **Sem segredo dentro.** O Agent é instruído a nunca capturar campo de
   senha ou PIN. Aqui, por garantia, texto/HTML passa por redação de padrões
   sensíveis antes de gravar.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.vault import cifrar_bytes, decifrar_bytes
from app.procuracoes.modelos import JobEvidencia, JobProcuracao

log = logging.getLogger("cajuru.procuracoes.evidencias")

PASTA_RAIZ = "procuracoes"

#: Só o que serve de prova visual ou textual. Nada executável.
TIPOS_ACEITOS: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "text/html": ".html",
    "text/plain": ".txt",
    "application/json": ".json",
    "application/pdf": ".pdf",
}

#: Assinatura binária → tipo real. Extensão declarada não é prova de nada.
_ASSINATURAS: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"%PDF-", "application/pdf"),
)

LIMITE_PADRAO_MB = 8

_PADROES_SENSIVEIS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(senha|password|pin|pwd)\s*[:=]\s*\S+"), r"\1: [redigido]"),
    (
        re.compile(r"(?i)<input[^>]*type\s*=\s*[\"']password[\"'][^>]*>"),
        "<input type=\"password\" value=\"[redigido]\">",
    ),
    (re.compile(r"(?i)(authorization|cookie|set-cookie)\s*:\s*[^\r\n]+"), r"\1: [redigido]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
     "[chave privada removida]"),
)


class EvidenciaError(RuntimeError):
    def __init__(self, mensagem: str, status_code: int = 422):
        super().__init__(mensagem)
        self.status_code = status_code


@dataclass(frozen=True)
class EvidenciaGravada:
    registro: JobEvidencia
    caminho: Path


def pasta_base() -> Path:
    return Path(settings.dados_dir) / PASTA_RAIZ


def _limite_bytes() -> int:
    mb = getattr(settings, "procuracoes_evidencia_max_mb", LIMITE_PADRAO_MB)
    return max(1, int(mb)) * 1024 * 1024


def _tipo_real(conteudo: bytes, declarado: str) -> str:
    for assinatura, tipo in _ASSINATURAS:
        if conteudo.startswith(assinatura):
            return tipo
    if declarado in {"text/html", "text/plain", "application/json"}:
        return declarado
    if conteudo[:12].startswith(b"RIFF") and conteudo[8:12] == b"WEBP":
        return "image/webp"
    raise EvidenciaError(
        "Tipo de evidência não reconhecido. Aceitos: PNG, JPEG, WEBP, PDF, HTML, TXT e JSON."
    )


def _redigir(conteudo: bytes, tipo: str) -> bytes:
    if tipo not in {"text/html", "text/plain", "application/json"}:
        return conteudo
    try:
        texto = conteudo.decode("utf-8")
    except UnicodeDecodeError:
        return conteudo
    for padrao, substituto in _PADROES_SENSIVEIS:
        texto = padrao.sub(substituto, texto)
    return texto.encode("utf-8")


def _destino(job: JobProcuracao, extensao: str) -> Path:
    """Caminho derivado só de inteiros e de um UUID — nome de arquivo do
    cliente nunca entra no path (é assim que se evita `../../`)."""
    nome = f"{uuid.uuid4().hex}{extensao}"
    return pasta_base() / str(int(job.escritorio_id)) / str(int(job.id)) / nome


def gravar(
    db: Session,
    job: JobProcuracao,
    *,
    conteudo: bytes,
    tipo_declarado: str,
    etapa: str = "",
    url_observada: str = "",
) -> EvidenciaGravada:
    """Cifra, grava atomicamente e registra o ponteiro. Sem commit."""
    if not conteudo:
        raise EvidenciaError("Evidência vazia.")
    if len(conteudo) > _limite_bytes():
        raise EvidenciaError(
            f"Evidência acima do limite de {_limite_bytes() // (1024 * 1024)} MiB.",
            status_code=413,
        )

    tipo = _tipo_real(conteudo, (tipo_declarado or "").split(";")[0].strip().lower())
    if tipo not in TIPOS_ACEITOS:
        raise EvidenciaError(f"Tipo '{tipo}' não aceito como evidência.")

    limpo = _redigir(conteudo, tipo)
    digest = hashlib.sha256(limpo).hexdigest()
    destino = _destino(job, TIPOS_ACEITOS[tipo])
    destino.parent.mkdir(parents=True, exist_ok=True)

    cifrado = cifrar_bytes(limpo)
    descritor, temporario = tempfile.mkstemp(dir=str(destino.parent), suffix=".parcial")
    try:
        with os.fdopen(descritor, "wb") as saida:
            saida.write(cifrado)
        os.chmod(temporario, 0o600)
        os.replace(temporario, destino)
    except Exception:
        try:
            os.unlink(temporario)
        except OSError:
            pass
        raise

    registro = JobEvidencia(
        job_id=job.id,
        etapa=(etapa or "")[:40],
        tipo=tipo,
        caminho_relativo=str(destino.relative_to(pasta_base())),
        tamanho_bytes=len(limpo),
        sha256=digest,
        url_observada=_url_segura(url_observada),
    )
    db.add(registro)
    db.flush()
    log.info(
        "procuracao_evidencia_gravada",
        extra={"job": job.id, "tipo": tipo, "bytes": len(limpo), "etapa": etapa},
    )
    return EvidenciaGravada(registro=registro, caminho=destino)


def ler(registro: JobEvidencia) -> bytes:
    """Abre a evidência e confere o `sha256` — adulteração em disco aparece."""
    caminho = _resolver(registro.caminho_relativo)
    if not caminho.is_file():
        raise EvidenciaError("Arquivo de evidência não encontrado no volume.", status_code=404)
    conteudo = decifrar_bytes(caminho.read_bytes())
    if hashlib.sha256(conteudo).hexdigest() != registro.sha256:
        log.error("procuracao_evidencia_corrompida", extra={"evidencia": registro.id})
        raise EvidenciaError(
            "A evidência não confere com o hash registrado.", status_code=409
        )
    return conteudo


def _url_segura(valor: str) -> str:
    """Guarda só a URL sem query string: parâmetros carregam identificadores
    de sessão do portal e não têm valor probatório."""
    texto = str(valor or "").strip()
    if not texto:
        return ""
    return texto.split("?")[0].split("#")[0][:500]


def _resolver(relativo: str) -> Path:
    """Impede que um valor manipulado no banco escape da pasta de evidências."""
    base = pasta_base().resolve()
    alvo = (base / str(relativo or "")).resolve()
    if base != alvo and base not in alvo.parents:
        raise EvidenciaError("Caminho de evidência inválido.", status_code=400)
    return alvo


def expurgar(db: Session, *, dias: int | None = None, agora: datetime | None = None) -> int:
    """Remove evidências vencidas.

    Evidência é prova operacional com prazo, não trilha de auditoria — a
    trilha (`procuracao_job_eventos`) nunca é apagada. Manter captura de tela
    do e-CAC para sempre seria acumular dado pessoal sem finalidade.
    """
    limite_dias = int(
        dias if dias is not None else getattr(settings, "procuracoes_evidencia_retencao_dias", 180)
    )
    if limite_dias <= 0:
        return 0
    corte = (agora or datetime.now(timezone.utc)) - timedelta(days=limite_dias)
    vencidas = db.query(JobEvidencia).filter(JobEvidencia.criado_em < corte).all()
    removidas = 0
    for registro in vencidas:
        try:
            caminho = _resolver(registro.caminho_relativo)
            if caminho.is_file():
                caminho.unlink()
        except (EvidenciaError, OSError) as exc:
            log.warning(
                "procuracao_evidencia_expurgo_falhou",
                extra={"evidencia": registro.id, "erro": str(exc)},
            )
        db.delete(registro)
        removidas += 1
    db.flush()
    if removidas:
        log.info("procuracao_evidencias_expurgadas", extra={"total": removidas, "dias": limite_dias})
    return removidas
