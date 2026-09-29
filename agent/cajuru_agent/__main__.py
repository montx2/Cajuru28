"""
Linha de comando do Cajuru Agent.

    cajuru-agent configurar --servidor ... --identificador ... --segredo ...
    cajuru-agent diagnostico     # estação inteira (PASS/AVISO/FALHA), sem falar com o servidor
    cajuru-agent certificados    # o que esta máquina enxerga
    cajuru-agent importar-certificados --pasta ... --planilha ... --executar
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
from . import diagnostico as diagnose
from . import importador
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
    """Diagnóstico completo da estação.

    Código de saída: 0 = apta (sem FALHA), 1 = não apta. Isso permite usar o
    comando como portão em script de instalação e em tarefa agendada.
    """
    relatorio = diagnose.executar(
        pasta_pfx=Path(args.pasta_pfx) if args.pasta_pfx else None,
        verificar_rede=not args.sem_rede,
    )

    if args.json:
        print(json.dumps(relatorio.para_json(), ensure_ascii=False, indent=2))
    else:
        print(diagnose.formatar(relatorio))
        print(f"Teste oficial do SERPRO: {diag.URL_VERIFICACAO_OFICIAL}")
        print(f"Manual oficial: {diag.URL_MANUAL_OFICIAL}\n")

    return 0 if relatorio.apto else 1


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


def _mostrar_importacao(itens, *, json_saida: bool) -> None:
    """Mostra prévia/resultado da importação sem nunca serializar senha."""
    if json_saida:
        saida = [item.para_saida() for item in itens if isinstance(item, importador.ResultadoItem)]
        if not saida:
            saida = [
                {
                    "arquivo": item.arquivo.name,
                    "status": item.status,
                    "mensagem": item.mensagem,
                    "cliente": item.cliente,
                    "documento": item.documento,
                    "validade_declarada": item.validade_declarada.isoformat() if item.validade_declarada else None,
                }
                for item in itens
            ]
        print(json.dumps(saida, ensure_ascii=False, indent=2))
        return

    for item in itens:
        validade = getattr(item, "validade_certificado", None) or item.validade_declarada
        sufixo_validade = f" · validade {validade.isoformat()}" if validade else ""
        cliente = f" · {item.cliente}" if item.cliente else ""
        documento = f" · {item.documento}" if item.documento else ""
        print(f"  [{item.status.upper()}] {item.arquivo.name}{cliente}{documento}{sufixo_validade}")
        print(f"    {item.mensagem}")


def cmd_importar_certificados(args) -> int:
    """Prévia segura e, sob confirmação explícita, instalação local de A1.

    O comando não precisa de conexão com o Cajuru28 para importar. A opção
    ``--sincronizar`` é separada para deixar claro o único momento em que dados
    públicos do certificado (nunca PFX/senha) serão enviados ao servidor.
    """
    try:
        plano = importador.montar_plano(Path(args.pasta), [Path(item) for item in args.planilha])
    except importador.ImportacaoLocalError as exc:
        print(f"\n  ✖ {exc}\n")
        return 2

    if not args.executar:
        if not args.json:
            print("\nPrévia da importação local — nenhum certificado, senha ou dado foi enviado ou instalado.\n")
        _mostrar_importacao(plano, json_saida=args.json)
        totais = importador.resumo(plano)
        prontos = totais.get("pronto", 0)
        if not args.json:
            print(f"\nResumo: {len(plano)} arquivo(s) · {prontos} pronto(s) · {len(plano) - prontos} pendência(s).")
            print("Revise a prévia. Para instalar somente os itens PRONTO no repositório desta conta Windows, rode de novo com --executar.\n")
        return 0 if prontos else 1

    try:
        resultados = importador.executar_plano(plano)
    except importador.ImportacaoLocalError as exc:
        print(f"\n  ✖ {exc}\n")
        return 2

    if not args.json:
        print("\nResultado da importação local — senhas e arquivos privados permaneceram nesta estação.\n")
    _mostrar_importacao(resultados, json_saida=args.json)
    totais = importador.resumo(resultados)
    concluidos = totais.get("importado", 0) + totais.get("ja_instalado", 0)
    if not args.json:
        print(f"\nResumo: {concluidos} disponível(is) · {totais.get('erro', 0)} com erro · {totais.get('ignorado', 0)} pendência(s).")

    if args.sincronizar and concluidos:
        try:
            config = Configuracao.carregar()
            agente = Agente(config, _cliente(config))
            resposta = agente.enviar_inventario(agente.coletar_certificados())
        except (CofreError, ProtocoloError) as exc:
            print(f"\n  ⚠ Certificados importados, mas o inventário não foi sincronizado: {exc}\n")
            return 1
        destino = sys.stderr if args.json else sys.stdout
        print(
            "Inventário público sincronizado com o Cajuru28: "
            f"{resposta.get('novos', 0)} novo(s), {resposta.get('atualizados', 0)} atualizado(s).",
            file=destino,
        )
    return 0 if not totais.get("erro") else 1


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

    p = sub.add_parser(
        "diagnostico",
        help="verifica a estação inteira: SO, relógio, DNS, portal, navegador, "
        "certificados e Assinador",
    )
    p.add_argument("--pasta-pfx", dest="pasta_pfx", default="")
    p.add_argument("--json", action="store_true", help="saída estruturada")
    p.add_argument(
        "--sem-rede",
        dest="sem_rede",
        action="store_true",
        help="pula relógio/DNS/portal (máquina sem saída para a internet)",
    )
    p.set_defaults(func=cmd_diagnostico)

    p = sub.add_parser("certificados", help="lista os certificados visíveis")
    p.add_argument("--pasta-pfx", dest="pasta_pfx", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_certificados)

    p = sub.add_parser(
        "importar-certificados",
        help="associa PFX às planilhas e instala A1 localmente, sem enviar senha/PFX",
    )
    p.add_argument("--pasta", required=True, help="pasta com arquivos .pfx/.p12 (subpastas são incluídas)")
    p.add_argument(
        "--planilha",
        action="append",
        required=True,
        help="planilha local CSV/TXT/XLSX/XLSM com cliente/CNPJ e senha; repita para usar duas planilhas",
    )
    p.add_argument(
        "--executar",
        action="store_true",
        help="confirma a instalação local dos itens aprovados na prévia",
    )
    p.add_argument(
        "--sincronizar",
        action="store_true",
        help="após instalar, envia apenas o inventário público ao Cajuru28",
    )
    p.add_argument("--json", action="store_true", help="emite itens sem senha em JSON")
    p.set_defaults(func=cmd_importar_certificados)

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
