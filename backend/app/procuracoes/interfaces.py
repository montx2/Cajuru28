"""
Interfaces formais do subsistema de Autorizações de Acesso.

O módulo já tinha serviços concretos (`servicos/fila.py`, `servicos/eventos.py`,
`servicos/certificados.py` etc.). Este arquivo explicita os contratos para que
novas implementações — por exemplo uma API oficial futura de outorga ou um
executor Playwright autorizado — entrem sem acoplar fila, certificado,
autenticação, assinatura e auditoria.

Nenhuma interface abaixo autoriza burlar CAPTCHA/MFA ou inventar endpoint. Elas
apenas deixam claro onde cada responsabilidade pertence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from app.procuracoes.estados import CodigoErro, StatusJob, TipoCertificado


@dataclass(frozen=True)
class ExpectedAuthorization:
    outorgante_documento: str
    outorgado_documento: str
    vigencia_ate: date
    escopo_servicos: str = "ALL"
    servicos: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActualPortalData:
    outorgante_documento: str = ""
    outorgado_documento: str = ""
    vigencia_ate: date | None = None
    escopo_servicos: str = ""
    servicos: tuple[str, ...] = ()
    situacao: str = ""
    protocolo: str = ""
    capturado_em: datetime | None = None


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    divergencias: tuple[str, ...] = ()
    codigo_erro: CodigoErro | None = None


@dataclass(frozen=True)
class CertificateSelection:
    ok: bool
    thumbprint: str = ""
    referencia_local: str = ""
    tipo: TipoCertificado = TipoCertificado.CLIENTE
    codigo_erro: CodigoErro | None = None
    mensagem: str = ""


@dataclass(frozen=True)
class HumanGateRequest:
    job_id: int
    codigo: CodigoErro
    etapa: str
    mensagem: str
    retomavel: bool = True
    detalhe: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PortalClient(Protocol):
    def abrir(self, url: str) -> None: ...
    def verificar_identidade(self, documento_esperado: str) -> ValidationResult: ...
    def ler_resumo(self) -> ActualPortalData: ...
    def capturar_evidencia(self, etapa: str) -> str: ...


@runtime_checkable
class AuthenticationProvider(Protocol):
    def autenticar(self, documento: str, certificado: CertificateSelection) -> ValidationResult: ...
    def detectar_human_gate(self) -> HumanGateRequest | None: ...


@runtime_checkable
class CertificateProvider(Protocol):
    def selecionar(self, documento: str, tipo: TipoCertificado) -> CertificateSelection: ...
    def diagnosticar_store(self) -> dict[str, Any]: ...


@runtime_checkable
class SignatureProvider(Protocol):
    def diagnosticar(self) -> dict[str, Any]: ...
    def assinar_quando_suportado(self, payload: bytes, certificado: CertificateSelection) -> bytes: ...


@runtime_checkable
class AuthorizationProvider(Protocol):
    def consultar_existente(self, esperado: ExpectedAuthorization) -> ActualPortalData | None: ...
    def validar_pre_assinatura(self, esperado: ExpectedAuthorization, atual: ActualPortalData) -> ValidationResult: ...
    def reconciliar(self, job_id: int) -> ActualPortalData | None: ...


@runtime_checkable
class SessionManager(Protocol):
    def abrir_contexto(self, job_id: int, identidade: TipoCertificado) -> str: ...
    def encerrar_contexto(self, session_id: str) -> None: ...


@runtime_checkable
class JobQueue(Protocol):
    def reivindicar(self, capacidade: int) -> list[int]: ...
    def mudar_estado(self, job_id: int, destino: StatusJob, mensagem: str = "") -> None: ...


@runtime_checkable
class StateStore(Protocol):
    def salvar_checkpoint(self, job_id: int, estado: StatusJob, detalhe: dict[str, Any]) -> None: ...
    def carregar_checkpoint(self, job_id: int) -> dict[str, Any]: ...


@runtime_checkable
class ErrorClassifier(Protocol):
    def classificar(self, exc: Exception | str) -> CodigoErro: ...
    def deve_retentar(self, codigo: CodigoErro, tentativas: int) -> bool: ...


@runtime_checkable
class AuditLogger(Protocol):
    def registrar(self, job_id: int, tipo: str, mensagem: str, detalhe: dict[str, Any] | None = None) -> None: ...


@runtime_checkable
class NotificationService(Protocol):
    def avisar(self, chave: str, nivel: str, titulo: str, detalhe: str = "") -> None: ...


@runtime_checkable
class HumanInteractionManager(Protocol):
    def pauseForCaptcha(self, pedido: HumanGateRequest) -> None: ...  # noqa: N802
    def pauseForTwoFactor(self, pedido: HumanGateRequest) -> None: ...  # noqa: N802
    def pauseForPin(self, pedido: HumanGateRequest) -> None: ...  # noqa: N802
    def pauseForManualReview(self, pedido: HumanGateRequest) -> None: ...  # noqa: N802
    def resumeJob(self, job_id: int) -> None: ...  # noqa: N802
