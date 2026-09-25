"""
Laço principal do Cajuru Agent.

Responsabilidades, na ordem em que acontecem:

1. abrir sessão assinada com o Cajuru28;
2. inventariar certificados e diagnosticar o Assinador SERPRO;
3. bater heartbeat enquanto estiver vivo;
4. pedir trabalho e conduzir o operador, etapa por etapa;
5. relatar cada avanço, cada evidência e cada parada.

Regras de sobrevivência embutidas:

- **falha de rede não perde trabalho**: o lease do job expira no servidor e o
  job volta sozinho para a fila, no mesmo ponto em que parou;
- **erro permanente não vira loop**: o Agent distingue "tentar de novo" de
  "isso não vai melhorar sozinho" pelo status HTTP e pelo código devolvido;
- **nada é dado como concluído sem confirmação real** do portal.
"""

from __future__ import annotations

import logging
import platform
import signal
import time
from pathlib import Path

from . import assinador as diag_assinador
from . import certificados as inventario
from .config import Configuracao
from .protocolo import ClienteCajuru, ProtocoloError
from .roteiro import ConducaoConsole, OperacaoCancelada

log = logging.getLogger("cajuru.agent")

VERSAO_AGENTE = "1.0.0"

#: Espera entre tentativas quando o servidor está fora do ar. Cresce até o
#: teto para não martelar um servidor em manutenção.
ESPERA_INICIAL = 15
ESPERA_MAXIMA = 300


