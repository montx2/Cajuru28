"""
Diagnóstico da conexão Jettax/Morfeu executado direto no servidor.

O painel já sonda endereço + formato de header ao salvar/testar a credencial.
Este script existe para o caso em que o HTTP 401 persiste e é preciso responder,
com evidência, a pergunta que a mensagem genérica da Jettax não responde:

    o valor configurado é um token que o servidor Morfeu reconhece?

Ele reproduz as sondagens do conector e acrescenta duas referências que o
painel não tem:

1. a resposta do endpoint de leitura **sem** nenhuma autenticação — a mensagem
   desse pedido é a mesma que o servidor devolve para um ``Bearer``
   desconhecido, e serve de linha de base;
2. a resposta com um valor **obviamente inválido** — se a mensagem for igual à
   que o seu token real recebe, o servidor está dizendo, na prática, "não
   conheço este valor".

Uso (o contêiner da API é quem tem saída de internet):

    docker compose exec api python scripts/diagnosticar_jettax.py

    # testar um token específico sem tocar no cofre:
    docker compose exec api python scripts/diagnosticar_jettax.py --token "COLE_AQUI"

    # sonda opcional do POST /api/login (rota existente, não documentada na
    # coleção pública). Uma única tentativa por execução; use com parcimônia,
    # porque tentativas repetidas podem contar como login errado na conta:
    docker compose exec api python scripts/diagnosticar_jettax.py \
        --email voce@escritorio.com.br --senha 'SuaSenha' [--formato email_senha]

O script é somente leitura: nada é gravado no banco. O token nunca é impresso
— apenas um resumo curto (sha256) e o comprimento, o bastante para conferir
qual valor está guardado sem expor o segredo no terminal. Toda sondagem usa
apenas os dois hosts HTTPS oficiais da Jettax e um endpoint GET de leitura.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Dentro do contêiner o código vive em /app; rodando fora dele, o pacote
# `app` está na pasta acima de scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, "/app")

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services.jettax import (  # noqa: E402
    HOSTS_OFICIAIS_JETTAX,
    normalizar_token,
)

ROTA_LEITURA = "/api/nfse/cities"
ROTA_LOGIN = "/api/login"
_TIMEOUT = max(5.0, float(getattr(settings, "jettax_timeout_segundos", 30.0)))
# Enviado uma única vez por host apenas para descobrir qual mensagem o servidor
# devolve para um valor que certamente não existe.
_TOKEN_DESCONHECIDO = "notasflow-diagnostico-valor-invalido"

# Formatos plausíveis do corpo do POST /api/login. A coleção pública não
# documenta a rota; o formato padrão é o mais comum em APIs Laravel.
_FORMATOS_LOGIN: dict[str, tuple[str, str]] = {
    "email_senha": ("email", "password"),
    "usuario_senha": ("usuario", "senha"),
    "login_senha": ("login", "senha"),
    "cnpj_senha": ("cnpj", "senha"),
}

_CAMPOS_TOKEN_RESPOSTA = ("token", "access_token", "api_token", "apiToken", "apiKey")


def _linha() -> None:
    print("-" * 72)


def _resumo_token(token: str) -> str:
    """Identifica o valor guardado sem imprimi-lo."""
    digesto = hashlib.sha256(token.encode()).hexdigest()[:12]
    return f"{len(token)} caracteres · sha256 {digesto}"


def _redigir(texto: str, limite: int = 200) -> str:
    """Redige sequências longas (formato típico de token/segredo) na saída."""
    palavras: list[str] = []
    for palavra in texto.split():
        limpa = palavra.strip(".,;:\"'{}[]()")
        palavras.append("[redigido]" if len(limpa) > 24 else palavra)
    return " ".join(palavras)[:limite]


def _mensagem_corpo(resposta: httpx.Response) -> str:
    try:
        corpo = resposta.json()
    except ValueError:
        return _redigir(resposta.text)
    if isinstance(corpo, dict):
        bruto = corpo.get("message") or corpo.get("error") or corpo.get("detail")
        if bruto:
            return _redigir(" ".join(str(bruto).split()))
        return _redigir(json.dumps(corpo, ensure_ascii=False)[:200])
    return _redigir(str(corpo)[:200])


def _pedido(metodo: str, url: str, *, authorization: str | None = None, corpo: dict | None = None) -> httpx.Response | Exception:
    cabecalhos = {"Accept": "application/json"}
    if authorization is not None:
        cabecalhos["Authorization"] = authorization
    if corpo is not None:
        cabecalhos["Content-Type"] = "application/json"
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as cliente:
            return cliente.request(metodo, url, headers=cabecalhos, json=corpo)
    except httpx.HTTPError as exc:  # rede/DNS/certificado
        return exc


def _descrever(resposta: httpx.Response | Exception) -> str:
    if isinstance(resposta, Exception):
        return f"sem resposta ({resposta.__class__.__name__})"
    texto = _mensagem_corpo(resposta)
    return f"HTTP {resposta.status_code}" + (f' "{texto}"' if texto else "")


def _extrair_token_resposta(resposta: httpx.Response) -> str | None:
    """Procura um valor de token no corpo da resposta do login (sem imprimi-lo)."""
    try:
        corpo = resposta.json()
    except ValueError:
        return None
    candidatos: list[object] = [corpo]
    if isinstance(corpo, dict):
        candidatos.extend(corpo.values())
        dados = corpo.get("data")
        if isinstance(dados, dict):
            candidatos.extend(dados.values())
    for candidato in candidatos:
        if isinstance(candidato, str) and 16 <= len(candidato) <= 512 and " " not in candidato.strip():
            return candidato.strip()
    return None


def _token_do_cofre(escritorio_id: int | None) -> tuple[str, str] | None:
    """Lê o token cifrado do escritório. Devolve (token, base_url) ou None."""
    from app.core.vault import SegredoIndecifravelError, decifrar_segredo
    from app.db.session import SessionLocal
    from app.models import JettaxCredencial

    sessao = SessionLocal()
    try:
        consulta = sessao.query(JettaxCredencial)
        if escritorio_id:
            consulta = consulta.filter(JettaxCredencial.escritorio_id == escritorio_id)
        credencial = consulta.order_by(JettaxCredencial.id).first()
        if credencial is None:
            return None
        try:
            token = decifrar_segredo(credencial.token_cifrado)
        except SegredoIndecifravelError:
            print(
                "[FALHA] A credencial guardada não pôde ser aberta: VAULT_MASTER_KEY mudou "
                "desde o salvamento. Salve o token novamente no painel e repita o diagnóstico."
            )
            raise SystemExit(2)
        return token, credencial.base_url
    finally:
        sessao.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico da conexão Jettax/Morfeu (somente leitura).")
    parser.add_argument("--token", help="testa este valor em vez do cofre; não versione nem compartilhe o comando")
    parser.add_argument("--escritorio", type=int, help="id do escritório quando houver mais de uma credencial salva")
    parser.add_argument("--email", help="e-mail/login da conta Jettax para a sonda opcional do POST /api/login")
    parser.add_argument("--senha", help="senha da conta Jettax para a sonda opcional do POST /api/login")
    parser.add_argument(
        "--formato",
        choices=sorted(_FORMATOS_LOGIN),
        default="email_senha",
        help="formato do corpo do POST /api/login (padrão: email_senha)",
    )
    parser.add_argument("--revelar", action="store_true", help="exibe o valor de token retornado pelo login, se houver")
    args = parser.parse_args()

    print("=" * 72)
    print("  NotasFlow — diagnóstico Jettax / Morfeu")
    print("=" * 72)

    # 1. De onde vem o token.
    if args.token:
        token_bruto, base_url = args.token, settings.jettax_api_base_url
        print("[INFO] Token passado via --token (o cofre não foi lido).")
    else:
        try:
            do_cofre = _token_do_cofre(args.escritorio)
        except Exception as exc:  # noqa: BLE001 -- banco fora do ar não pode virar traceback cru
            print(f"[FALHA] Não consegui ler o banco do NotasFlow: {exc.__class__.__name__}")
            print("        Os contêineres estão saudáveis? Verifique com: docker compose ps")
            return 2
        if do_cofre is None:
            if (settings.jettax_api_token or "").strip():
                token_bruto, base_url = settings.jettax_api_token, settings.jettax_api_base_url
                print("[INFO] Nenhuma credencial no painel; usando JETTAX_API_TOKEN do ambiente.")
            else:
                print("[FALHA] Nenhuma credencial Jettax encontrada (painel ou ambiente).")
                print("        Salve o token em Configurações → Jettax / Morfeu e rode novamente.")
                return 2
        else:
            token_bruto, base_url = do_cofre
            print(f"[INFO] Token lido do cofre do painel (base_url salva: {base_url}).")

    token = normalizar_token(token_bruto)
    if not token:
        print("[FALHA] O valor salvo ficou vazio após a limpeza (prefixo/aspas/espaços).")
        return 2
    if token != token_bruto.strip():
        print("[INFO] O valor foi normalizado (prefixo 'Bearer', aspas ou espaços removidos).")
    print(f"[INFO] Valor em teste: {_resumo_token(token)} (o valor em si não é impresso).")
    if len(token) < 8:
        print("[FALHA] Token curto demais para uma credencial de API.")
        return 2
    _linha()

    # 2. Sondagens por host (somente hosts oficiais da Jettax).
    hosts: list[str] = []
    for url in [str(base_url or "").strip().rstrip("/"), *HOSTS_OFICIAIS_JETTAX]:
        if url.startswith("https://") and url not in hosts and ".jettax.com.br" in url:
            hosts.append(url)

    aceito = False
    mensagem_sem_auth: dict[str, str] = {}
    mensagem_desconhecido: dict[str, str] = {}
    mensagem_real: dict[str, str] = {}

    for host in hosts:
        print(f"Host {host}")
        respostas: dict[str, httpx.Response | Exception] = {
            "sem autenticação": _pedido("GET", f"{host}{ROTA_LEITURA}"),
            "valor obviamente inválido": _pedido("GET", f"{host}{ROTA_LEITURA}", authorization=_TOKEN_DESCONHECIDO),
            "token salvo (puro)": _pedido("GET", f"{host}{ROTA_LEITURA}", authorization=token),
            "token salvo (Bearer)": _pedido("GET", f"{host}{ROTA_LEITURA}", authorization=f"Bearer {token}"),
        }
        for rotulo, resposta in respostas.items():
            print(f"  {rotulo:<26} {_descrever(resposta)}")
            if isinstance(resposta, Exception):
                continue
            if rotulo == "sem autenticação":
                mensagem_sem_auth[host] = _mensagem_corpo(resposta)
            elif rotulo == "valor obviamente inválido":
                mensagem_desconhecido[host] = _mensagem_corpo(resposta)
            elif rotulo == "token salvo (puro)":
                mensagem_real[host] = _mensagem_corpo(resposta)
                if resposta.status_code < 300:
                    aceito = True
        print()

    # 3. Sonda opcional do POST /api/login (rota existente, não documentada).
    token_login: str | None = None
    if args.email and args.senha:
        campo_login, campo_senha = _FORMATOS_LOGIN[args.formato]
        corpo = {campo_login: args.email, campo_senha: args.senha}
        print(f"POST {ROTA_LOGIN} (formato {args.formato}) — uma única tentativa")
        for host in hosts:
            resposta = _pedido("POST", f"{host}{ROTA_LOGIN}", corpo=corpo)
            print(f"  {host:<34} {_descrever(resposta)}")
            if isinstance(resposta, httpx.Response) and resposta.status_code < 300:
                token_login = _extrair_token_resposta(resposta)
                if token_login:
                    print(f"  [ACHADO] O login devolveu um valor de token ({_resumo_token(token_login)}).")
                    if args.revelar:
                        print(f"  [REVELADO] {token_login}")
                        print("             Guarde com o mesmo cuidado do token anterior.")
                    else:
                        print("             Rode com --revelar para exibi-lo e cole no painel.")
                break
        _linha()
    elif args.email or args.senha:
        print("[AVISO] Sonda de login ignorada: informe --email e --senha juntos.")
        _linha()

    # 4. Conclusão.
    print("CONCLUSÃO")
    if aceito:
        print("[OK] O token foi aceito por pelo menos um host oficial com o header puro.")
        print("     Se o painel ainda acusa erro, salve a credencial novamente no painel")
        print("     (Configurações → Jettax / Morfeu) e use o botão Testar conexão.")
        return 0

    iguais = [
        host for host in mensagem_real
        if host in mensagem_desconhecido and mensagem_real[host] and mensagem_real[host] == mensagem_desconhecido[host]
    ]
    print("[401] A Jettax recusou o valor em todos os hosts oficiais, nos dois formatos de header.")
    if iguais:
        print("      O servidor devolveu ao seu token a MESMA resposta dada a um valor obviamente")
        print("      inválido — ou seja, ele não reconhece esse valor como credencial Morfeu.")
        print("      Isso descarta formato de header/URL: o problema é o valor em si.")
    else:
        print("      A resposta ao seu token difere da resposta a um valor desconhecido; o valor")
        print("      pode estar correto, mas inativo/revogado ou sem permissão contratada.")
    print("      Próximos passos, em ordem:")
    print("      1. Confirme o que foi colado: senha do Jettax 360, token de primeiro acesso,")
    print("         token da Acessórias/SIEG/NIBO e chaves Domínio/Onvio NÃO são tokens Morfeu.")
    print("      2. Peça à Jettax (suporte/comercial) um token emitido para a API Morfeu,")
    print("         ativo, e a confirmação de que a conta tem acesso à API contratado — não")
    print("         existe geração autoatendimento de token no painel Jettax 360.")
    if token_login:
        print("      3. O POST /api/login devolveu um token; teste-o como credencial Morfeu")
        print("         antes de acionar o suporte.")
    elif args.email and args.senha:
        print("      3. O POST /api/login não devolveu token com o formato testado; se fizer")
        print("         sentido, tente outro --formato ou registre a resposta acima no ticket.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
