"""
Linha de comando do Cajuru Agent.

    cajuru-agent configurar --servidor ... --identificador ... --segredo ...
    cajuru-agent diagnostico     # ambiente local, sem falar com o servidor
    cajuru-agent certificados    # o que esta máquina enxerga
    cajuru-agent testar          # autentica e bate um heartbeat
    cajuru-agent executar        # laço principal
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import assinador as diag
from . import certificados as inventario
from .config import Configuracao, CofreError, guardar_segredo, ler_segredo, pasta_base
from .executor import VERSAO_AGENTE, Agente
from .protocolo import ClienteCajuru, ProtocoloError


def configurar_log(verboso: bool) -> None:
    destino = pasta_base() / "agent.log"
    destino.parent.mkdir(parents=True, exist_ok=True)
    formato = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format=formato,
        handlers=[logging.FileHandler(destino, encoding="utf-8"), logging.StreamHandler(sys.stderr)],
    )
    # Nenhum segredo chega ao log: o protocolo só registra o identificador
    # público da estação, e o httpx não loga corpo por padrão.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _cliente(config: Configuracao) -> ClienteCajuru:
    if not config.servidor_url or not config.identificador:
        raise SystemExit(
            "Estação não configurada. Rode 'cajuru-agent configurar' ou instalar_agent.ps1."
        )
    segredo = ler_segredo(config.identificador)
    return ClienteCajuru(
        config.servidor_url,
        config.identificador,
        segredo,
        verificar_tls=config.verificar_tls,
    )


def cmd_configurar(args) -> int:
    config = Configuracao.carregar()
    config.servidor_url = args.servidor or config.servidor_url
    config.identificador = args.identificador or config.identificador
    config.nome_estacao = args.nome or config.nome_estacao
    config.pasta_pfx = args.pasta_pfx or config.pasta_pfx
    if args.capacidade:
        config.capacidade = max(1, min(5, int(args.capacidade)))
    config.salvar()

    if args.segredo:
        cofre = guardar_segredo(config.identificador, args.segredo)
        print(f"Credencial guardada em: {cofre}")
    print(f"Configuração salva em: {config.arquivo}")
    return 0


def cmd_diagnostico(args) -> int:
    certificados = inventario.inventariar(
        Path(args.pasta_pfx) if args.pasta_pfx else None
    )
    tem = any(inventario.vigente(c) and c.tem_chave_privada for c in certificados)
    resultado = diag.diagnosticar(tem_certificado=tem)

    print("\nDiagnóstico do Assinador Digital SERPRO")
    print("─" * 50)
    for rotulo, valor in [
        ("Instalado", resultado.instalado),
        ("Em execução", resultado.em_execucao),
        (f"Host {diag.HOST_MAPEADO} mapeado", resultado.hosts_mapeado),
        (f"Porta {diag.PORTA_LOCAL} respondendo", resultado.porta_local),
        ("Certificado vigente na estação", resultado.certificado_visivel),
    ]:
        print(f"  {'OK  ' if valor else 'FALTA'}  {rotulo}")
    print(f"  Versão detectada: {resultado.versao or '(não identificada)'}")
    if resultado.observacoes:
        print("\nO que fazer:")
        for observacao in resultado.observacoes:
            print(f"  • {observacao}")
    print(f"\nTeste oficial do SERPRO: {diag.URL_VERIFICACAO_OFICIAL}")
    print(f"Manual oficial: {diag.URL_MANUAL_OFICIAL}\n")
    return 0 if resultado.porta_local else 1


def cmd_certificados(args) -> int:
    encontrados = inventario.inventariar(
        Path(args.pasta_pfx) if args.pasta_pfx else None
    )
    if args.json:
        print(json.dumps([c.para_envio() for c in encontrados], indent=2, ensure_ascii=False))
        return 0
    if not encontrados:
        print("Nenhum certificado encontrado nesta estação.")
        return 1
    print(f"\n{len(encontrados)} certificado(s) visível(is):\n")
    for item in encontrados:
        situacao = "vigente" if inventario.vigente(item) else "VENCIDO/INDISPONÍVEL"
        print(f"  • {item.titular_nome or '(sem nome)'}  [{situacao}]")
        print(f"    documento : {item.documento or '(não identificado)'}")
        print(f"    thumbprint: {item.thumbprint}")
        print(f"    validade  : {item.valido_ate or '(desconhecida)'}")
        if item.erro:
            print(f"    atenção   : {item.erro}")
        print()
    return 0


def cmd_testar(args) -> int:
    config = Configuracao.carregar()
    cliente = _cliente(config)
    agente = Agente(config, cliente)
    certificados = agente.coletar_certificados()
    try:
        agente.enviar_inventario(certificados)
        resposta = agente.bater_heartbeat(certificados)
    except ProtocoloError as exc:
        print(f"\n  ✖ {exc}\n")
        return 2
    print("\n  Conexão com o Cajuru28: OK")
    print(f"  Estação: {config.identificador}")
    print(f"  Assinador apto: {'sim' if resposta.get('assinador_apto') else 'não'}")
    if resposta.get("assinador_detalhe"):
        print(f"  Detalhe: {resposta['assinador_detalhe']}")
    print(f"  Jobs aguardando esta estação: {resposta.get('jobs_disponiveis', 0)}\n")
    return 0


def cmd_executar(args) -> int:
    config = Configuracao.carregar()
    cliente = _cliente(config)
    agente = Agente(config, cliente)
    print(f"\n  Cajuru Agent {VERSAO_AGENTE} — estação {config.identificador}")
    print(f"  Servidor: {config.servidor_url}")
    print("  Ctrl+C encerra com segurança (o job volta para a fila).\n")
    return agente.rodar(ciclos=args.ciclos)


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cajuru-agent", description="Estação do módulo Procurações RFB do Cajuru28."
    )
    parser.add_argument("-v", "--verboso", action="store_true")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("configurar", help="grava endereço e credencial da estação")
    p.add_argument("--servidor", default="")
    p.add_argument("--identificador", default="")
    p.add_argument("--segredo", default="")
    p.add_argument("--nome", default="")
    p.add_argument("--pasta-pfx", dest="pasta_pfx", default="")
    p.add_argument("--capacidade", type=int, default=0)
    p.set_defaults(func=cmd_configurar)

    p = sub.add_parser("diagnostico", help="verifica o Assinador SERPRO nesta máquina")
    p.add_argument("--pasta-pfx", dest="pasta_pfx", default="")
    p.set_defaults(func=cmd_diagnostico)

    p = sub.add_parser("certificados", help="lista os certificados visíveis")
    p.add_argument("--pasta-pfx", dest="pasta_pfx", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_certificados)

    p = sub.add_parser("testar", help="autentica no Cajuru28 e envia um heartbeat")
    p.set_defaults(func=cmd_testar)

    p = sub.add_parser("executar", help="laço principal")
    p.add_argument("--ciclos", type=int, default=None)
    p.set_defaults(func=cmd_executar)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    configurar_log(args.verboso)
    try:
        return int(args.func(args) or 0)
    except CofreError as exc:
        print(f"\n  ✖ {exc}\n")
        return 3
    except KeyboardInterrupt:
        print("\n  Encerrado pelo operador.\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