class Agente:
    def __init__(self, config: Configuracao, cliente: ClienteCajuru, *, conducao=None):
        self.config = config
        self.cliente = cliente
        self.conducao = conducao or ConducaoConsole(navegador=config.navegador)
        self._parar = False
        self._ultimo_heartbeat = 0.0
        self._ultimo_inventario = 0.0
        self._espera = ESPERA_INICIAL

    # -- ciclo de vida -----------------------------------------------------

    def solicitar_parada(self, *_args) -> None:
        log.info("parada_solicitada")
        self._parar = True

    def instalar_sinais(self) -> None:
        for sinal in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sinal, self.solicitar_parada)
            except (ValueError, OSError):
                pass  # sem terminal (serviço do Windows): segue sem handler

    # -- coleta ------------------------------------------------------------

    def coletar_certificados(self) -> list[inventario.CertificadoLocal]:
        pasta = Path(self.config.pasta_pfx) if self.config.pasta_pfx else None
        encontrados = inventario.inventariar(pasta)
        log.info("inventario_local", extra={"total": len(encontrados)})
        return encontrados

    def enviar_inventario(self, certificados) -> dict:
        return self.cliente.enviar_inventario([c.para_envio() for c in certificados])

    def bater_heartbeat(self, certificados) -> dict:
        tem_certificado = any(
            inventario.vigente(c) and c.tem_chave_privada for c in certificados
        )
        diagnostico = diag_assinador.diagnosticar(tem_certificado=tem_certificado)
        for observacao in diagnostico.observacoes:
            log.info("assinador: %s", observacao)
        return self.cliente.heartbeat(
            {
                "versao_agente": VERSAO_AGENTE,
                "versao_navegador": platform.platform(),
                "assinador": diagnostico.para_envio(),
            }
        )

    # -- trabalho ----------------------------------------------------------

    def executar_ordem(self, ordem: dict) -> None:
        """Conduz uma ordem de trabalho do começo ao fim (ou até parar)."""
        job_id = int(ordem["job_id"])
        lease = str(ordem["lease_token"])
        fase = str(ordem.get("fase") or "outorga")
        roteiro = list(ordem.get("roteiro") or [])

        self.conducao.cabecalho(ordem)
        total = len(roteiro)

        for indice, passo in enumerate(roteiro, start=1):
            etapa = str(passo.get("etapa") or "")
            try:
                resposta = self.conducao.conduzir_etapa(passo, indice, total)
            except OperacaoCancelada as exc:
                self.cliente.resultado(
                    job_id,
                    lease,
                    resultado="intervencao",
                    codigo_erro="OPERADOR_INTERROMPEU",
                    mensagem=str(exc),
                )
                self.conducao.avisar("Job devolvido para a fila no ponto atual.")
                return

            if resposta.portal_alterado:
                self.cliente.portal_alterado(
                    job_id,
                    lease,
                    etapa,
                    [resposta.texto] if resposta.texto else [],
                    str(passo.get("url") or ""),
                )
                self.conducao.avisar(
                    "Portal alterado: o job foi interrompido e a equipe técnica avisada. "
                    "Nenhum clique às cegas será feito."
                )
                return

            if resposta.intervencao:
                self.cliente.resultado(
                    job_id,
                    lease,
                    resultado="intervencao",
                    codigo_erro="DESAFIO_DE_SEGURANCA",
                    mensagem=resposta.texto or "Desafio apresentado pelo portal.",
                )
                self.conducao.avisar(
                    "Job marcado como intervenção manual. Conclua no portal se for o caso "
                    "e registre o resultado pelo Cajuru28."
                )
                return

            if etapa and str(passo.get("executor")) != "sistema":
                self.cliente.progresso(job_id, lease, etapa, mensagem="Etapa confirmada pelo operador.")
                self.cliente.renovar_lease(job_id, lease)

        protocolo, confirmacao = self.conducao.pedir_confirmacao_final(fase)
        if not protocolo and not confirmacao:
            self.cliente.resultado(
                job_id,
                lease,
                resultado="intervencao",
                codigo_erro="CONFIRMACAO_AUSENTE",
                mensagem=(
                    "Operador não informou protocolo nem texto de confirmação do portal. "
                    "A fase não pode ser dada como concluída."
                ),
            )
            self.conducao.avisar(
                "Sem confirmação do portal o job não avança — é a regra que impede "
                "registrar como assinado algo que não foi."
            )
            return

        resultado = self.cliente.resultado(
            job_id,
            lease,
            resultado="outorga_registrada" if fase == "outorga" else "aceite_registrado",
            protocolo=protocolo,
            confirmacao_portal=confirmacao,
        )
        self.conducao.avisar(f"Registrado. Situação do job: {resultado.get('status')}.")

    # -- laço --------------------------------------------------------------

    def rodar(self, *, ciclos: int | None = None) -> int:
        """Laço principal. `ciclos` limita as iterações (usado em teste)."""
        self.instalar_sinais()
        executados = 0

        while not self._parar and (ciclos is None or executados < ciclos):
            executados += 1
            try:
                certificados = self._certificados_do_ciclo()
                resposta = self.bater_heartbeat(certificados)
                self._espera = ESPERA_INICIAL

                if not resposta.get("assinador_apto", False):
                    self._avisar_assinador(resposta)
                    self._dormir(self.config.intervalo_heartbeat_segundos)
                    continue

                entrega = self.cliente.reivindicar(self.config.capacidade)
                ordens = entrega.get("ordens") or []
                if not ordens:
                    self._dormir(
                        int(entrega.get("intervalo_busca_segundos") or self.config.intervalo_busca_segundos)
                    )
                    continue

                for ordem in ordens:
                    if self._parar:
                        break
                    self.executar_ordem(ordem)

            except ProtocoloError as exc:
                if exc.codigo == "ASSINADOR_NAO_INSTALADO":
                    self._avisar_assinador({"assinador_detalhe": str(exc)})
                    self._dormir(self.config.intervalo_heartbeat_segundos)
                    continue
                if not exc.recuperavel:
                    log.error("erro_permanente: %s", exc)
                    print(f"\n  ✖ {exc}\n")
                    return 2
                log.warning("erro_temporario: %s", exc)
                self._dormir(self._espera)
                self._espera = min(ESPERA_MAXIMA, self._espera * 2)
            except KeyboardInterrupt:
                self.solicitar_parada()
            except Exception:  # noqa: BLE001 — o laço não pode morrer por bug isolado
                log.exception("falha_inesperada_no_ciclo")
                self._dormir(self._espera)
                self._espera = min(ESPERA_MAXIMA, self._espera * 2)

        self.cliente.encerrar_sessao()
        log.info("agente_encerrado")
        return 0

    def _certificados_do_ciclo(self):
        agora = time.time()
        certificados = self.coletar_certificados()
        # Inventário completo no máximo a cada 10 minutos: a leitura do
        # repositório do Windows é barata, mas não é de graça.
        if agora - self._ultimo_inventario > 600:
            self.enviar_inventario(certificados)
            self._ultimo_inventario = agora
        return certificados

    def _avisar_assinador(self, resposta: dict) -> None:
        detalhe = resposta.get("assinador_detalhe") or "Assinador SERPRO indisponível."
        log.warning("assinador_nao_apto: %s", detalhe)
        print(f"\n  ⚠ {detalhe}")
        print("    Nenhum job será iniciado enquanto o Assinador não estiver pronto.")
        print(f"    Teste oficial: {diag_assinador.URL_VERIFICACAO_OFICIAL}")
        print(f"    Manual: {diag_assinador.URL_MANUAL_OFICIAL}\n")

    def _dormir(self, segundos: int) -> None:
        fim = time.time() + max(1, int(segundos))
        while time.time() < fim and not self._parar:
            time.sleep(min(1.0, fim - time.time()))
