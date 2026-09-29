"""
Diagnóstico completo da estação de trabalho.

Responde a uma pergunta só: **esta máquina consegue conduzir uma outorga hoje?**

Antes existia apenas o diagnóstico do Assinador SERPRO. Isso deixava passar as
falhas que mais custam tempo na operação real, porque todas produzem, na tela
do operador, a mesma mensagem genérica do portal:

- relógio do Windows fora de hora — quebra a validação TLS, a verificação da
  cadeia do certificado e, silenciosamente, a janela de 5 minutos do HMAC do
  protocolo do Agent. É a causa raiz mais desperdiçada de tempo que existe
  neste fluxo, porque nada na tela diz "seu relógio está errado";
- DNS sem resolver os domínios oficiais;
- portal fora do ar (ou bloqueado por proxy/firewall corporativo);
- navegador ausente ou antigo demais;
- nenhum certificado vigente no repositório.

Cada verificação devolve `PASS`, `AVISO` ou `FALHA` — nunca uma exceção. Um
diagnóstico que estoura no meio é inútil justamente na máquina com problema,
que é a única onde ele importa.

Nenhuma verificação altera o sistema. Isto aqui é um termômetro, não um
instalador: não mexe em `hosts`, não instala nada, não mexe em política de
navegador. Quando encontra problema, diz o que fazer e deixa a decisão com a
pessoa.
"""

from __future__ import annotations

import enum
import logging
import platform
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

import httpx

from cajuru_agent import assinador as diag_assinador
from cajuru_agent import certificados as inventario

log = logging.getLogger("cajuru.agent.diagnostico")


class Nivel(str, enum.Enum):
    """Resultado de uma verificação, em ordem crescente de gravidade."""

    PASS = "PASS"
    AVISO = "AVISO"
    FALHA = "FALHA"
    #: Não se aplica a este ambiente (ex.: repositório do Windows no Linux).
    #: Diferente de PASS de propósito: não verificado não é o mesmo que ok.
    PULADO = "PULADO"


_ORDEM = {Nivel.PULADO: 0, Nivel.PASS: 1, Nivel.AVISO: 2, Nivel.FALHA: 3}

#: Domínios oficiais que precisam resolver e responder.
HOSTS_OFICIAIS: tuple[str, ...] = (
    "servicos.receitafederal.gov.br",
    "cav.receita.fazenda.gov.br",
    "sso.acesso.gov.br",
)

#: Host usado como referência de hora. É oficial e responde `Date` em HTTPS.
HOST_REFERENCIA_HORA = "servicos.receitafederal.gov.br"

#: Desvio de relógio tolerado. O protocolo do Agent recusa requisição com mais
#: de 5 min de diferença; avisamos bem antes disso para o operador corrigir
#: enquanto ainda é só um aviso.
DESVIO_AVISO_SEGUNDOS = 60
DESVIO_FALHA_SEGUNDOS = 240

#: Abaixo disso o A1 é tratado como "vencendo" no diagnóstico.
DIAS_ALERTA_CERTIFICADO = 30

_VERSAO = re.compile(r"(\d+(?:\.\d+){1,3})")


@dataclass(frozen=True)
class Verificacao:
    """Resultado de um item do diagnóstico."""

    chave: str
    titulo: str
    nivel: Nivel
    detalhe: str = ""
    #: O que a pessoa deve fazer. Vazio quando não há nada a fazer.
    acao: str = ""
    #: Fatos estruturados, para a saída JSON. Nunca contém segredo.
    dados: dict = field(default_factory=dict)

    def para_json(self) -> dict:
        return {
            "chave": self.chave,
            "titulo": self.titulo,
            "nivel": self.nivel.value,
            "detalhe": self.detalhe,
            "acao": self.acao,
            "dados": self.dados,
        }


@dataclass
class Relatorio:
    """Conjunto de verificações + veredito."""

    verificacoes: list[Verificacao] = field(default_factory=list)
    gerado_em: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def pior_nivel(self) -> Nivel:
        if not self.verificacoes:
            return Nivel.PULADO
        return max((v.nivel for v in self.verificacoes), key=lambda n: _ORDEM[n])

    @property
    def apto(self) -> bool:
        """Apto = nenhuma FALHA. Aviso não impede operar, mas aparece."""
        return self.pior_nivel is not Nivel.FALHA

    def contagem(self) -> dict[str, int]:
        return {
            nivel.value: sum(1 for v in self.verificacoes if v.nivel is nivel)
            for nivel in Nivel
        }

    def falhas(self) -> list[Verificacao]:
        return [v for v in self.verificacoes if v.nivel is Nivel.FALHA]

    def para_json(self) -> dict:
        return {
            "gerado_em": self.gerado_em.isoformat(),
            "apto": self.apto,
            "pior_nivel": self.pior_nivel.value,
            "contagem": self.contagem(),
            "verificacoes": [v.para_json() for v in self.verificacoes],
        }


