"""
Testes do diagnóstico da estação.

O que importa verificar aqui não é "a função roda", e sim que ela **classifica
certo**: um relógio adiantado tem que virar FALHA, um certificado vencendo tem
que virar AVISO (não FALHA — ainda dá para operar hoje), e nenhuma verificação
pode derrubar o diagnóstico inteiro ao estourar.

As dependências externas (rede, DNS, PowerShell) entram por parâmetro, então
nenhum teste toca a rede nem depende de estar no Windows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from cajuru_agent import assinador as diag_assinador
from cajuru_agent import certificados as inventario
from cajuru_agent import diagnostico as diag


AGORA = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)


def _certificado(*, dias_para_vencer: int, documento="12345678000199", chave=True):
    fim = AGORA + timedelta(days=dias_para_vencer)
    return inventario.CertificadoLocal(
        thumbprint=f"TP{dias_para_vencer}{documento[-4:]}",
        documento=documento,
        titular_nome="EMPRESA TESTE LTDA",
        valido_de=(AGORA - timedelta(days=365)).isoformat(),
        valido_ate=fim.isoformat(),
        tem_chave_privada=chave,
    )


def _resposta_com_data(momento: datetime) -> httpx.Client:
    """Cliente falso que devolve `Date` controlado."""

    def responder(requisicao: httpx.Request) -> httpx.Response:
        cabecalho = momento.strftime("%a, %d %b %Y %H:%M:%S GMT")
        return httpx.Response(200, headers={"Date": cabecalho})

    return httpx.Client(transport=httpx.MockTransport(responder))


# ---------------------------------------------------------------------------
# Relógio — a verificação que justifica o módulo
# ---------------------------------------------------------------------------


def test_relogio_sincronizado_passa():
    with _resposta_com_data(AGORA) as cliente:
        resultado = diag.verificar_relogio(cliente=cliente, agora=lambda: AGORA)
    assert resultado.nivel is diag.Nivel.PASS


def test_relogio_pouco_adiantado_vira_aviso():
    """90s: ainda dentro da janela de 5 min do HMAC, mas caminhando para fora."""
    local = AGORA + timedelta(seconds=90)
    with _resposta_com_data(AGORA) as cliente:
        resultado = diag.verificar_relogio(cliente=cliente, agora=lambda: local)
    assert resultado.nivel is diag.Nivel.AVISO
    assert resultado.dados["desvio_segundos"] == pytest.approx(90, abs=1)


def test_relogio_muito_fora_vira_falha():
    """Acima de 4 min o servidor começa a recusar: é falha, não aviso."""
    local = AGORA - timedelta(minutes=6)
    with _resposta_com_data(AGORA) as cliente:
        resultado = diag.verificar_relogio(cliente=cliente, agora=lambda: local)
    assert resultado.nivel is diag.Nivel.FALHA
    assert "Sincronize" in resultado.acao


def test_relogio_sem_rede_nao_quebra():
    def recusar(requisicao: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rota", request=requisicao)

    with httpx.Client(transport=httpx.MockTransport(recusar)) as cliente:
        resultado = diag.verificar_relogio(cliente=cliente, agora=lambda: AGORA)
    assert resultado.nivel is diag.Nivel.AVISO


# ---------------------------------------------------------------------------
# DNS e portal
# ---------------------------------------------------------------------------


def test_dns_resolvendo_passa():
    resultado = diag.verificar_dns(hosts=("a.gov.br",), resolver=lambda h: "10.0.0.1")
    assert resultado.nivel is diag.Nivel.PASS


def test_dns_quebrado_e_falha():
    def recusar(host: str) -> str:
        raise OSError("sem resolução")

    resultado = diag.verificar_dns(hosts=("a.gov.br", "b.gov.br"), resolver=recusar)
    assert resultado.nivel is diag.Nivel.FALHA
    assert resultado.dados["falhos"] == ["a.gov.br", "b.gov.br"]


def test_portal_totalmente_fora_e_falha():
    def recusar(requisicao: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rota", request=requisicao)

    with httpx.Client(transport=httpx.MockTransport(recusar)) as cliente:
        resultado = diag.verificar_portal(cliente=cliente, hosts=("a.gov.br",))
    assert resultado.nivel is diag.Nivel.FALHA


def test_portal_parcialmente_fora_e_aviso():
    def responder(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.host == "a.gov.br":
            return httpx.Response(200)
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(responder)) as cliente:
        resultado = diag.verificar_portal(
            cliente=cliente, hosts=("a.gov.br", "b.gov.br")
        )
    assert resultado.nivel is diag.Nivel.AVISO


# ---------------------------------------------------------------------------
# Navegador
# ---------------------------------------------------------------------------


def test_navegador_ausente_e_falha():
    resultado = diag.verificar_navegador(detector=lambda: ("", ""))
    assert resultado.nivel is diag.Nivel.FALHA


def test_navegador_encontrado_passa():
    resultado = diag.verificar_navegador(detector=lambda: ("Edge", "141.0.3200.1"))
    assert resultado.nivel is diag.Nivel.PASS
    assert resultado.dados["versao"] == "141.0.3200.1"


# ---------------------------------------------------------------------------
# Certificados
# ---------------------------------------------------------------------------


def test_sem_certificado_vigente_e_falha():
    resultados = diag.verificar_certificados(
        [_certificado(dias_para_vencer=-5)], agora=AGORA
    )
    assert resultados[0].nivel is diag.Nivel.FALHA


def test_certificado_vencendo_e_aviso_e_nao_falha():
    """Vence em 10 dias: ainda opera hoje. Bloquear agora seria errado."""
    resultados = diag.verificar_certificados(
        [_certificado(dias_para_vencer=10)], agora=AGORA
    )
    resumo, alerta = resultados
    assert resumo.nivel is diag.Nivel.PASS
    assert alerta.nivel is diag.Nivel.AVISO
    assert alerta.dados["quantidade"] == 1


def test_certificado_folgado_nao_gera_alerta():
    resultados = diag.verificar_certificados(
        [_certificado(dias_para_vencer=400)], agora=AGORA
    )
    assert all(v.nivel is diag.Nivel.PASS for v in resultados)


def test_documento_do_certificado_sai_mascarado():
    """O diagnóstico é colado em chamado; CNPJ de cliente não passeia."""
    resultados = diag.verificar_certificados(
        [_certificado(dias_para_vencer=5, documento="12345678000199")], agora=AGORA
    )
    item = resultados[1].dados["itens"][0]
    assert item["documento"] == "12.***.***/0001-99"
    assert "12345678000199" not in str(resultados[1].dados)


def test_certificado_sem_chave_privada_nao_conta_como_utilizavel():
    resultados = diag.verificar_certificados(
        [_certificado(dias_para_vencer=300, chave=False)], agora=AGORA
    )
    assert resultados[0].nivel is diag.Nivel.FALHA


# ---------------------------------------------------------------------------
# Assinador
# ---------------------------------------------------------------------------


def _diag_assinador(**kwargs) -> diag_assinador.Diagnostico:
    base = {
        "instalado": True,
        "em_execucao": True,
        "hosts_mapeado": True,
        "porta_local": True,
        "certificado_visivel": True,
        "versao": "4.2.0",
    }
    base.update(kwargs)
    return diag_assinador.Diagnostico(**base)


def test_assinador_pronto_passa():
    resultado = diag.verificar_assinador(
        tem_certificado=True, diagnosticar=lambda **_: _diag_assinador()
    )
    assert resultado.nivel is diag.Nivel.PASS


def test_assinador_parado_e_falha():
    resultado = diag.verificar_assinador(
        tem_certificado=True,
        diagnosticar=lambda **_: _diag_assinador(porta_local=False, em_execucao=False),
    )
    assert resultado.nivel is diag.Nivel.FALHA
    assert "não está em execução" in resultado.detalhe


def test_assinador_desatualizado_e_aviso():
    resultado = diag.verificar_assinador(
        tem_certificado=True,
        versao_minima="4.0.0",
        diagnosticar=lambda **_: _diag_assinador(versao="3.9.1"),
    )
    assert resultado.nivel is diag.Nivel.AVISO


@pytest.mark.parametrize(
    "atual,minima,esperado",
    [
        ("4.0.0", "4.0.0", False),
        ("3.9.9", "4.0.0", True),
        ("4.1", "4.0.0", False),
        ("4.0.0.1", "4.0.0", False),
        ("10.0.0", "9.9.9", False),
        ("", "4.0.0", False),
    ],
)
def test_comparacao_de_versao(atual, minima, esperado):
    """10.0.0 > 9.9.9: comparação numérica, não lexicográfica."""
    assert diag._versao_menor(atual, minima) is esperado


# ---------------------------------------------------------------------------
# Relatório e resiliência
# ---------------------------------------------------------------------------


def test_relatorio_apto_quando_so_ha_aviso():
    relatorio = diag.Relatorio(
        verificacoes=[
            diag.Verificacao("a", "A", diag.Nivel.PASS),
            diag.Verificacao("b", "B", diag.Nivel.AVISO),
        ]
    )
    assert relatorio.apto is True
    assert relatorio.pior_nivel is diag.Nivel.AVISO


def test_relatorio_nao_apto_com_falha():
    relatorio = diag.Relatorio(
        verificacoes=[
            diag.Verificacao("a", "A", diag.Nivel.PASS),
            diag.Verificacao("b", "B", diag.Nivel.FALHA),
        ]
    )
    assert relatorio.apto is False
    assert len(relatorio.falhas()) == 1


def test_verificacao_que_estoura_vira_aviso_e_nao_derruba():
    def explodir() -> diag.Verificacao:
        raise RuntimeError("boom")

    resultado = diag._protegido(explodir)
    assert resultado.nivel is diag.Nivel.AVISO


def test_execucao_sem_rede_marca_pulado_e_nao_finge_sucesso():
    """Não verificado nunca pode virar PASS — é o ponto do nível PULADO."""
    relatorio = diag.executar(verificar_rede=False)
    por_chave = {v.chave: v for v in relatorio.verificacoes}
    for chave in ("relogio", "dns", "portal"):
        assert por_chave[chave].nivel is diag.Nivel.PULADO


def test_json_do_relatorio_e_serializavel():
    import json

    relatorio = diag.executar(verificar_rede=False)
    texto = json.dumps(relatorio.para_json(), ensure_ascii=False)
    assert "verificacoes" in texto
