"""
Política de pré-requisito do **Assinador Digital SERPRO (Desktop)**.

Contexto oficial, verificado na documentação do produto:

- o Assinador Desktop expõe um **servidor local em `https://127.0.0.1:65156`**,
  usado pelos portais do Governo Federal para assinar com certificado
  instalado na máquina (A1 em repositório do Windows ou A3 em token);
- o acesso exige o mapeamento
  ``127.0.0.1  assinador-desktop.serpro.gov.br`` no arquivo
  ``C:\\Windows\\System32\\drivers\\etc\\hosts`` — instalado pelo próprio
  pacote oficial;
- navegadores baseados em Chromium (Chrome/Edge) pedem, desde 2025, a
  permissão **"Acesso à rede local"** para que a página do portal alcance
  `127.0.0.1`; sem ela a assinatura simplesmente não abre;
- o SERPRO publica uma página oficial de verificação
  (``https://www.frameworkdemoiselle.gov.br/v3/signer/demo/``) e o manual do
  usuário traz a seção de teste de conexão.

**O que este módulo faz e o que ele não faz.** Ele *não* assina nada e *não*
substitui o Assinador — fazer criptografia própria no lugar do componente
oficial quebraria o fluxo homologado e a validade jurídica da assinatura.
Ele define o contrato do diagnóstico que o Agent executa na estação e a
política que o servidor aplica sobre o resultado: sem Assinador em condições,
o job **não sai do lugar** e o operador é avisado antes de gastar uma sessão
com certificado.

Isso é o critério de aceite D: *Assinador SERPRO indisponível → job não inicia
+ alerta*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Endereço local publicado pelo Assinador Desktop. Não é uma API nossa nem
#: um endpoint inventado: é o que a documentação oficial descreve, e quem
#: conversa com ele é o Agent, na própria máquina.
HOST_LOCAL = "127.0.0.1"
PORTA_LOCAL = 65156
URL_LOCAL = f"https://{HOST_LOCAL}:{PORTA_LOCAL}"
HOST_MAPEADO = "assinador-desktop.serpro.gov.br"
URL_VERIFICACAO_OFICIAL = "https://www.frameworkdemoiselle.gov.br/v3/signer/demo/"
URL_MANUAL_OFICIAL = (
    "https://artefatos-assinador.serpro.gov.br/downloads/Manual_Usuario_Assinador_Desktop.pdf"
)

#: Itens do diagnóstico, na ordem em que o Agent deve executá-los. Cada um
#: tem um conserto objetivo — é isso que transforma "não funciona" em tarefa.
VERIFICACOES: tuple[tuple[str, str, str], ...] = (
    (
        "instalado",
        "Assinador Digital SERPRO instalado",
        "Instale o Assinador Digital SERPRO Desktop a partir do site oficial do SERPRO.",
    ),
    (
        "em_execucao",
        "Processo do Assinador em execução",
        "Abra o Assinador Digital SERPRO (ele fica na área de notificação do Windows).",
    ),
    (
        "hosts_mapeado",
        f"Mapeamento de {HOST_MAPEADO} no arquivo hosts",
        "Reinstale o Assinador com permissão de administrador: o instalador oficial "
        "grava o mapeamento no arquivo hosts.",
    ),
    (
        "porta_local",
        f"Servidor local respondendo em {URL_LOCAL}",
        "Verifique firewall/antivírus bloqueando a porta local 65156 e reinicie o Assinador.",
    ),
    (
        "versao_compativel",
        "Versão mínima homologada",
        "Atualize o Assinador Digital SERPRO para a versão exigida na configuração do módulo.",
    ),
    (
        "certificado_visivel",
        "Certificado acessível ao Assinador",
        "Confirme que o A1 está importado no repositório do Windows (ou o A3 conectado) "
        "para o mesmo usuário que executa o Agent.",
    ),
    (
        "permissao_navegador",
        "Permissão de acesso à rede local no navegador",
        "No navegador, autorize 'Acesso à rede local' para o portal e revalide em "
        f"{URL_VERIFICACAO_OFICIAL}.",
    ),
)

_ORDEM = tuple(chave for chave, _, _ in VERIFICACOES)
_ROTULOS = {chave: rotulo for chave, rotulo, _ in VERIFICACOES}
_CONSERTOS = {chave: conserto for chave, _, conserto in VERIFICACOES}

#: Itens que, faltando, impedem a assinatura. `permissao_navegador` é aviso:
#: só se confirma no momento em que a página do portal abre.
BLOQUEANTES = frozenset(
    {"instalado", "em_execucao", "hosts_mapeado", "porta_local", "versao_compativel"}
)


@dataclass(frozen=True)
class Avaliacao:
    """Veredito sobre o ambiente de assinatura de uma estação."""

    apto: bool
    versao: str
    resumo: str
    pendencias: tuple[str, ...] = field(default_factory=tuple)
    avisos: tuple[str, ...] = field(default_factory=tuple)
    consertos: tuple[str, ...] = field(default_factory=tuple)

    @property
    def detalhe(self) -> str:
        partes = [self.resumo]
        if self.consertos:
            partes.append("Como resolver: " + " ".join(self.consertos))
        return " ".join(partes)[:255]


def comparar_versao(atual: str, minima: str) -> bool:
    """`True` se `atual >= minima`. Trecho não numérico conta como zero."""
    def partes(texto: str) -> list[int]:
        achados = re.findall(r"\d+", str(texto or ""))
        return [int(valor) for valor in achados[:4]] or [0]

    a, b = partes(atual), partes(minima)
    tamanho = max(len(a), len(b))
    a += [0] * (tamanho - len(a))
    b += [0] * (tamanho - len(b))
    return a >= b


def avaliar(
    diagnostico: dict | None,
    *,
    versao_minima: str = "",
    exigido: bool = True,
) -> Avaliacao:
    """Traduz o relatório do Agent em decisão de liberar ou barrar o job.

    Ausência de informação **não** é aprovação: diagnóstico vazio reprova
    quando o Assinador é exigido. Falhar fechado é o comportamento correto
    para pré-requisito de assinatura.
    """
    dados = dict(diagnostico or {})
    versao = str(dados.get("versao") or "").strip()[:30]

    if not exigido:
        return Avaliacao(
            apto=True,
            versao=versao,
            resumo=(
                "Verificação do Assinador desativada na configuração — a assinatura "
                "depende inteiramente do operador."
            ),
        )

    if not dados:
        return Avaliacao(
            apto=False,
            versao="",
            resumo="A estação ainda não enviou o diagnóstico do Assinador SERPRO.",
            pendencias=("diagnostico_ausente",),
            consertos=(
                "Execute o Cajuru Agent na estação para que ele reporte o ambiente de assinatura.",
            ),
        )

    pendencias: list[str] = []
    avisos: list[str] = []
    for chave in _ORDEM:
        if chave == "versao_compativel":
            ok = comparar_versao(versao, versao_minima) if versao_minima else bool(versao)
        else:
            ok = bool(dados.get(chave))
        if ok:
            continue
        if chave in BLOQUEANTES:
            pendencias.append(chave)
        else:
            avisos.append(chave)

    if pendencias:
        faltando = ", ".join(_ROTULOS[chave].lower() for chave in pendencias)
        return Avaliacao(
            apto=False,
            versao=versao,
            resumo=f"Assinador SERPRO indisponível na estação: {faltando}.",
            pendencias=tuple(pendencias),
            avisos=tuple(avisos),
            consertos=tuple(_CONSERTOS[chave] for chave in pendencias),
        )

    resumo = f"Assinador SERPRO {versao or 'detectado'} pronto para uso."
    if avisos:
        resumo += " Pendência não bloqueante: " + ", ".join(
            _ROTULOS[chave].lower() for chave in avisos
        ) + "."
    return Avaliacao(
        apto=True,
        versao=versao,
        resumo=resumo,
        avisos=tuple(avisos),
        consertos=tuple(_CONSERTOS[chave] for chave in avisos),
    )


def roteiro_de_instalacao(
    apenas: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, str]]:
    """Passo a passo exibido na tela de Agents quando algo está faltando.

    Passando `apenas`, o roteiro é reduzido às pendências daquela estação —
    quem já instalou tudo menos a permissão do navegador não precisa reler o
    manual inteiro.
    """
    filtro = {chave for chave in (apenas or ()) if chave}
    return [
        {
            "chave": chave,
            "titulo": rotulo,
            "acao": conserto,
        }
        for chave, rotulo, conserto in VERIFICACOES
        if not filtro or chave in filtro
    ] + [
        {
            "chave": "validacao_oficial",
            "titulo": "Validar no ambiente oficial do SERPRO",
            "acao": (
                f"Abra {URL_VERIFICACAO_OFICIAL} e conclua uma assinatura de teste. "
                f"O manual oficial está em {URL_MANUAL_OFICIAL}."
            ),
        }
    ]
