"""
Linha de comando do Cajuru Agent.

    cajuru-agent configurar --servidor ... --identificador ... --segredo ...
    cajuru-agent diagnostico     # Assinador SERPRO local
    cajuru-agent diagnose        # pré-flight completo da estação
    cajuru-agent certificados    # o que esta máquina enxerga
    cajuru-agent politica-certificado --documento ...  # AutoSelectCertificateForUrls
    cajuru-agent importar-certificados --pasta ... --planilha ... --executar
    cajuru-agent testar          # autentica e bate um heartbeat
    cajuru-agent executar        # laço principal
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import platform
import socket
import subprocess
import sys
from pathlib import Path

import httpx

from . import assinador as diag
from . import certificados as inventario
from . import importador
from . import politicas_navegador
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


def _versao_pacote(nome: str) -> str:
    try:
        return importlib.metadata.version(nome)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _dns_ok(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def _https_ok(url: str) -> bool:
    try:
        with httpx.Client(timeout=5.0, follow_redirects=False) as cliente:
            resposta = cliente.get(url)
        return resposta.status_code < 500
    except httpx.HTTPError:
        return False


def cmd_diagnose(args) -> int:
    """Pré-flight completo da estação Windows antes de iniciar lote."""
    pasta = Path(args.pasta_pfx) if args.pasta_pfx else None
    certificados = inventario.inventariar(pasta)
    vigentes = [c for c in certificados if inventario.vigente(c) and c.tem_chave_privada]
    assinador = diag.diagnosticar(tem_certificado=bool(vigentes))
    politicas = politicas_navegador.diagnosticar_politicas()
    playwright = _versao_pacote("playwright")

    checks = [
        ("Windows", platform.system() == "Windows", platform.platform()),
        ("Python", sys.version_info >= (3, 11), platform.python_version()),
        ("Playwright", bool(playwright), playwright or "não instalado"),
        ("Certificados A1 vigentes", bool(vigentes), f"{len(vigentes)} de {len(certificados)} visível(is)"),
        ("Windows Certificate Store", platform.system() == "Windows", "CurrentUser\\My / LocalMachine\\My"),
        ("DNS Portal RFB", _dns_ok("servicos.receitafederal.gov.br"), "servicos.receitafederal.gov.br"),
        ("Portal RFB HTTPS", _https_ok("https://servicos.receitafederal.gov.br"), "GET com timeout de 5s"),
        ("Assinador SERPRO instalado", assinador.instalado, assinador.versao or "versão não detectada"),
        ("Assinador SERPRO em execução", assinador.em_execucao, f"porta {diag.PORTA_LOCAL}"),
        ("Hosts do Assinador", assinador.hosts_mapeado, diag.HOST_MAPEADO),
        ("Permissão/loopback navegador", assinador.permissao_navegador, "porta local + hosts"),
    ]

    if args.json:
        print(
            json.dumps(
                {
                    "checks": [
                        {"nome": nome, "ok": ok, "detalhe": detalhe}
                        for nome, ok, detalhe in checks
                    ],
                    "assinador": assinador.para_envio(),
                    "politicas_navegador": politicas.navegadores,
                    "observacoes": list(assinador.observacoes) + list(politicas.observacoes),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        bloqueantes_json = [nome for nome, ok, _detalhe in checks if not ok and nome not in {"Portal RFB HTTPS"}]
        return 0 if not bloqueantes_json else 1

    print("\nDiagnóstico completo da estação")
    print("─" * 60)
    for nome, ok, detalhe in checks:
        print(f"  {'OK   ' if ok else 'FALTA'} {nome:<30} {detalhe}")
    print("\nPolíticas AutoSelectCertificateForUrls (HKCU):")
    for navegador, valores in politicas.navegadores.items():
        print(f"  • {navegador}: {len(valores)} regra(s)")
    observacoes = list(assinador.observacoes) + list(politicas.observacoes)
    if not playwright:
        observacoes.append("Instale Playwright na estação: pip install -r agent/requirements.txt && python -m playwright install chromium")
    if observacoes:
        print("\nO que fazer:")
        for item in observacoes:
            print(f"  • {item}")
    print()
    bloqueantes = [nome for nome, ok, _detalhe in checks if not ok and nome not in {"Portal RFB HTTPS"}]
    return 0 if not bloqueantes else 1


def cmd_politica_certificado(args) -> int:
    """Gera/aplica AutoSelectCertificateForUrls para o certificado exato."""
    navegadores = tuple(args.navegador or ["edge", "chrome"])
    padroes = tuple(args.portal or politicas_navegador.PADROES_RFB_PADRAO)
    try:
        certificado, politicas = politicas_navegador.gerar_para_documento(
            args.documento,
            navegadores=navegadores,
            padroes=padroes,
            thumbprint=args.thumbprint or "",
            pasta_pfx=Path(args.pasta_pfx) if args.pasta_pfx else None,
        )
    except politicas_navegador.PoliticaNavegadorError as exc:
        print(f"\n  ✖ {exc}\n")
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "certificado": certificado.para_envio(),
                    "politicas": [
                        {
                            "navegador": p.navegador,
                            "registro_hkcu": p.caminho_registro_hkcu,
                            "regras": [r.para_json() for r in p.regras],
                        }
                        for p in politicas
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("\nCertificado selecionado de forma determinística")
        print("─" * 60)
        print(f"  titular   : {certificado.titular_nome or '(sem nome)'}")
        print(f"  documento : {certificado.documento}")
        print(f"  thumbprint: {certificado.thumbprint}")
        print(f"  issuer    : {certificado.issuer[:120]}")
        print("\nScript PowerShell idempotente (HKCU, não remove regras existentes):\n")
        print(politicas_navegador.script_powershell(politicas))

    if args.executar:
        try:
            resultados = [politicas_navegador.aplicar_politica(p) for p in politicas]
        except (politicas_navegador.PoliticaNavegadorError, subprocess.SubprocessError) as exc:
            print(f"\n  ✖ Não foi possível aplicar a política: {exc}\n")
            return 2
        for resultado in resultados:
            print(
                f"{resultado.navegador}: {resultado.adicionadas} nova(s), "
                f"{resultado.existentes} já existente(s)."
            )
            for mensagem in resultado.mensagens:
                print(f"  • {mensagem}")
    elif not args.json:
        print("Para aplicar nesta conta Windows, rode de novo com --executar após revisar o script.")
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

    p = sub.add_parser("diagnostico", help="verifica o Assinador SERPRO nesta máquina")
    p.add_argument("--pasta-pfx", dest="pasta_pfx", default="")
    p.set_defaults(func=cmd_diagnostico)

    p = sub.add_parser("diagnose", help="pré-flight completo: Windows, navegador, certificados, rede e Assinador")
    p.add_argument("--pasta-pfx", dest="pasta_pfx", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("certificados", help="lista os certificados visíveis")
    p.add_argument("--pasta-pfx", dest="pasta_pfx", default="")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_certificados)

    p = sub.add_parser(
        "politica-certificado",
        help="gera/aplica AutoSelectCertificateForUrls para selecionar o A1 correto no Chrome/Edge",
    )
    p.add_argument("--documento", required=True, help="CPF/CNPJ do titular do certificado")
    p.add_argument("--thumbprint", default="", help="fixa o certificado quando houver mais de um candidato")
    p.add_argument("--navegador", action="append", choices=["edge", "chrome", "chromium"], help="repita para gerar para mais navegadores; padrão edge+chrome")
    p.add_argument("--portal", action="append", help="URL pattern autorizado; padrão inclui Portal RFB, e-CAC, gov.br e assinatura.gov.br")
    p.add_argument("--pasta-pfx", dest="pasta_pfx", default="")
    p.add_argument("--executar", action="store_true", help="aplica no HKCU desta conta Windows depois da revisão")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_politica_certificado)

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