# ---------------------------------------------------------------------------
# Verificações individuais
#
# Cada uma recebe as dependências que usa (cliente HTTP, resolvedor DNS,
# relógio). Isso não é cerimônia: é o que permite testar "DNS quebrado" e
# "relógio 10 minutos adiantado" sem quebrar a máquina de verdade.
# ---------------------------------------------------------------------------


def verificar_sistema() -> Verificacao:
    """Sistema operacional e arquitetura."""
    sistema = platform.system()
    versao = platform.version()
    release = platform.release()
    dados = {"sistema": sistema, "release": release, "versao": versao}

    if sistema != "Windows":
        return Verificacao(
            chave="sistema",
            titulo="Sistema operacional",
            nivel=Nivel.AVISO,
            detalhe=f"{sistema} {release} — ambiente não homologado para o Assinador SERPRO.",
            acao=(
                "O fluxo de outorga com A1 e Assinador Desktop é homologado em "
                "Windows 10/11. Fora dele, use esta estação apenas para consulta."
            ),
            dados=dados,
        )

    return Verificacao(
        chave="sistema",
        titulo="Sistema operacional",
        nivel=Nivel.PASS,
        detalhe=f"Windows {release} (build {versao}).",
        dados=dados,
    )


def verificar_python() -> Verificacao:
    """O Agent exige 3.11+ (usa `X | Y` em anotação avaliada e `tomllib`)."""
    atual = sys.version_info
    texto = f"{atual.major}.{atual.minor}.{atual.micro}"
    if atual < (3, 11):
        return Verificacao(
            chave="python",
            titulo="Python",
            nivel=Nivel.FALHA,
            detalhe=f"Python {texto} — o Agent exige 3.11 ou superior.",
            acao="Reinstale o Agent com `instalar_agent.ps1`, que provisiona o venv correto.",
            dados={"versao": texto},
        )
    return Verificacao(
        chave="python",
        titulo="Python",
        nivel=Nivel.PASS,
        detalhe=f"Python {texto}.",
        dados={"versao": texto},
    )


def verificar_relogio(
    *,
    cliente: httpx.Client | None = None,
    agora: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    host: str = HOST_REFERENCIA_HORA,
) -> Verificacao:
    """Compara o relógio local com o cabeçalho `Date` de um host oficial.

    Por que isto é uma verificação de primeira classe e não um detalhe: um
    relógio errado produz, ao mesmo tempo, erro de TLS, "certificado fora da
    validade" num A1 perfeitamente válido, e recusa silenciosa do protocolo do
    Agent pela janela de nonce. O operador vê três sintomas desconexos e
    nenhum deles menciona hora.
    """
    fechar = cliente is None
    cliente = cliente or httpx.Client(timeout=8.0, follow_redirects=True)
    try:
        resposta = cliente.head(f"https://{host}/")
        cabecalho = resposta.headers.get("Date", "")
        if not cabecalho:
            return Verificacao(
                chave="relogio",
                titulo="Relógio do sistema",
                nivel=Nivel.AVISO,
                detalhe="O host oficial não devolveu o cabeçalho Date; não foi possível comparar.",
                acao="Confira manualmente em Configurações → Hora e idioma.",
            )
        referencia = parsedate_to_datetime(cabecalho)
        if referencia.tzinfo is None:
            referencia = referencia.replace(tzinfo=timezone.utc)
        desvio = abs((agora() - referencia).total_seconds())
        dados = {"desvio_segundos": round(desvio, 1), "referencia": referencia.isoformat()}

        if desvio >= DESVIO_FALHA_SEGUNDOS:
            return Verificacao(
                chave="relogio",
                titulo="Relógio do sistema",
                nivel=Nivel.FALHA,
                detalhe=f"Relógio {desvio:.0f}s fora da hora oficial.",
                acao=(
                    "Sincronize o relógio: Configurações → Hora e idioma → "
                    "'Sincronizar agora'. Acima de 5 min o servidor recusa as "
                    "requisições desta estação."
                ),
                dados=dados,
            )
        if desvio >= DESVIO_AVISO_SEGUNDOS:
            return Verificacao(
                chave="relogio",
                titulo="Relógio do sistema",
                nivel=Nivel.AVISO,
                detalhe=f"Relógio {desvio:.0f}s fora da hora oficial.",
                acao="Sincronize o relógio antes que passe de 5 minutos.",
                dados=dados,
            )
        return Verificacao(
            chave="relogio",
            titulo="Relógio do sistema",
            nivel=Nivel.PASS,
            detalhe=f"Dentro da hora oficial (desvio de {desvio:.0f}s).",
            dados=dados,
        )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return Verificacao(
            chave="relogio",
            titulo="Relógio do sistema",
            nivel=Nivel.AVISO,
            detalhe=f"Não foi possível obter a hora oficial ({type(exc).__name__}).",
            acao="Verifique a conexão; a checagem de relógio depende de alcançar o portal.",
        )
    finally:
        if fechar:
            cliente.close()


