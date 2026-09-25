"""
Reconciliação entre as fontes externas e a carteira do escritório.

Sincronizar não é "importar". É responder, para cada empresa cadastrada, qual
é a situação da autorização de acesso — e fazer isso de forma que rodar duas
vezes seguidas produza exatamente o mesmo estado.

Como a idempotência é garantida:

- a chave natural é ``(escritorio, empresa, outorgado)``, com UNIQUE no banco;
- nada é criado para documento que não está na carteira: vira `ignorado` com
  o motivo registrado, não uma empresa fantasma;
- só conta como "atualizado" o registro cujo conteúdo mudou de fato, senão o
  relatório mentiria e todo rodapé de tela viraria ruído.

Precedência entre fontes: um dado vindo do **canal oficial** (Integra
Contador) sobrepõe o de fonte secundária; o inverso não acontece. Sem isso,
uma planilha desatualizada poderia "apagar" o que a API oficial confirmou.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Empresa
from app.procuracoes.estados import PRAZO_ACEITE, StatusAutorizacao
from app.procuracoes.integracoes.base import (
    FonteError,
    FonteProcuracoes,
    RegistroProcuracao,
)
from app.procuracoes.integracoes.registro import FONTE_INTEGRA_CONTADOR, ROTULOS
from app.procuracoes.modelos import (
    Autorizacao,
    AutorizacaoPermissao,
    IntegracaoErro,
    IntegracaoJob,
    ProcuracaoConfiguracao,
)
from app.procuracoes.servicos import eventos
from app.procuracoes.servicos.configuracao import obter_configuracao

log = logging.getLogger("cajuru.procuracoes.sincronizacao")

#: Fontes cujo dado prevalece sobre as demais, da mais forte para a mais fraca.
PRECEDENCIA: tuple[str, ...] = (FONTE_INTEGRA_CONTADOR, "jettax360", "planilha", "manual")

MAX_ERROS_REGISTRADOS = 500


@dataclass
class ResultadoSincronizacao:
    """Relatório do que aconteceu — é o que a tela mostra ao operador."""

    fonte: str
    recebidos: int = 0
    criados: int = 0
    atualizados: int = 0
    ignorados: int = 0
    invalidos: int = 0
    inalterados: int = 0
    mensagem: str = ""
    integracao_job_id: int | None = None
    erros: list[dict[str, str]] = field(default_factory=list)

    @property
    def resumo(self) -> str:
        return (
            f"{self.recebidos} recebido(s): {self.criados} criado(s), "
            f"{self.atualizados} atualizado(s), {self.inalterados} sem mudança, "
            f"{self.ignorados} ignorado(s), {self.invalidos} inválido(s)."
        )


def _forca(fonte: str) -> int:
    """Menor índice = fonte mais confiável."""
    try:
        return PRECEDENCIA.index(fonte)
    except ValueError:
        return len(PRECEDENCIA)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def sincronizar(
    db: Session,
    escritorio_id: int,
    fonte_nome: str,
    fonte: FonteProcuracoes,
    *,
    origem: str = "manual",
    documentos: list[str] | None = None,
) -> ResultadoSincronizacao:
    """Executa a leitura e reconcilia. Não faz commit — quem chama decide."""
    config = obter_configuracao(db, escritorio_id)
    registro_job = IntegracaoJob(
        escritorio_id=escritorio_id,
        fonte=fonte_nome[:40],
        status="em_andamento",
        origem=origem[:20],
    )
    db.add(registro_job)
    db.flush()

    resultado = ResultadoSincronizacao(fonte=fonte_nome, integracao_job_id=registro_job.id)
    try:
        registros = fonte.listar(documentos)
    except FonteError as exc:
        registro_job.status = "falhou"
        registro_job.mensagem = str(exc)[:1000]
        registro_job.finalizado_em = _agora()
        db.add(
            IntegracaoErro(
                integracao_job_id=registro_job.id,
                codigo=exc.codigo[:60],
                mensagem=str(exc)[:1000],
            )
        )
        eventos.notificar(
            db,
            escritorio_id,
            chave=f"sincronizacao:{fonte_nome}:falha",
            tipo="sincronizacao_falhou",
            nivel="erro",
            titulo=f"Sincronização com {ROTULOS.get(fonte_nome, fonte_nome)} falhou",
            detalhe=str(exc)[:1000],
        )
        db.flush()
        log.warning(
            "procuracao_sincronizacao_falhou",
            extra={"fonte": fonte_nome, "escritorio": escritorio_id, "codigo": exc.codigo},
        )
        raise

    resultado.recebidos = len(registros)
    indice = _indice_de_empresas(db, escritorio_id)

    for bruto in registros:
        try:
            item = bruto.normalizado()
        except ValueError:
            resultado.invalidos += 1
            _registrar_erro(
                db,
                registro_job,
                resultado,
                documento=str(bruto.documento)[:30],
                codigo="DOCUMENTO_INVALIDO",
                mensagem="CNPJ/CPF fora do formato esperado.",
            )
            continue

        empresa = indice.get(item.documento)
        if empresa is None:
            resultado.ignorados += 1
            _registrar_erro(
                db,
                registro_job,
                resultado,
                documento=item.documento,
                codigo="EMPRESA_NAO_CADASTRADA",
                mensagem=(
                    "A fonte retornou um documento que não existe na carteira. "
                    "Cadastre a empresa para que ela entre no controle de procurações."
                ),
            )
            continue

        situacao = _aplicar(db, config, empresa, item, fonte_nome)
        if situacao == "sem_outorgado":
            resultado.ignorados += 1
            _registrar_erro(
                db,
                registro_job,
                resultado,
                documento=item.documento,
                codigo="OUTORGADO_NAO_CONFIGURADO",
                mensagem=(
                    "Nenhum CNPJ/CPF da contabilidade está definido em "
                    "Configurações → Procurações. Sem outorgado não existe chave "
                    "natural para a autorização."
                ),
            )
            continue
        if situacao == "criado":
            resultado.criados += 1
        elif situacao == "atualizado":
            resultado.atualizados += 1
        elif situacao == "preterido":
            resultado.ignorados += 1
        else:
            resultado.inalterados += 1

    registro_job.status = "concluido"
    registro_job.registros_recebidos = resultado.recebidos
    registro_job.registros_criados = resultado.criados
    registro_job.registros_atualizados = resultado.atualizados
    registro_job.registros_ignorados = resultado.ignorados
    registro_job.registros_invalidos = resultado.invalidos
    registro_job.mensagem = resultado.resumo[:1000]
    registro_job.finalizado_em = _agora()
    resultado.mensagem = resultado.resumo
    db.flush()

    log.info(
        "procuracao_sincronizacao_concluida",
        extra={
            "fonte": fonte_nome,
            "escritorio": escritorio_id,
            "recebidos": resultado.recebidos,
            "criados": resultado.criados,
            "atualizados": resultado.atualizados,
        },
    )
    return resultado


def _indice_de_empresas(db: Session, escritorio_id: int) -> dict[str, Empresa]:
    empresas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .all()
    )
    return {empresa.cnpj_cpf: empresa for empresa in empresas}


def _registrar_erro(
    db: Session,
    registro_job: IntegracaoJob,
    resultado: ResultadoSincronizacao,
    *,
    documento: str,
    codigo: str,
    mensagem: str,
) -> None:
    if len(resultado.erros) < MAX_ERROS_REGISTRADOS:
        db.add(
            IntegracaoErro(
                integracao_job_id=registro_job.id,
                documento=documento[:30],
                codigo=codigo[:60],
                mensagem=mensagem[:1000],
            )
        )
        resultado.erros.append(
            {"documento": documento, "codigo": codigo, "mensagem": mensagem}
        )


def _aplicar(
    db: Session,
    config: ProcuracaoConfiguracao,
    empresa: Empresa,
    item: RegistroProcuracao,
    fonte_nome: str,
) -> str:
    """Grava a situação de uma empresa. Devolve criado|atualizado|igual|preterido."""
    outorgado = item.outorgado_documento or config.outorgado_documento
    if not outorgado:
        # Sem outorgado configurado não há chave natural. Em vez de engolir o
        # registro, o chamador transforma isso em erro visível na tela.
        return "sem_outorgado"

    autorizacao = (
        db.query(Autorizacao)
        .filter(
            Autorizacao.escritorio_id == empresa.escritorio_id,
            Autorizacao.empresa_id == empresa.id,
            Autorizacao.outorgado_documento == outorgado,
        )
        .first()
    )

    if autorizacao is not None and _forca(fonte_nome) > _forca(autorizacao.origem_dado):
        # Fonte mais fraca não sobrescreve confirmação de fonte mais forte;
        # apenas marca que foi vista.
        autorizacao.sincronizado_em = _agora()
        db.flush()
        return "preterido"

    novo = autorizacao is None
    if novo:
        autorizacao = Autorizacao(
            escritorio_id=empresa.escritorio_id,
            empresa_id=empresa.id,
            outorgante_documento=empresa.cnpj_cpf,
            outorgante_nome=empresa.razao_social,
            outorgado_documento=outorgado,
            outorgado_nome=config.outorgado_nome,
            situacao=StatusAutorizacao.SEM_AUTORIZACAO.value,
        )
        db.add(autorizacao)
        db.flush()

    anterior = (
        autorizacao.situacao,
        autorizacao.data_inicio,
        autorizacao.data_validade,
        autorizacao.protocolo,
        autorizacao.escopo_servicos,
    )

    autorizacao.situacao = item.situacao.value
    autorizacao.data_inicio = item.data_inicio or autorizacao.data_inicio
    autorizacao.data_validade = item.data_validade
    if item.protocolo:
        autorizacao.protocolo = item.protocolo
    if item.razao_social and not autorizacao.outorgante_nome:
        autorizacao.outorgante_nome = item.razao_social
    autorizacao.origem_dado = fonte_nome[:30]
    autorizacao.sincronizado_em = _agora()
    if item.situacao in {StatusAutorizacao.ATIVA, StatusAutorizacao.EXPIRADA}:
        autorizacao.confirmado_em = _agora()
    if item.situacao is StatusAutorizacao.EM_ANALISE and autorizacao.prazo_aceite_ate is None:
        autorizacao.prazo_aceite_ate = date.today() + PRAZO_ACEITE

    codigos = tuple(servico.codigo for servico in item.servicos)
    if codigos:
        autorizacao.escopo_servicos = "ALL" if codigos == ("ALL",) else "LISTA"
        _sincronizar_permissoes(db, autorizacao, item)

    db.flush()
    if novo:
        return "criado"

    atual = (
        autorizacao.situacao,
        autorizacao.data_inicio,
        autorizacao.data_validade,
        autorizacao.protocolo,
        autorizacao.escopo_servicos,
    )
    return "atualizado" if atual != anterior else "igual"


def _sincronizar_permissoes(
    db: Session, autorizacao: Autorizacao, item: RegistroProcuracao
) -> None:
    """Substitui a lista de serviços pelo que a fonte informou.

    Substituir e não mesclar é proposital: um serviço que sumiu da resposta
    foi revogado no portal, e manter o registro antigo daria ao operador a
    impressão de um acesso que ele não tem mais.
    """
    atuais = {
        permissao.codigo: permissao
        for permissao in db.query(AutorizacaoPermissao)
        .filter(AutorizacaoPermissao.autorizacao_id == autorizacao.id)
        .all()
    }
    vistos: set[str] = set()
    for servico in item.servicos:
        vistos.add(servico.codigo)
        existente = atuais.get(servico.codigo)
        if existente is None:
            db.add(
                AutorizacaoPermissao(
                    autorizacao_id=autorizacao.id,
                    codigo=servico.codigo[:120],
                    rotulo=(servico.rotulo or servico.codigo)[:255],
                    expira_em=servico.expira_em,
                    origem="sincronizacao",
                )
            )
        else:
            existente.rotulo = (servico.rotulo or servico.codigo)[:255]
            existente.expira_em = servico.expira_em
    for codigo, permissao in atuais.items():
        if codigo not in vistos:
            db.delete(permissao)
    db.flush()


def avaliar_vencimentos(
    db: Session, escritorio_id: int, *, hoje: date | None = None
) -> dict[str, int]:
    """Aplica o tempo sobre as autorizações — o que ninguém faz manualmente.

    Três efeitos, todos derivados de data e nenhum de suposição:

    1. `ATIVA` com validade no passado vira `EXPIRADA`;
    2. `EM_ANALISE` que passou dos 30 dias de aceite vira `CANCELADA` — é o
       que o próprio portal faz, e fingir que ainda está em análise esconderia
       a necessidade de refazer a outorga;
    3. autorização que entra na janela de alerta gera notificação única.
    """
    referencia = hoje or date.today()
    config = obter_configuracao(db, escritorio_id)
    janelas = sorted(config.alerta_dias_lista, reverse=True)
    contadores = {"expiradas": 0, "aceite_vencido": 0, "alertas": 0}

    autorizacoes = (
        db.query(Autorizacao)
        .filter(Autorizacao.escritorio_id == escritorio_id)
        .all()
    )
    for autorizacao in autorizacoes:
        if (
            autorizacao.situacao == StatusAutorizacao.ATIVA.value
            and autorizacao.data_validade
            and autorizacao.data_validade < referencia
        ):
            autorizacao.situacao = StatusAutorizacao.EXPIRADA.value
            contadores["expiradas"] += 1
            eventos.notificar(
                db,
                escritorio_id,
                chave=f"autorizacao:{autorizacao.id}:expirada",
                tipo="autorizacao_expirada",
                nivel="erro",
                titulo=f"Autorização expirada — {autorizacao.outorgante_nome or autorizacao.outorgante_documento}",
                detalhe=(
                    f"A autorização venceu em {autorizacao.data_validade:%d/%m/%Y}. "
                    "Uma nova outorga precisa ser feita para manter o acesso."
                ),
                empresa_id=autorizacao.empresa_id,
            )
            continue

        if (
            autorizacao.situacao
            in {StatusAutorizacao.EM_ANALISE.value, StatusAutorizacao.AGUARDANDO_ACEITE.value}
            and autorizacao.prazo_aceite_ate
            and autorizacao.prazo_aceite_ate < referencia
        ):
            autorizacao.situacao = StatusAutorizacao.CANCELADA.value
            autorizacao.ultimo_erro = (
                "Cancelada automaticamente: o prazo de 30 dias para o aceite do "
                "outorgado expirou sem validação."
            )
            contadores["aceite_vencido"] += 1
            eventos.notificar(
                db,
                escritorio_id,
                chave=f"autorizacao:{autorizacao.id}:aceite_vencido",
                tipo="aceite_vencido",
                nivel="erro",
                titulo=f"Aceite não realizado em 30 dias — {autorizacao.outorgante_nome or autorizacao.outorgante_documento}",
                detalhe=(
                    "A autorização foi cancelada pelo decurso do prazo. "
                    "É necessário refazer a outorga no portal."
                ),
                empresa_id=autorizacao.empresa_id,
            )
            continue

        if (
            autorizacao.situacao == StatusAutorizacao.ATIVA.value
            and autorizacao.data_validade
            and janelas
        ):
            faltam = (autorizacao.data_validade - referencia).days
            janela = next((dias for dias in janelas if faltam <= dias), None)
            if janela is not None and faltam >= 0:
                eventos.notificar(
                    db,
                    escritorio_id,
                    chave=f"autorizacao:{autorizacao.id}:vencendo:{janela}",
                    tipo="autorizacao_vencendo",
                    nivel="alerta",
                    titulo=(
                        f"Autorização vence em {faltam} dia(s) — "
                        f"{autorizacao.outorgante_nome or autorizacao.outorgante_documento}"
                    ),
                    detalhe=(
                        f"Validade até {autorizacao.data_validade:%d/%m/%Y}. "
                        "Renove antes do vencimento para não perder acesso ao e-CAC."
                    ),
                    empresa_id=autorizacao.empresa_id,
                )
                contadores["alertas"] += 1

    db.flush()
    return contadores


def limpar_integracoes_antigas(db: Session, *, dias: int = 90) -> int:
    """Histórico de execução de integração tem prazo; a trilha de job não."""
    corte = _agora() - timedelta(days=max(7, dias))
    antigos = (
        db.query(IntegracaoJob)
        .filter(IntegracaoJob.iniciado_em < corte)
        .all()
    )
    for registro in antigos:
        db.delete(registro)
    db.flush()
    return len(antigos)
