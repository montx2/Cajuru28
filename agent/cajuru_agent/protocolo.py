"""
Cliente HTTP assinado do Cajuru Agent.

Cada requisição carrega uma assinatura HMAC-SHA256 sobre::

    METODO \\n CAMINHO \\n TIMESTAMP \\n NONCE \\n sha256(corpo)

Incluir o corpo na assinatura é o que impede um proxy de trocar o resultado de
um job pelo caminho. O nonce é de uso único no servidor (janela de 5 minutos),
o que fecha a porta para replay de uma requisição capturada.

O segredo de matrícula é usado **uma única vez**, para abrir a sessão; a partir
daí tudo é assinado com a chave de sessão, que expira em 12 horas. Nenhum dos
dois aparece em log.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("cajuru.agent.protocolo")

CABECALHO_AGENTE = "X-Cajuru-Agente"
CABECALHO_CHAVE = "X-Cajuru-Chave"
CABECALHO_LEASE = "X-Cajuru-Lease"
CABECALHO_TIMESTAMP = "X-Cajuru-Timestamp"
CABECALHO_NONCE = "X-Cajuru-Nonce"
CABECALHO_ASSINATURA = "X-Cajuru-Assinatura"

TIMEOUT_PADRAO = httpx.Timeout(20.0, connect=10.0)


class ProtocoloError(RuntimeError):
    """Falha de comunicação com o Cajuru28, já traduzida para o operador."""

    def __init__(self, mensagem: str, *, status: int = 0, codigo: str = ""):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo

    @property
    def recuperavel(self) -> bool:
        """Vale tentar de novo? Rede e 5xx sim; 401/403/409 não."""
        return self.status == 0 or self.status >= 500 or self.status == 429


class SessaoExpirada(ProtocoloError):
    """A chave de sessão não vale mais; é preciso reautenticar."""


def assinar(chave: str, metodo: str, caminho: str, timestamp: str, nonce: str, corpo: bytes) -> str:
    base = "\n".join(
        [
            metodo.upper(),
            caminho,
            timestamp,
            nonce,
            hashlib.sha256(corpo or b"").hexdigest(),
        ]
    )
    return hmac.new(chave.encode("utf-8"), base.encode("utf-8"), hashlib.sha256).hexdigest()


class ClienteCajuru:
    """Fala com o servidor. Reabre a sessão sozinho quando ela expira."""

    def __init__(
        self,
        base_url: str,
        identificador: str,
        segredo: str,
        *,
        verificar_tls: bool | str = True,
        cliente_http: httpx.Client | None = None,
    ):
        base = base_url.strip().rstrip("/")
        if not base.startswith("https://") and not base.startswith("http://localhost"):
            raise ProtocoloError(
                "O endereço do Cajuru28 precisa usar HTTPS. Endereço configurado: "
                f"{base or '(vazio)'}"
            )
        self.base_url = base
        self.identificador = identificador
        self._segredo = segredo
        self._chave_sessao = ""
        self._expira_em = 0.0
        self._http = cliente_http or httpx.Client(
            base_url=base, timeout=TIMEOUT_PADRAO, verify=verificar_tls, follow_redirects=False
        )

    # -- sessão ------------------------------------------------------------

    @property
    def autenticado(self) -> bool:
        return bool(self._chave_sessao) and time.time() < self._expira_em

    def abrir_sessao(self) -> None:
        """Troca o segredo de matrícula por uma chave de sessão temporária."""
        resposta = self._http.post(
            "/procuracoes/agente/sessao",
            json={"identificador": self.identificador, "segredo": self._segredo},
        )
        if resposta.status_code == 401:
            raise ProtocoloError(
                "Credencial da estação recusada. Gere uma nova credencial no Cajuru28 "
                "(Procurações → Estações) e rode o instalador novamente.",
                status=401,
            )
        corpo = self._json_ou_erro(resposta)
        self._chave_sessao = corpo["chave_sessao"]
        # Margem de 5 min: melhor reabrir cedo do que descobrir no meio de um job.
        self._expira_em = time.time() + max(60, int(corpo.get("expira_em_segundos", 43200)) - 300)
        log.info("sessao_aberta", extra={"estacao": self.identificador})

    def encerrar_sessao(self) -> None:
        if not self._chave_sessao:
            return
        try:
            self._enviar("DELETE", "/procuracoes/agente/sessao", {})
        except ProtocoloError:
            pass  # encerrar é cortesia; a sessão expira sozinha
        finally:
            self._chave_sessao = ""

    # -- verbos ------------------------------------------------------------

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._enviar("POST", "/procuracoes/agente/heartbeat", payload)

    def enviar_inventario(self, certificados: list[dict[str, Any]]) -> dict[str, Any]:
        return self._enviar(
            "POST", "/procuracoes/agente/inventario", {"certificados": certificados}
        )

    def reivindicar(self, capacidade: int = 1) -> dict[str, Any]:
        return self._enviar(
            "POST", "/procuracoes/agente/reivindicar", {"capacidade": max(1, capacidade)}
        )

    def renovar_lease(self, job_id: int, lease: str) -> dict[str, Any]:
        return self._enviar(
            "POST", f"/procuracoes/agente/jobs/{job_id}/lease", {"lease_token": lease}
        )

    def progresso(
        self, job_id: int, lease: str, etapa: str, *, mensagem: str = "", detalhe: dict | None = None
    ) -> dict[str, Any]:
        return self._enviar(
            "POST",
            f"/procuracoes/agente/jobs/{job_id}/progresso",
            {
                "lease_token": lease,
                "etapa": etapa,
                "mensagem": mensagem,
                "detalhe": detalhe or {},
            },
        )

    def resultado(self, job_id: int, lease: str, **campos: Any) -> dict[str, Any]:
        return self._enviar(
            "POST",
            f"/procuracoes/agente/jobs/{job_id}/resultado",
            {"lease_token": lease, **campos},
        )

    def portal_alterado(
        self, job_id: int, lease: str, etapa: str, ausentes: list[str], url: str
    ) -> dict[str, Any]:
        return self._enviar(
            "POST",
            f"/procuracoes/agente/jobs/{job_id}/portal-alterado",
            {
                "lease_token": lease,
                "etapa": etapa,
                "ancoras_ausentes": ausentes,
                "url": url,
            },
        )

    def sessao_navegador(self, job_id: int, lease: str, **campos: Any) -> dict[str, Any]:
        return self._enviar(
            "POST",
            f"/procuracoes/agente/jobs/{job_id}/sessao-navegador",
            {"lease_token": lease, **campos},
        )

    def enviar_evidencia(
        self,
        job_id: int,
        lease: str,
        conteudo: bytes,
        *,
        tipo: str,
        etapa: str = "",
        url_observada: str = "",
    ) -> dict[str, Any]:
        """Evidência vai como corpo binário; o lease viaja em cabeçalho.

        Query string entra em log de proxy reverso; cabeçalho, não. E o corpo
        binário evita inflar 33% com base64 uma captura de vários megabytes.
        """
        caminho = f"/procuracoes/agente/jobs/{job_id}/evidencia"
        parametros = {}
        if etapa:
            parametros["etapa"] = etapa
        if url_observada:
            parametros["url_observada"] = url_observada
        return self._enviar_bruto(
            "POST",
            caminho,
            conteudo,
            tipo_conteudo=tipo,
            parametros=parametros,
            extras={CABECALHO_LEASE: lease},
        )

    # -- transporte --------------------------------------------------------

    def _enviar(self, metodo: str, caminho: str, payload: dict[str, Any]) -> dict[str, Any]:
        corpo = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._enviar_bruto(metodo, caminho, corpo, tipo_conteudo="application/json")

    def _enviar_bruto(
        self,
        metodo: str,
        caminho: str,
        corpo: bytes,
        *,
        tipo_conteudo: str,
        parametros: dict[str, str] | None = None,
        extras: dict[str, str] | None = None,
        _retentado: bool = False,
    ) -> dict[str, Any]:
        if not self.autenticado:
            self.abrir_sessao()

        agora = datetime.now(timezone.utc).isoformat()
        nonce = secrets.token_hex(16)
        cabecalhos = {
            CABECALHO_AGENTE: self.identificador,
            CABECALHO_CHAVE: self._chave_sessao,
            CABECALHO_TIMESTAMP: agora,
            CABECALHO_NONCE: nonce,
            CABECALHO_ASSINATURA: assinar(
                self._chave_sessao, metodo, caminho, agora, nonce, corpo
            ),
            "Content-Type": tipo_conteudo,
            **(extras or {}),
        }
        try:
            resposta = self._http.request(
                metodo, caminho, content=corpo, headers=cabecalhos, params=parametros or {}
            )
        except httpx.HTTPError as exc:
            raise ProtocoloError(f"Sem comunicação com o Cajuru28: {exc}") from exc

        if resposta.status_code == 401 and not _retentado:
            # Sessão caiu (expirou, servidor reiniciou, credencial rotacionada).
            self._chave_sessao = ""
            self.abrir_sessao()
            return self._enviar_bruto(
                metodo,
                caminho,
                corpo,
                tipo_conteudo=tipo_conteudo,
                parametros=parametros,
                extras=extras,
                _retentado=True,
            )
        return self._json_ou_erro(resposta)

    @staticmethod
    def _json_ou_erro(resposta: httpx.Response) -> dict[str, Any]:
        if resposta.status_code < 300:
            if not resposta.content:
                return {}
            try:
                return resposta.json()
            except ValueError:
                return {}

        codigo = ""
        mensagem = f"HTTP {resposta.status_code}"
        try:
            corpo = resposta.json()
            detalhe = corpo.get("detail", corpo)
            if isinstance(detalhe, dict):
                codigo = str(detalhe.get("codigo", ""))
                mensagem = str(detalhe.get("mensagem") or detalhe.get("detalhe") or mensagem)
            elif isinstance(detalhe, str):
                mensagem = detalhe
        except ValueError:
            pass

        if resposta.status_code == 401:
            raise SessaoExpirada(mensagem, status=401, codigo=codigo)
        raise ProtocoloError(mensagem, status=resposta.status_code, codigo=codigo)