def verificar_dns(
    *,
    hosts: Sequence[str] = HOSTS_OFICIAIS,
    resolver: Callable[[str], str] = socket.gethostbyname,
) -> Verificacao:
    """Resolve os domínios oficiais."""
    resolvidos: dict[str, str] = {}
    falhos: list[str] = []
    for host in hosts:
        try:
            resolvidos[host] = resolver(host)
        except (OSError, UnicodeError):
            falhos.append(host)

    if falhos:
        return Verificacao(
            chave="dns",
            titulo="Resolução DNS",
            nivel=Nivel.FALHA,
            detalhe=f"Não resolveu: {', '.join(falhos)}.",
            acao=(
                "Verifique o DNS da estação e se um proxy/firewall corporativo "
                "bloqueia os domínios da Receita."
            ),
            dados={"resolvidos": resolvidos, "falhos": falhos},
        )
    return Verificacao(
        chave="dns",
        titulo="Resolução DNS",
        nivel=Nivel.PASS,
        detalhe=f"{len(resolvidos)} domínios oficiais resolvidos.",
        dados={"resolvidos": resolvidos},
    )


def verificar_portal(
    *,
    cliente: httpx.Client | None = None,
    hosts: Sequence[str] = HOSTS_OFICIAIS,
) -> Verificacao:
    """Alcance HTTPS dos endereços oficiais.

    Só um GET de disponibilidade na raiz — nada de sondar rota interna. O que
    interessa é "o caminho até a Receita está aberto?", não o conteúdo.
    """
    fechar = cliente is None
    cliente = cliente or httpx.Client(timeout=10.0, follow_redirects=True)
    estados: dict[str, str] = {}
    inacessiveis: list[str] = []
    try:
        for host in hosts:
            try:
                resposta = cliente.get(f"https://{host}/")
                estados[host] = str(resposta.status_code)
                if resposta.status_code >= 500:
                    inacessiveis.append(host)
            except httpx.HTTPError as exc:
                estados[host] = type(exc).__name__
                inacessiveis.append(host)
    finally:
        if fechar:
            cliente.close()

    if len(inacessiveis) == len(list(hosts)):
        return Verificacao(
            chave="portal",
            titulo="Portal da Receita",
            nivel=Nivel.FALHA,
            detalhe="Nenhum endereço oficial respondeu.",
            acao="Sem rede até a Receita não há operação. Verifique conexão, proxy e firewall.",
            dados={"estados": estados},
        )
    if inacessiveis:
        return Verificacao(
            chave="portal",
            titulo="Portal da Receita",
            nivel=Nivel.AVISO,
            detalhe=f"Sem resposta de: {', '.join(inacessiveis)}.",
            acao="Pode ser indisponibilidade momentânea do serviço. Repita o diagnóstico.",
            dados={"estados": estados},
        )
    return Verificacao(
        chave="portal",
        titulo="Portal da Receita",
        nivel=Nivel.PASS,
        detalhe=f"{len(estados)} endereços oficiais responderam.",
        dados={"estados": estados},
    )


#: Onde os navegadores registram a versão no Windows, e o binário no Unix.
_NAVEGADORES_WINDOWS = (
    ("Microsoft Edge", r"HKLM:\SOFTWARE\WOW6432Node\Microsoft\Edge\BLBeacon"),
    ("Google Chrome", r"HKLM:\SOFTWARE\WOW6432Node\Google\Update\Clients"),
)
_NAVEGADORES_UNIX = ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")


