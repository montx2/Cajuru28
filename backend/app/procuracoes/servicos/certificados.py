"""
Associação **determinística** entre empresa e certificado A1.

A regra que não pode ser quebrada: `Cliente X → certificado X → job X`.
Nunca "pegar qualquer certificado". Quando a correspondência não é única e
comprovada, o resultado é `CERTIFICADO_AMBIGUO` e o job vai para intervenção
manual — assinar em nome da empresa errada é um ato jurídico irreversível.

A correspondência é feita sobre metadados que o Agent extrai do X.509 na
estação (o servidor nunca vê a chave privada):

1. `documento` — CNPJ/CPF do titular lido da extensão ICP-Brasil
   (`subjectAltName otherName` 2.16.76.1.3.3 / 2.16.76.1.3.1);
2. `thumbprint` — SHA-256 do DER, identificador global do certificado;
3. `subject`/`numero_serie` — apenas para exibição e desempate humano.

A âncora é sempre (1). `subject` textual jamais decide sozinho: razão social
muda, CNPJ não.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.documentos import normalizar_documento
from app.procuracoes.estados import CodigoErro, TipoCertificado
from app.procuracoes.modelos import Agente, CertificadoInventario

#: Margem de segurança: um A1 que vence hoje não sobrevive a um fluxo de
#: outorga + assinatura que pode levar minutos e ser retomado amanhã.
MARGEM_VALIDADE = timedelta(days=1)


@dataclass(frozen=True)
class ResultadoSelecao:
    """Resposta única da seleção — sucesso e falha têm a mesma forma."""

    ok: bool
    certificado: CertificadoInventario | None = None
    codigo_erro: CodigoErro | None = None
    mensagem: str = ""
    #: Candidatos considerados, para a tela explicar a ambiguidade.
    candidatos: tuple[CertificadoInventario, ...] = ()

    @property
    def thumbprint(self) -> str:
        return self.certificado.thumbprint if self.certificado else ""


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def documento_normalizado(valor: str | None) -> str:
    try:
        return normalizar_documento(valor)
    except (ValueError, TypeError):
        return ""


def _vigente(certificado: CertificadoInventario, agora: datetime) -> bool:
    fim = _aware(certificado.valido_ate)
    if fim is None:
        return False
    if fim <= agora + MARGEM_VALIDADE:
        return False
    inicio = _aware(certificado.valido_de)
    return not (inicio and inicio > agora)


def selecionar_para_documento(
    db: Session,
    escritorio_id: int,
    documento: str,
    *,
    tipo: TipoCertificado = TipoCertificado.CLIENTE,
    agente_id: int | None = None,
    thumbprint_preferido: str = "",
    agora: datetime | None = None,
) -> ResultadoSelecao:
    """Escolhe o certificado da identidade `documento`, ou explica por que não dá.

    `thumbprint_preferido` permite que o operador fixe manualmente qual
    certificado usar para uma empresa — a escolha humana ganha da heurística,
    mas continua sendo validada contra o CNPJ.
    """
    agora = agora or datetime.now(timezone.utc)
    alvo = documento_normalizado(documento)
    if not alvo:
        return ResultadoSelecao(
            ok=False,
            codigo_erro=CodigoErro.DADOS_INSUFICIENTES,
            mensagem="A empresa está sem CNPJ/CPF válido no cadastro.",
        )

    consulta = db.query(CertificadoInventario).filter(
        CertificadoInventario.escritorio_id == escritorio_id,
        CertificadoInventario.documento == alvo,
        CertificadoInventario.tipo == tipo.value,
    )
    if agente_id is not None:
        consulta = consulta.filter(CertificadoInventario.agente_id == agente_id)
    encontrados = consulta.order_by(CertificadoInventario.valido_ate.desc()).all()

    if not encontrados:
        # Existe algum certificado na frota com outro documento? Isso muda a
        # mensagem: "não achei" é diferente de "achei, mas é de outra empresa".
        houve_na_estacao = (
            db.query(CertificadoInventario)
            .filter(
                CertificadoInventario.escritorio_id == escritorio_id,
                CertificadoInventario.agente_id == agente_id,
            )
            .count()
            if agente_id is not None
            else 0
        )
        if houve_na_estacao:
            return ResultadoSelecao(
                ok=False,
                codigo_erro=CodigoErro.CERTIFICADO_NAO_CORRESPONDE,
                mensagem=(
                    "A estação tem certificados instalados, mas nenhum pertence ao "
                    f"documento {alvo}. Nada foi executado."
                ),
            )
        return ResultadoSelecao(
            ok=False,
            codigo_erro=CodigoErro.CERTIFICADO_NAO_ENCONTRADO,
            mensagem=f"Nenhum certificado A1 de {alvo} foi inventariado nesta estação.",
        )

    if thumbprint_preferido:
        fixado = next(
            (c for c in encontrados if c.thumbprint == thumbprint_preferido), None
        )
        if fixado is None:
            return ResultadoSelecao(
                ok=False,
                codigo_erro=CodigoErro.CERTIFICADO_NAO_ENCONTRADO,
                mensagem=(
                    "O certificado fixado para esta empresa não está mais disponível "
                    "na estação designada."
                ),
                candidatos=tuple(encontrados),
            )
        encontrados = [fixado]

    vigentes = [c for c in encontrados if _vigente(c, agora)]
    if not vigentes:
        mais_recente = max(
            encontrados, key=lambda c: _aware(c.valido_ate) or datetime.min.replace(tzinfo=timezone.utc)
        )
        fim = _aware(mais_recente.valido_ate)
        quando = fim.date().isoformat() if fim else "desconhecida"
        return ResultadoSelecao(
            ok=False,
            codigo_erro=CodigoErro.CERTIFICADO_EXPIRADO,
            mensagem=(
                f"O certificado A1 de {alvo} está vencido (validade {quando}). "
                "Renove antes de processar."
            ),
            candidatos=tuple(encontrados),
        )

    disponiveis = [c for c in vigentes if c.situacao == "disponivel"]
    if not disponiveis:
        return ResultadoSelecao(
            ok=False,
            codigo_erro=CodigoErro.CERTIFICADO_INDISPONIVEL,
            mensagem=(
                "O certificado existe e está vigente, mas a estação o reportou como "
                "indisponível na última verificação."
            ),
            candidatos=tuple(vigentes),
        )

    distintos = {c.thumbprint for c in disponiveis}
    if len(distintos) > 1:
        return ResultadoSelecao(
            ok=False,
            codigo_erro=CodigoErro.CERTIFICADO_AMBIGUO,
            mensagem=(
                f"Há {len(distintos)} certificados vigentes para {alvo}. "
                "Escolha explicitamente qual deve ser usado — o sistema não escolhe "
                "certificado por conta própria."
            ),
            candidatos=tuple(disponiveis),
        )

    return ResultadoSelecao(ok=True, certificado=disponiveis[0], candidatos=tuple(disponiveis))


def agentes_com_certificado(
    db: Session,
    escritorio_id: int,
    documento: str,
    *,
    tipo: TipoCertificado = TipoCertificado.CLIENTE,
    agora: datetime | None = None,
) -> list[int]:
    """Estações que têm um A1 vigente daquela identidade.

    É o que permite rotear o job para a máquina certa em vez de descobrir na
    hora H que o certificado está na sala ao lado.
    """
    agora = agora or datetime.now(timezone.utc)
    alvo = documento_normalizado(documento)
    if not alvo:
        return []
    linhas = (
        db.query(CertificadoInventario)
        .filter(
            CertificadoInventario.escritorio_id == escritorio_id,
            CertificadoInventario.documento == alvo,
            CertificadoInventario.tipo == tipo.value,
            CertificadoInventario.situacao == "disponivel",
        )
        .all()
    )
    return sorted({linha.agente_id for linha in linhas if _vigente(linha, agora)})


def sincronizar_inventario(
    db: Session,
    agente: Agente,
    itens: list[dict],
    *,
    agora: datetime | None = None,
) -> dict[str, int]:
    """Atualiza o inventário da estação de forma idempotente.

    Chave natural: (agente, thumbprint). Certificado que sumiu da máquina não é
    apagado — vira `indisponivel`, para que o histórico de "qual certificado
    assinou o quê" continue resolvível.
    """
    agora = agora or datetime.now(timezone.utc)
    existentes = {
        linha.thumbprint: linha
        for linha in db.query(CertificadoInventario)
        .filter(CertificadoInventario.agente_id == agente.id)
        .all()
    }
    vistos: set[str] = set()
    criados = atualizados = invalidos = 0

    for item in itens:
        thumbprint = str(item.get("thumbprint") or "").strip().lower()
        if len(thumbprint) != 64 or not all(c in "0123456789abcdef" for c in thumbprint):
            invalidos += 1
            continue
        documento = documento_normalizado(item.get("documento"))
        if not documento:
            invalidos += 1
            continue

        linha = existentes.get(thumbprint)
        if linha is None:
            linha = CertificadoInventario(
                escritorio_id=agente.escritorio_id,
                agente_id=agente.id,
                thumbprint=thumbprint,
            )
            db.add(linha)
            criados += 1
        else:
            atualizados += 1

        linha.documento = documento
        linha.subject = str(item.get("subject") or "")[:500]
        linha.issuer = str(item.get("issuer") or "")[:500]
        linha.numero_serie = str(item.get("numero_serie") or "")[:80]
        linha.titular_nome = str(item.get("titular_nome") or "")[:255]
        linha.valido_de = _parse_data(item.get("valido_de"))
        linha.valido_ate = _parse_data(item.get("valido_ate"))
        linha.origem = "arquivo" if str(item.get("origem")) == "arquivo" else "windows_store"
        linha.referencia_local = str(item.get("referencia_local") or "")[:128]
        linha.tipo = (
            TipoCertificado.CONTABILIDADE.value
            if str(item.get("tipo")) == TipoCertificado.CONTABILIDADE.value
            else TipoCertificado.CLIENTE.value
        )
        linha.senha_disponivel = bool(item.get("senha_disponivel"))
        linha.ultimo_erro = str(item.get("erro") or "")[:255]
        linha.ultima_validacao_em = agora
        linha.visto_em = agora
        linha.situacao = _situacao(linha, item, agora)
        vistos.add(thumbprint)

    sumidos = 0
    for thumbprint, linha in existentes.items():
        if thumbprint in vistos:
            continue
        if linha.situacao != "indisponivel":
            linha.situacao = "indisponivel"
            linha.ultimo_erro = "Não encontrado no último inventário da estação."
            sumidos += 1

    db.flush()
    return {
        "criados": criados,
        "atualizados": atualizados,
        "invalidos": invalidos,
        "indisponiveis": sumidos,
        "total": len(vistos),
    }


def _situacao(linha: CertificadoInventario, item: dict, agora: datetime) -> str:
    if item.get("erro"):
        return "indisponivel"
    if not item.get("tem_chave_privada", True):
        return "sem_chave_privada"
    fim = _aware(linha.valido_ate)
    if fim is None or fim <= agora:
        return "expirado"
    return "disponivel"


def _parse_data(valor) -> datetime | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    try:
        texto = str(valor).replace("Z", "+00:00")
        convertido = datetime.fromisoformat(texto)
    except (TypeError, ValueError):
        return None
    return convertido if convertido.tzinfo else convertido.replace(tzinfo=timezone.utc)


def certificados_expirando(
    db: Session, escritorio_id: int, dias: int, *, agora: datetime | None = None
) -> list[CertificadoInventario]:
    """A1 que vencem dentro de `dias` — insumo das notificações."""
    agora = agora or datetime.now(timezone.utc)
    limite = agora + timedelta(days=max(0, dias))
    return (
        db.query(CertificadoInventario)
        .filter(
            CertificadoInventario.escritorio_id == escritorio_id,
            CertificadoInventario.situacao.in_(["disponivel", "expirado"]),
            CertificadoInventario.valido_ate.isnot(None),
            CertificadoInventario.valido_ate <= limite,
        )
        .order_by(CertificadoInventario.valido_ate)
        .all()
    )


def documentos_disponiveis(
    db: Session, agente: Agente, *, agora: datetime | None = None
) -> list[str]:
    """CNPJ/CPF que esta estação consegue representar agora.

    É o insumo do roteamento: a fila só entrega a uma máquina o job cujo
    certificado está nela. Evita o job que viaja até a estação errada e
    volta como falha.
    """
    agora = agora or datetime.now(timezone.utc)
    linhas = (
        db.query(CertificadoInventario)
        .filter(
            CertificadoInventario.agente_id == agente.id,
            CertificadoInventario.situacao == "disponivel",
            CertificadoInventario.documento != "",
        )
        .all()
    )
    return sorted({linha.documento for linha in linhas if _vigente(linha, agora)})
