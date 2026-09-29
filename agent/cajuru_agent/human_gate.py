"""
Classificação e centralização de intervenções humanas inevitáveis.

CAPTCHA, MFA/2FA e PIN não são contornados. O Agent transforma esses eventos em
um ponto de pausa controlado, com código estável, para que o backend mantenha o
estado do job e possa retomar exatamente da etapa anterior.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass


class TipoHumanGate(str, enum.Enum):
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    TWO_FACTOR_REQUIRED = "TWO_FACTOR_REQUIRED"
    PIN_REQUIRED = "PIN_REQUIRED"
    CERTIFICATE_SELECTION_REQUIRED = "CERTIFICATE_SELECTION_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True)
class HumanGate:
    tipo: TipoHumanGate
    codigo_erro: str
    mensagem: str
    retomavel: bool = True


_PADROES: tuple[tuple[TipoHumanGate, re.Pattern[str]], ...] = (
    (TipoHumanGate.CAPTCHA_REQUIRED, re.compile(r"\b(captcha|recaptcha|desafio visual|não sou um rob[oô])\b", re.I)),
    (TipoHumanGate.TWO_FACTOR_REQUIRED, re.compile(r"\b(2fa|mfa|duplo fator|autentica[cç][aã]o em duas etapas|c[oó]digo\s+(sms|e-mail|email|app|aplicativo)|token)\b", re.I)),
    (TipoHumanGate.PIN_REQUIRED, re.compile(r"\b(pin|senha do certificado|senha do token|senha\s+a[13]|password do certificado)\b", re.I)),
    (TipoHumanGate.CERTIFICATE_SELECTION_REQUIRED, re.compile(r"\b(selecion(ar|e) certificado|janela de certificado|certificado n[aã]o foi selecionado)\b", re.I)),
)

_MENSAGENS = {
    TipoHumanGate.CAPTCHA_REQUIRED: "CAPTCHA apresentado pelo portal; operador deve resolver e acionar continuar.",
    TipoHumanGate.TWO_FACTOR_REQUIRED: "Código de verificação solicitado; operador deve informar no portal/gov.br.",
    TipoHumanGate.PIN_REQUIRED: "PIN/senha local do certificado solicitado; operador deve informar na máquina, sem registrar no Cajuru.",
    TipoHumanGate.CERTIFICATE_SELECTION_REQUIRED: "Navegador abriu seletor de certificados; configurar AutoSelectCertificateForUrls ou escolher manualmente uma vez.",
    TipoHumanGate.MANUAL_REVIEW: "Intervenção humana necessária; o motivo informado não foi classificado automaticamente.",
}


def classificar_intervencao(texto: str) -> HumanGate:
    """Transforma texto observado pelo operador/Playwright em código estável."""
    observado = (texto or "").strip()
    for tipo, padrao in _PADROES:
        if padrao.search(observado):
            return HumanGate(tipo=tipo, codigo_erro=tipo.value, mensagem=_MENSAGENS[tipo])
    return HumanGate(
        tipo=TipoHumanGate.MANUAL_REVIEW,
        codigo_erro=TipoHumanGate.MANUAL_REVIEW.value,
        mensagem=observado or _MENSAGENS[TipoHumanGate.MANUAL_REVIEW],
    )


def pauseForCaptcha(detalhe: str = "") -> HumanGate:  # noqa: N802 - API operacional pedida no requisito
    return HumanGate(
        tipo=TipoHumanGate.CAPTCHA_REQUIRED,
        codigo_erro=TipoHumanGate.CAPTCHA_REQUIRED.value,
        mensagem=detalhe or _MENSAGENS[TipoHumanGate.CAPTCHA_REQUIRED],
    )


def pauseForTwoFactor(detalhe: str = "") -> HumanGate:  # noqa: N802
    return HumanGate(
        tipo=TipoHumanGate.TWO_FACTOR_REQUIRED,
        codigo_erro=TipoHumanGate.TWO_FACTOR_REQUIRED.value,
        mensagem=detalhe or _MENSAGENS[TipoHumanGate.TWO_FACTOR_REQUIRED],
    )


def pauseForPin(detalhe: str = "") -> HumanGate:  # noqa: N802
    return HumanGate(
        tipo=TipoHumanGate.PIN_REQUIRED,
        codigo_erro=TipoHumanGate.PIN_REQUIRED.value,
        mensagem=detalhe or _MENSAGENS[TipoHumanGate.PIN_REQUIRED],
    )


def pauseForManualReview(detalhe: str = "") -> HumanGate:  # noqa: N802
    return HumanGate(
        tipo=TipoHumanGate.MANUAL_REVIEW,
        codigo_erro=TipoHumanGate.MANUAL_REVIEW.value,
        mensagem=detalhe or _MENSAGENS[TipoHumanGate.MANUAL_REVIEW],
        retomavel=True,
    )