def _versao_navegador_windows() -> tuple[str, str]:
    """(nome, versão) do primeiro navegador Chromium encontrado no registro."""
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "$e=(Get-ItemProperty 'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Edge\\BLBeacon').version;"
        "if($e){Write-Output \"Edge|$e\"; exit}"
        "$c=(Get-ItemProperty 'HKLM:\\SOFTWARE\\WOW6432Node\\Google\\Chrome\\BLBeacon').version;"
        "if($c){Write-Output \"Chrome|$c\"}"
    )
    try:
        saida = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("versao_navegador_indisponivel: %s", exc)
        return "", ""
    if "|" in saida:
        nome, _, versao = saida.partition("|")
        return nome.strip(), versao.strip()
    return "", ""


def _versao_navegador_unix() -> tuple[str, str]:
    for binario in _NAVEGADORES_UNIX:
        caminho = shutil.which(binario)
        if not caminho:
            continue
        try:
            saida = subprocess.run(
                [caminho, "--version"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        encontrado = _VERSAO.search(saida or "")
        return binario, encontrado.group(1) if encontrado else ""
    return "", ""


def verificar_navegador(
    *, detector: Callable[[], tuple[str, str]] | None = None
) -> Verificacao:
    """Navegador Chromium disponível e sua versão.

    O portal é operado no navegador real da pessoa. Se não houver Edge nem
    Chrome, a condução não tem onde acontecer.
    """
    if detector is None:
        detector = (
            _versao_navegador_windows
            if platform.system() == "Windows"
            else _versao_navegador_unix
        )
    nome, versao = detector()

    if not nome:
        return Verificacao(
            chave="navegador",
            titulo="Navegador",
            nivel=Nivel.FALHA,
            detalhe="Nenhum navegador baseado em Chromium foi encontrado.",
            acao="Instale o Microsoft Edge ou o Google Chrome nesta estação.",
        )
    if not versao:
        return Verificacao(
            chave="navegador",
            titulo="Navegador",
            nivel=Nivel.AVISO,
            detalhe=f"{nome} encontrado, mas a versão não pôde ser lida.",
            acao="Confirme manualmente em 'Sobre' que o navegador está atualizado.",
            dados={"nome": nome},
        )
    return Verificacao(
        chave="navegador",
        titulo="Navegador",
        nivel=Nivel.PASS,
        detalhe=f"{nome} {versao}.",
        dados={"nome": nome, "versao": versao},
    )


def verificar_assinador(
    *,
    tem_certificado: bool,
    versao_minima: str = "4.0.0",
    diagnosticar: Callable[..., diag_assinador.Diagnostico] | None = None,
) -> Verificacao:
    """Assinador Digital SERPRO — reaproveita o diagnóstico já existente."""
    executar = diagnosticar or diag_assinador.diagnosticar
    resultado = executar(tem_certificado=tem_certificado)
    dados = resultado.para_envio()

    if not resultado.porta_local:
        faltando = []
        if not resultado.instalado:
            faltando.append("não instalado")
        if not resultado.em_execucao:
            faltando.append("não está em execução")
        if not resultado.hosts_mapeado:
            faltando.append(f"host {diag_assinador.HOST_MAPEADO} não mapeado")
        return Verificacao(
            chave="assinador",
            titulo="Assinador Digital SERPRO",
            nivel=Nivel.FALHA,
            detalhe="Assinador indisponível: " + (", ".join(faltando) or "porta local fechada"),
            acao=(
                "Abra o Assinador Desktop e confirme que ele está ativo na bandeja. "
                f"Manual oficial: {diag_assinador.URL_MANUAL_OFICIAL}"
            ),
            dados=dados,
        )

    if resultado.versao and _versao_menor(resultado.versao, versao_minima):
        return Verificacao(
            chave="assinador",
            titulo="Assinador Digital SERPRO",
            nivel=Nivel.AVISO,
            detalhe=f"Versão {resultado.versao} é anterior à mínima exigida ({versao_minima}).",
            acao="Atualize o Assinador Desktop pelo site oficial do SERPRO.",
            dados=dados,
        )

    return Verificacao(
        chave="assinador",
        titulo="Assinador Digital SERPRO",
        nivel=Nivel.PASS,
        detalhe=f"Respondendo na porta {diag_assinador.PORTA_LOCAL}"
        + (f", versão {resultado.versao}." if resultado.versao else "."),
        dados=dados,
    )


def _versao_menor(atual: str, minima: str) -> bool:
    """Compara versões campo a campo, tolerando formatos diferentes."""

    def partes(texto: str) -> list[int]:
        encontrado = _VERSAO.search(texto or "")
        if not encontrado:
            return []
        return [int(p) for p in encontrado.group(1).split(".")]

    a, b = partes(atual), partes(minima)
    if not a or not b:
        return False
    tamanho = max(len(a), len(b))
    a += [0] * (tamanho - len(a))
    b += [0] * (tamanho - len(b))
    return a < b


def verificar_certificados(
    certificados: Iterable[inventario.CertificadoLocal],
    *,
    agora: datetime | None = None,
    dias_alerta: int = DIAS_ALERTA_CERTIFICADO,
) -> list[Verificacao]:
    """Resumo do repositório + alerta de vencimento próximo.

    Devolve duas verificações porque são decisões diferentes: "existe
    certificado utilizável?" (bloqueia hoje) e "algum vence em breve?"
    (bloqueia daqui a algumas semanas, e é exatamente o que ninguém vê chegar).
    """
    agora = agora or datetime.now(timezone.utc)
    lista = list(certificados)

    vigentes = [c for c in lista if inventario.vigente(c, agora) and c.tem_chave_privada]
    vencidos = [c for c in lista if not inventario.vigente(c, agora)]
    sem_chave = [c for c in lista if c.tem_chave_privada is False]

    if platform.system() != "Windows" and not lista:
        resumo = Verificacao(
            chave="certificados",
            titulo="Repositório de certificados",
            nivel=Nivel.PULADO,
            detalhe="Repositório do Windows indisponível neste sistema.",
            dados={"total": 0},
        )
        return [resumo]

    dados = {
        "total": len(lista),
        "vigentes": len(vigentes),
        "vencidos": len(vencidos),
        "sem_chave_privada": len(sem_chave),
    }

    if not vigentes:
        resumo = Verificacao(
            chave="certificados",
            titulo="Repositório de certificados",
            nivel=Nivel.FALHA,
            detalhe=f"{len(lista)} certificados encontrados, nenhum vigente e com chave privada.",
            acao=(
                "Importe os A1 no repositório do Windows do usuário que opera a "
                "estação. Arquivo .pfx solto em pasta não é utilizável pelo Assinador."
            ),
            dados=dados,
        )
        return [resumo]

    resumo = Verificacao(
        chave="certificados",
        titulo="Repositório de certificados",
        nivel=Nivel.PASS,
        detalhe=(
            f"{len(vigentes)} certificados vigentes"
            + (f", {len(vencidos)} vencidos" if vencidos else "")
            + (f", {len(sem_chave)} sem chave privada" if sem_chave else "")
            + "."
        ),
        dados=dados,
    )

    vencendo = []
    for certificado in vigentes:
        dias = _dias_restantes(certificado, agora)
        if dias is not None and dias <= dias_alerta:
            vencendo.append((certificado, dias))
    vencendo.sort(key=lambda item: item[1])

    if not vencendo:
        alerta = Verificacao(
            chave="certificados_vencendo",
            titulo="Certificados a vencer",
            nivel=Nivel.PASS,
            detalhe=f"Nenhum certificado vence nos próximos {dias_alerta} dias.",
            dados={"quantidade": 0},
        )
    else:
        # O documento é mascarado: o diagnóstico é colado em chamado e grupo
        # de mensagem com frequência, e CNPJ de cliente não precisa passear.
        exemplos = [
            {
                "documento": _mascarar(certificado.documento),
                "titular": certificado.titular_nome[:60],
                "dias": dias,
                "valido_ate": certificado.valido_ate,
            }
            for certificado, dias in vencendo[:10]
        ]
        alerta = Verificacao(
            chave="certificados_vencendo",
            titulo="Certificados a vencer",
            nivel=Nivel.AVISO,
            detalhe=f"{len(vencendo)} certificado(s) vencem em até {dias_alerta} dias.",
            acao="Renove antes que o cliente entre na fila — A1 vencido derruba a outorga no meio.",
            dados={"quantidade": len(vencendo), "itens": exemplos},
        )

    return [resumo, alerta]


def _dias_restantes(
    certificado: inventario.CertificadoLocal, agora: datetime
) -> int | None:
    try:
        fim = datetime.fromisoformat(certificado.valido_ate.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if fim.tzinfo is None:
        fim = fim.replace(tzinfo=timezone.utc)
    return (fim - agora).days


def _mascarar(documento: str) -> str:
    """CNPJ/CPF com o miolo oculto — espelha `app.core.mascaramento`."""
    digitos = "".join(c for c in str(documento or "") if c.isdigit())
    if len(digitos) == 14:
        return f"{digitos[:2]}.***.***/{digitos[8:12]}-{digitos[12:]}"
    if len(digitos) == 11:
        return f"{digitos[:3]}.***.***-{digitos[9:]}"
    return "*" * len(digitos)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------


def executar(
    *,
    pasta_pfx: Path | None = None,
    versao_minima_assinador: str = "4.0.0",
    verificar_rede: bool = True,
    cliente: httpx.Client | None = None,
) -> Relatorio:
    """Roda o diagnóstico inteiro. Nunca levanta exceção.

    `verificar_rede=False` permite rodar offline (útil em teste e em máquina
    sem saída para a internet), marcando os itens de rede como PULADO em vez
    de fingir que passaram.
    """
    verificacoes: list[Verificacao] = [verificar_sistema(), verificar_python()]

    if verificar_rede:
        for executar_item in (
            lambda: verificar_relogio(cliente=cliente),
            verificar_dns,
            lambda: verificar_portal(cliente=cliente),
        ):
            verificacoes.append(_protegido(executar_item))
    else:
        verificacoes.extend(
            Verificacao(
                chave=chave,
                titulo=titulo,
                nivel=Nivel.PULADO,
                detalhe="Verificação de rede desligada nesta execução.",
            )
            for chave, titulo in (
                ("relogio", "Relógio do sistema"),
                ("dns", "Resolução DNS"),
                ("portal", "Portal da Receita"),
            )
        )

    verificacoes.append(_protegido(verificar_navegador))

    try:
        lista = inventario.inventariar(pasta_pfx)
    except Exception as exc:  # inventário depende de PowerShell e disco
        log.warning("inventario_falhou: %s", exc)
        lista = []
        verificacoes.append(
            Verificacao(
                chave="certificados",
                titulo="Repositório de certificados",
                nivel=Nivel.FALHA,
                detalhe=f"O inventário de certificados falhou ({type(exc).__name__}).",
                acao="Verifique se o PowerShell está disponível e se a política de execução permite consulta.",
            )
        )
    else:
        verificacoes.extend(verificar_certificados(lista))

    tem_certificado = any(
        inventario.vigente(c) and c.tem_chave_privada for c in lista
    )
    verificacoes.append(
        _protegido(
            lambda: verificar_assinador(
                tem_certificado=tem_certificado,
                versao_minima=versao_minima_assinador,
            )
        )
    )

    return Relatorio(verificacoes=verificacoes)


def _protegido(funcao: Callable[[], Verificacao]) -> Verificacao:
    """Isola a verificação: um item quebrado não derruba o diagnóstico."""
    try:
        return funcao()
    except Exception as exc:  # noqa: BLE001 — diagnóstico não pode morrer
        log.warning("verificacao_falhou: %s", exc)
        return Verificacao(
            chave=getattr(funcao, "__name__", "desconhecida"),
            titulo="Verificação",
            nivel=Nivel.AVISO,
            detalhe=f"A verificação não pôde ser concluída ({type(exc).__name__}).",
        )


#: Símbolo de cada nível na saída de console.
_SIMBOLO = {
    Nivel.PASS: "PASS",
    Nivel.AVISO: "AVISO",
    Nivel.FALHA: "FALHA",
    Nivel.PULADO: "----",
}


def formatar(relatorio: Relatorio) -> str:
    """Saída de console alinhada, legível em terminal e colável em chamado."""
    linhas = ["", "Diagnóstico da estação — Procurações RFB", "─" * 64]
    for item in relatorio.verificacoes:
        linhas.append(f"[{_SIMBOLO[item.nivel]}] {item.titulo}: {item.detalhe}")
        if item.acao and item.nivel in (Nivel.FALHA, Nivel.AVISO):
            linhas.append(f"         → {item.acao}")
    linhas.append("─" * 64)

    contagem = relatorio.contagem()
    linhas.append(
        f"{contagem['PASS']} ok · {contagem['AVISO']} aviso(s) · "
        f"{contagem['FALHA']} falha(s) · {contagem['PULADO']} não verificado(s)"
    )
    if relatorio.apto:
        linhas.append("Resultado: estação APTA a conduzir uma outorga.")
    else:
        linhas.append("Resultado: estação NÃO APTA. Resolva as falhas acima.")
    linhas.append("")
    return "\n".join(linhas)
