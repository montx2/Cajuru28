"""
Tasks de importação.

Todo o desenho desta fila gira em torno de uma coisa: o Ambiente Nacional
(SEFAZ) e o ADN (NFS-e) limitam *quem consulta o CNPJ*, não *quantas notas
você baixa*. Ignorar isso trava o CNPJ por 1 hora e é exatamente o erro que
derruba importadores comerciais. Aqui, portanto:

- um **lease** por empresa+tipo: nunca duas varreduras no mesmo CNPJ ao mesmo
  tempo (dois cursores avançando = consulta fora da sequência = cStat 656);
- o **cursor mora em `sincronizacoes_dfe`**, uma linha por empresa+tipo, e só
  anda para frente;
- **137/"nada novo"** ⇒ agenda a próxima consulta para depois da janela
  oficial (1h + margem);
- **656** ⇒ não é "erro": a execução vira `aguardando`, o bloqueio é
  registrado e a continuação é reagendada sozinha — com o `ultNSU` que o
  ambiente devolveu adotado, para voltar alinhado;
- **queda de ambiente (5xx/rede)** ⇒ retenta cedo, porque aí nenhuma cota foi
  gasta;
- intervalo de **2s entre páginas** e teto de páginas por varredura, como
  recomenda o sped-nfe;
- checkpoint a cada lote: o que já baixou está no banco, mesmo se o worker
  cair no meio da hora de bloqueio.

**Período (desde a v3.1).** A varredura na origem continua sendo por NSU —
a SEFAZ/ADN não aceita "me dê só agosto" —, mas a execução carrega o intervalo
que o operador pediu e só as notas **emitidas dentro dele** são gravadas. O que
vem de fora é descartado antes de virar linha no banco e arquivo em disco, e
contado em `documentos_fora_do_periodo` para a execução poder provar o que
deixou de fora. O cursor de NSU avança normalmente: descartar conteúdo nunca
faz o sistema reconsultar o mesmo NSU depois.
"""

import logging
import os
import time
from datetime import date, datetime, timezone

from cryptography.hazmat.primitives.serialization import pkcs12
from dateutil import parser as date_parser
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.core.money import valor_monetario
from app.core.tempo import tornar_data_hora_fiscal_consciente
from app.core.vault import decifrar_segredo
from app.db.session import SessionLocal
from app.models import (
    Certificado,
    DirecaoDocumento,
    DocumentoFiscal,
    Empresa,
    EventoFiscalPendente,
    ExecucaoImportacao,
    StatusDocumentoFiscal,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.services import batimento, fila, sincronizacao
from app.services.proveniencia import registrar_proveniencia
from app.services.importadores.manifestacao import ManifestacaoRecusada, manifestar_ciencia
from app.services.certificados import ler_pfx_protegido
from app.services.importadores.base import (
    AmbienteIndisponivel,
    ConsumoIndevido,
    DocumentoBaixado,
)
from app.services.importadores.eventos import EventoFiscal
from app.services.importadores import obter_importador
from app.services.mtls import sessao_mtls
from app.worker.celery_app import celery_app

log = logging.getLogger("notasflow.worker")

# Trava de segurança: no máximo N lotes (de até 50 documentos) por varredura.
# Vem do sped-nfe: "o LOOP deve ter um limite de iterações, por exemplo 50".
TAMANHO_MAXIMO_LOTE_POR_EXECUCAO = max(1, int(settings.max_lotes_por_execucao))

# Intervalo entre páginas. Recomendado explicitamente: "o tempo entre cada busca
# no LOOP deve ser de pelo menos 2 segundos".
ESPERA_ENTRE_LOTES = max(0.0, float(settings.espera_entre_lotes_segundos))


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _parse_data_emissao(valor: str | datetime | None) -> datetime:
    """
    Converte a data de emissão (string ISO do XML fiscal, datetime, ou vazio)
    para datetime timezone-aware. Fallback: agora em UTC — nunca deixa a
    gravação quebrar por um campo opcional malformado.
    """
    if isinstance(valor, datetime):
        return tornar_data_hora_fiscal_consciente(valor)
    if not valor or not str(valor).strip():
        return datetime.now(timezone.utc)
    try:
        dt = date_parser.isoparse(str(valor).strip())
        return tornar_data_hora_fiscal_consciente(dt)
    except (ValueError, TypeError, OverflowError):
        try:
            dt = date_parser.parse(str(valor).strip())
            return tornar_data_hora_fiscal_consciente(dt)
        except (ValueError, TypeError, OverflowError):
            return datetime.now(timezone.utc)


def _parse_data(valor: str | None) -> date | None:
    """Competência do XML para `date`. Nada de fuso: o que importa é o mês."""
    if not valor or not str(valor).strip():
        return None
    try:
        return date_parser.parse(str(valor).strip()).date()
    except (ValueError, TypeError, OverflowError):
        return None


@celery_app.task(name="importar_documentos", bind=True, max_retries=0)
def importar_documentos(
    self, empresa_id: int, tipo: str, execucao_id: int, tentativa: int = 0
) -> None:
    """
    Varredura completa de uma empresa+tipo, do último NSU conhecido até o
    maxNSU do ambiente, com checkpoint a cada lote.

    `tentativa` conta apenas retentativas de *queda de ambiente* (5xx/rede).
    Bloqueio por consumo indevido não usa contador: a regra oficial é esperar,
    então cada hora é uma tentativa nova e o processo continua sozinho até
    conseguir.
    """
    db = SessionLocal()
    estado = None
    travado = False
    tipo_doc = TipoDocumentoFiscal(tipo)

    try:
        execucao = db.get(ExecucaoImportacao, execucao_id)
        empresa = db.get(Empresa, empresa_id)
        if execucao is None or empresa is None:
            return
        if execucao.status == StatusExecucao.CONCLUIDA:
            # Redelivery do broker (acks_late) numa varredura que já terminou:
            # sair daqui é o que evita reconsultar a SEFAZ de graça.
            return
        if execucao.status == StatusExecucao.AGUARDANDO:
            # O ETA venceu e a task acordou: a linha deixa de parecer parada
            # enquanto o worker valida certificado/lease/janela.
            execucao.status = StatusExecucao.EM_ANDAMENTO
            execucao.bloqueado_ate = None
            execucao.mensagem_erro = None

        certificado = (
            db.query(Certificado)
            .filter(Certificado.empresa_id == empresa_id, Certificado.ativo.is_(True))
            .first()
        )
        if certificado is None:
            _marcar_erro(db, execucao, "Nenhum certificado ativo para esta empresa")
            return

        estado = sincronizacao.obter_estado(db, empresa_id, tipo_doc)
        if estado is None:
            _marcar_erro(db, execucao, "Estado de sincronização indisponível (banco?)")
            return
        travado = sincronizacao.travar(db, estado)
        db.commit()
        if not travado:
            log.info(
                "Empresa %s/%s já está sendo varrida por outra task; sem duplicar consulta.",
                empresa_id, tipo,
            )
            execucao.status = StatusExecucao.CONCLUIDA
            execucao.bloqueado_ate = None
            execucao.mensagem_erro = None
            execucao.aviso = _resumir_avisos(
                execucao.aviso,
                ["Consulta não duplicada: outra varredura deste CNPJ/tipo já estava em andamento."],
            )
            execucao.finalizado_em = _agora()
            db.commit()
            return

        # Batimento: a API usa isto (e o ping do broker) para dizer ao
        # operador se "tem alguém trabalhando" na primeira tela.
        batimento.registrar(db, "worker", f"importar_documentos {empresa_id}/{tipo}")

        # ---------------- janela de consumo ----------------
        if not getattr(execucao, "forcar", False):
            libertacao = sincronizacao.liberacao_para(db, empresa_id, tipo_doc)
            if not libertacao.pode:
                _aguardar_janela(db, estado, execucao, libertacao)
                return

        ultimo_nsu = _resolver_nsu_inicial(db, empresa_id, tipo_doc, execucao, estado)
        senha = decifrar_segredo(certificado.senha_cifrada)
        pfx_bytes = ler_pfx_protegido(certificado.arquivo_path)

        importador = obter_importador(tipo_doc)
        total_importado = execucao.documentos_importados or 0
        total_cancelados = execucao.documentos_cancelados or 0
        total_nao_reconhecidos = execucao.eventos_nao_reconhecidos or 0
        total_no_periodo = execucao.documentos_no_periodo or 0
        total_fora_do_periodo = execucao.documentos_fora_do_periodo or 0
        total_completados = 0
        periodo = fila_periodo(execucao)
        importou_alguma_coisa = False

        # Telemetria do A1: o centro de certificados mostra "última utilização"
        # e "último erro de autenticação". Abrir o .pfx com a senha É a
        # autenticação local (senha errada/certificado corrompido falham aqui,
        # antes de gastar qualquer chamada ao ambiente fiscal).
        try:
            pkcs12.load_key_and_certificates(pfx_bytes, senha.encode())
        except Exception as exc:  # noqa: BLE001
            certificado.ultimo_erro = f"Abertura do .pfx falhou: {str(exc)[:300]}"
            certificado.ultima_utilizacao_em = _agora()
            db.commit()
            raise
        certificado.ultima_utilizacao_em = _agora()
        certificado.ultimo_erro = None
        db.commit()

        with sessao_mtls(pfx_bytes, senha) as (cert_path, key_path):
            for pagina in range(TAMANHO_MAXIMO_LOTE_POR_EXECUCAO):
                if pagina:
                    time.sleep(ESPERA_ENTRE_LOTES)
                try:
                    lote = importador.buscar_lote(
                        cnpj=empresa.cnpj_cpf,
                        cert_path=cert_path,
                        key_path=key_path,
                        ultimo_nsu=ultimo_nsu,
                        uf=empresa.uf,
                    )
                except ConsumoIndevido as exc:
                    tratar_consumo_indevido(db, estado, execucao, exc)
                    return
                except AmbienteIndisponivel as exc:
                    tratar_ambiente_indisponivel(db, execucao, exc, tentativa)
                    return

                for doc in lote.documentos:
                    # XML completo de uma nota que estava só em resumo: promove
                    # sem olhar o período (a nota já é nossa).
                    if _promover_resumo(db, empresa_id, tipo_doc, doc):
                        total_completados += 1
                        continue
                    # O filtro que o operador pediu, aplicado ANTES de gravar:
                    # a distribuição entrega tudo que existe a partir do NSU,
                    # e guardar meses que ninguém pediu é o que inchava o
                    # acervo. A nota fora do intervalo é apenas contada.
                    if not _documento_no_periodo(doc, periodo):
                        total_fora_do_periodo += 1
                        continue
                    if _gravar_documento(db, empresa_id, tipo_doc, doc):
                        total_importado += 1
                        total_no_periodo += 1
                        importou_alguma_coisa = True
                        if _aplicar_eventos_pendentes(db, empresa_id, tipo_doc, doc.chave_acesso):
                            total_cancelados += 1

                for evento in lote.eventos:
                    resultado = _processar_evento(db, empresa_id, tipo_doc, evento)
                    if resultado == "aplicado":
                        total_cancelados += 1

                total_nao_reconhecidos += lote.eventos_nao_reconhecidos
                ultimo_nsu = lote.proximo_nsu

                sincronizacao.avançar_cursor(
                    db, estado, ultimo_nsu=lote.proximo_nsu, max_nsu=lote.max_nsu
                )
                execucao.ultimo_nsu = ultimo_nsu
                execucao.documentos_importados = total_importado
                execucao.documentos_cancelados = total_cancelados
                execucao.eventos_nao_reconhecidos = total_nao_reconhecidos
                execucao.documentos_no_periodo = total_no_periodo
                execucao.documentos_fora_do_periodo = total_fora_do_periodo
                if lote.erros:
                    execucao.aviso = _resumir_avisos(execucao.aviso, lote.erros)
                db.commit()  # checkpoint a cada lote — nada se perde numa queda

                if not lote.ha_mais_documentos:
                    break
            else:
                # Estourou o teto de páginas: continua do checkpoint na mesma
                # execução (não finge "concluída" com trabalho pela metade).
                fila_reagendar(db, execucao, _agora(), motivo="Continuação da varredura (teto de páginas).")
                return

        # ---------------- fim da varredura ----------------
        if sincronizacao.nunca_consultado(estado):
            # Nunca obtivemos `maxNSU` para esta empresa+tipo: não sabemos se
            # estamos em dia, logo NÃO cabe a espera de 1h. Era exatamente aqui
            # que a NF-e se enterrava: sem importar nada, caía no ramo de "em
            # dia", ganhava 1h de cooldown e nunca mais era consultada de fato.
            sincronizacao.marcar_consulta_ok(db, estado)
            execucao.aviso = _resumir_avisos(
                execucao.aviso,
                ["O ambiente ainda não informou o NSU máximo desta empresa/tipo. "
                 "Nada foi bloqueado: a próxima varredura tentará de novo."],
            )
        elif sincronizacao.esta_em_dia(estado) or not importou_alguma_coisa:
            # "ultNSU == maxNSU" é a definição oficial de "não há mais nada
            # agora" — e é o gatilho da espera de 1 hora.
            quando = sincronizacao.marcar_sem_novidade(db, estado)
            execucao.aviso = _resumir_avisos(
                execucao.aviso,
                [f"Em dia até o NSU {estado.ultimo_nsu}. Próxima consulta a partir de "
                 f"{quando:%d/%m/%Y %H:%M} (janela oficial de 1h do ambiente)."],
            )
        else:
            sincronizacao.marcar_consulta_ok(db, estado)

        if (estado.max_nsu and int(estado.ultimo_nsu or 0) < int(estado.max_nsu or 0)):
            sincronizacao.marcar_consulta_ok(db, estado)

        if total_completados:
            execucao.aviso = _resumir_avisos(
                execucao.aviso,
                [f"{total_completados} nota(s) que estavam só em resumo foram completadas com o XML integral."],
            )

        if total_fora_do_periodo:
            # Prova do recorte: sem esta linha o operador veria "500 documentos
            # distribuídos, 12 importados" e não saberia se perdeu algo.
            execucao.aviso = _resumir_avisos(
                execucao.aviso,
                [
                    f"{total_fora_do_periodo} documento(s) fora do período "
                    f"{periodo.rotulo()} foram ignorados (não entraram no acervo). "
                    "Para trazê-los, rode a importação com o período correspondente."
                ],
            )

        execucao.status = StatusExecucao.CONCLUIDA
        execucao.bloqueado_ate = None
        execucao.finalizado_em = _agora()
        db.commit()

    except Exception as exc:  # noqa: BLE001 — task de background: captura, registra, não derruba o worker
        log.exception("Importação %s/%s falhou", empresa_id, tipo)
        db.rollback()
        execucao = db.get(ExecucaoImportacao, execucao_id)
        _marcar_erro(db, execucao, str(exc))
    finally:
        if estado is not None and travado:
            try:
                sincronizacao.liberar(db, estado)
                db.commit()
            except Exception:  # noqa: BLE001 — liberar nunca pode esconder o erro real
                db.rollback()
        db.close()


# ---------------------------------------------------------------------------
# Tratamento dos dois "erros" que não são erro
# ---------------------------------------------------------------------------


def tratar_consumo_indevido(
    db, estado, execucao: ExecucaoImportacao, erro: ConsumoIndevido
) -> None:
    """
    cStat 656: o CNPJ está bloqueado e a regra oficial manda esperar a hora
    inteira — retentar antes zera o cronômetro do bloqueio.

    Duas coisas acontecem além de esperar:

    1. o `ultNSU`/`maxNSU` que veio *junto* na resposta é adotado. É o que
       destrava o caso "outro sistema consultou este CNPJ e o meu cursor ficou
       para trás", que é o motivo mais comum de gente presa em loop de 656;
    2. o que já tinha baixado fica commitado (checkpoint por lote), então a
       retomada continua exatamente de onde parou.
    """
    quando = sincronizacao.marcar_consumo_indevido(
        db,
        estado,
        motivo=f"cStat {erro.cstat}: {erro.motivo}",
        # Quando o ambiente informou o tempo exato (Retry-After do ADN), a
        # exceção já traz `bloqueio`; senão fica None e cai no cooldown de 1h.
        bloqueio=getattr(erro, "bloqueio", None),
    )
    if erro.ultimo_nsu:
        sincronizacao.realinhar_cursor(
            db, estado, ultimo_nsu=erro.ultimo_nsu, max_nsu=erro.max_nsu
        )
    db.commit()

    execucao.ultimo_nsu = estado.ultimo_nsu
    mensagem = (
        f"{erro.ambiente} bloqueou este CNPJ por consumo indevido (cStat {erro.cstat}): "
        f"{erro.motivo} "
        f"Nova tentativa automática em {quando:%d/%m/%Y às %H:%M}. "
        "Nada foi perdido: o que já baixou está gravado e a retomada continua do checkpoint."
    )
    if erro.motivo and "ultNSU" in erro.motivo:
        mensagem += " O cursor foi realinhado com o NSU informado pelo próprio ambiente."
    _marcar_aguardando(db, execucao, mensagem, quando)
    fila_reagendar(db, execucao, quando, motivo=mensagem)


def tratar_ambiente_indisponivel(
    db, execucao: ExecucaoImportacao, erro: AmbienteIndisponivel, tentativa: int
) -> None:
    """
    5xx/rede: nenhuma cota foi gasta, então a espera é curta e crescente.
    Depois do teto, vira erro visível — mas o agendador continua tentando
    sozinho nas próximas varreduras.
    """
    limite = max(1, int(settings.max_tentativas_transporte))
    if tentativa >= limite:
        _marcar_erro(
            db,
            execucao,
            f"Ambiente fiscal indisponível após {tentativa + 1} tentativas: {erro}",
        )
        return
    quando = _agora() + erro.tentativa_recomendada * (2**tentativa)
    _marcar_aguardando(
        db,
        execucao,
        f"SEFAZ/ADN indisponível. Tentativa {tentativa + 1} de {limite + 1}; "
        f"próxima em {quando:%H:%M}. ({str(erro)[:300]})",
        quando,
    )
    fila_reagendar(
        db,
        execucao,
        quando,
        motivo="Ambiente fiscal indisponível — retentando.",
        tentativa=tentativa + 1,
    )


def _aguardar_janela(db, estado, execucao: ExecucaoImportacao, libertacao) -> None:
    """Disparamos uma varredura dentro da janela de espera: reagenda e sai."""
    _marcar_aguardando(
        db,
        execucao,
        (
            f"Janela de consumo do ambiente aberta em {libertacao.quando:%d/%m/%Y às %H:%M}. "
            + (f"{libertacao.motivo} " if libertacao.motivo else "")
            + "Nova tentativa automática já está agendada."
        ),
        libertacao.quando,
    )
    fila_reagendar(db, execucao, libertacao.quando, motivo="Aguardando janela de consumo.")


def _marcar_aguardando(
    db, execucao: ExecucaoImportacao, mensagem: str, quando: datetime
) -> None:
    execucao.status = StatusExecucao.AGUARDANDO
    execucao.bloqueado_ate = quando
    execucao.tentativas = (execucao.tentativas or 0) + 1
    execucao.mensagem_erro = mensagem[:4000]
    execucao.finalizado_em = None
    db.commit()


def fila_reagendar(
    db, execucao: ExecucaoImportacao, quando: datetime, *, motivo: str, tentativa: int | None = None
) -> bool:
    """Delegado para `app.services.fila.reagendar` (mesmo caminho do Beat)."""
    return fila.reagendar(db, execucao, quando, motivo=motivo, tentativa=tentativa)


def fila_periodo(execucao: ExecucaoImportacao):
    from app.services.periodo import Periodo

    return Periodo(inicio=execucao.data_inicio, fim=execucao.data_fim)


def _documento_no_periodo(doc, periodo) -> bool:
    """
    A nota recém-baixada pertence ao período pedido?

    Critério: **data de emissão** — a mesma regra que as telas usam para
    filtrar (`app/services/referencia.py`), para o que foi importado em agosto
    ser exatamente o que aparece quando se filtra agosto.

    Dois cuidados deliberados:

    - período aberto (execução antiga, sem data gravada) aceita tudo, senão
      um reprocessamento apagaria o histórico de quem importava antes desta
      versão;
    - documento sem data legível é **mantido**. Descartar por falta de campo
      seria perder nota fiscal por um defeito de leiaute — o erro caro. Ela
      aparece na tela pelo que tiver de data e pode ser conferida à mão.
    """
    if periodo is None or not periodo.definido:
        return True
    quando = _parse_data(str(getattr(doc, "data_emissao", "") or ""))
    if quando is None:
        return True
    return periodo.contem(quando)


def _resolver_nsu_inicial(
    db, empresa_id: int, tipo: TipoDocumentoFiscal, execucao: ExecucaoImportacao, estado=None
) -> str:
    """
    Ponto de retomada: o cursor vive em `sincronizacoes_dfe`. Para bancos que
    ainda não têm estado (recém-migrado), cai no maior NSU do histórico — e só
    então em "0", que é o único valor que não briga com a sequência do ambiente.
    """
    if execucao.ultimo_nsu:
        return execucao.ultimo_nsu

    if estado is None:
        estado = sincronizacao.obter_estado(db, empresa_id, tipo, criar=False)
    if estado is not None and estado.ultimo_nsu:
        return estado.ultimo_nsu

    historico = (
        db.query(ExecucaoImportacao.ultimo_nsu)
        .filter(
            ExecucaoImportacao.empresa_id == empresa_id,
            ExecucaoImportacao.tipo == tipo,
            ExecucaoImportacao.id != execucao.id,
            ExecucaoImportacao.ultimo_nsu.isnot(None),
        )
        .all()
    )
    # Máximo **numérico** (ordenar como string colocaria "900" acima de "1000"
    # e mandaria a consulta para trás na sequência — o que a SEFAZ pune).
    maiores = [int("".join(c for c in nsu if c.isdigit()) or 0) for (nsu,) in historico]
    return str(max(maiores)) if maiores else "0"


def _normalizar_chave(chave: str | None) -> str:
    """A coluna tem 60 chars; chaves iguais após o corte colidem no unique."""
    if not chave:
        return ""
    return str(chave).strip()[:60]


def _inserir_documento_sem_duplicar(db, valores: dict) -> bool:
    """
    Insere um documento de forma atômica e retorna se uma linha foi criada.

    Consultar antes de inserir não é suficiente: dois workers podem consultar
    ao mesmo tempo, ambos concluírem que a chave não existe e um deles receber
    `psycopg2.errors.UniqueViolation`. O `ON CONFLICT DO NOTHING` deixa o
    próprio PostgreSQL arbitrar essa corrida sem abortar a importação.

    SQLite usa a mesma sintaxe para manter os testes locais fiéis ao banco de
    produção. A aplicação é suportada em PostgreSQL; outro dialeto recebe um
    erro explícito, em vez de voltar ao padrão inseguro de consulta + insert.
    """
    dialeto = db.get_bind().dialect.name
    tabela = DocumentoFiscal.__table__

    if dialeto == "postgresql":
        comando = postgresql_insert(tabela).values(**valores).on_conflict_do_nothing(
            constraint="uq_documento_por_empresa"
        )
    elif dialeto == "sqlite":
        comando = sqlite_insert(tabela).values(**valores).on_conflict_do_nothing(
            index_elements=("empresa_id", "chave_acesso")
        )
    else:
        raise RuntimeError(
            f"Banco não suportado para importação idempotente: {dialeto}. Use PostgreSQL."
        )

    resultado = db.execute(comando)
    return resultado.rowcount == 1


def _promover_resumo(db, empresa_id: int, tipo: TipoDocumentoFiscal, doc) -> bool:
    """
    Troca um `resumo` já gravado pelo XML completo que a distribuição entregou.

    Depois da Ciência da Operação o Ambiente Nacional envia o `procNFe` pelo
    próprio fluxo de NSU (sem gastar a cota do consChNFe). Como a chave já
    existe, o insert idempotente de `_gravar_documento` ignoraria o completo e o
    documento ficaria como resumo para sempre — por isso esta promoção roda
    ANTES do filtro de período e do insert.

    Retorna True quando um resumo foi completado.
    """
    if (getattr(doc, "leiaute", "") or "completo") != "completo":
        return False
    chave = _normalizar_chave(getattr(doc, "chave_acesso", None))
    if not chave:
        return False
    existente = (
        db.query(DocumentoFiscal)
        .filter(
            DocumentoFiscal.empresa_id == empresa_id,
            DocumentoFiscal.tipo == tipo,
            DocumentoFiscal.chave_acesso == chave,
            DocumentoFiscal.leiaute == "resumo",
        )
        .first()
    )
    if existente is None:
        return False
    _sobrescrever_xml(existente, doc)
    registrar_proveniencia(db, existente.id, "sefaz", str(doc.nsu))
    return True


def _gravar_documento(db, empresa_id: int, tipo: TipoDocumentoFiscal, doc) -> bool:
    """
    Persiste um documento de forma idempotente.

    A mesma nota pode voltar em uma consulta posterior ou chegar a workers em
    paralelo. A restrição `uq_documento_por_empresa` continua sendo a regra
    final, mas o insert atômico absorve o conflito e a task segue normalmente.
    Retorna True somente quando uma nota nova foi gravada.
    """
    chave = _normalizar_chave(getattr(doc, "chave_acesso", None))
    if not chave:
        return False

    pasta = os.path.join(settings.dados_dir, "xml", str(empresa_id), tipo.value)
    nome_seguro = "".join(c for c in chave if c.isalnum() or c in "-_") or f"nsu_{doc.nsu}"
    xml_path = os.path.join(pasta, f"{nome_seguro}.xml")
    direcao = doc.direcao if doc.direcao in ("tomada", "prestada") else "tomada"

    def texto(field: str, limite: int) -> str | None:
        valor = str(getattr(doc, field, "") or "").strip()
        return valor[:limite] or None

    valores = {
        "empresa_id": empresa_id,
        "tipo": tipo,
        "direcao": DirecaoDocumento(direcao),
        "chave_acesso": chave,
        "nsu": str(doc.nsu),
        "data_emissao": _parse_data_emissao(doc.data_emissao),
        "competencia": _parse_data(getattr(doc, "competencia", "")),
        "valor_total": valor_monetario(doc.valor_total),
        "xml_path": xml_path,
        "status": StatusDocumentoFiscal.NORMAL,
        "leiaute": getattr(doc, "leiaute", "completo") or "completo",
        "numero": texto("numero", 20),
        "serie": texto("serie", 10),
        "emitente_documento": texto("emitente_documento", 18),
        "emitente_nome": texto("emitente_nome", 255),
        "destinatario_documento": texto("destinatario_documento", 18),
        "destinatario_nome": texto("destinatario_nome", 255),
        "situacao": texto("status_autorizacao", 255),
        "origem": "adn" if tipo == TipoDocumentoFiscal.NFSE else "sefaz",
    }
    criado = _inserir_documento_sem_duplicar(db, valores)
    documento = (
        db.query(DocumentoFiscal)
        .filter(DocumentoFiscal.empresa_id == empresa_id, DocumentoFiscal.chave_acesso == chave)
        .first()
    )
    if documento is not None:
        # A nota é única, mas cada confirmação de origem fica rastreável. Não
        # muda o XML quando a mesma chave reaparece por outra fonte.
        registrar_proveniencia(db, documento.id, valores["origem"] or "desconhecida", str(doc.nsu))
    if not criado:
        return False

    # Só grava o XML depois de vencer a disputa no banco. Assim uma
    # reimportação não sobrescreve o arquivo já associado à nota existente.
    os.makedirs(pasta, exist_ok=True)
    with open(xml_path, "wb") as f:
        f.write(doc.xml)
    return True


def _processar_evento(
    db, empresa_id: int, tipo: TipoDocumentoFiscal, evento: EventoFiscal
) -> str:
    """
    Aplica um evento recebido na distribuição.

    Retorno:
    - "aplicado": cancelamento aplicado numa nota já gravada;
    - "pendente": cancelamento guardado (a nota ainda não chegou);
    - "duplicado": evento repetido, já tratado antes;
    - "ignorado": não é cancelamento (CC-e etc.) — apenas contabilizado.
    """
    if not evento.eh_cancelamento:
        return "ignorado"

    chave = _normalizar_chave(evento.chave_acesso)
    if not chave:
        # Cancelamento sem chave: não dá pra aplicar, mas não pode sumir.
        return "ignorado"

    documento = (
        db.query(DocumentoFiscal)
        .filter(
            DocumentoFiscal.empresa_id == empresa_id,
            DocumentoFiscal.tipo == tipo,
            DocumentoFiscal.chave_acesso == chave,
        )
        .first()
    )

    if documento is not None:
        if documento.status != StatusDocumentoFiscal.CANCELADA:
            documento.status = StatusDocumentoFiscal.CANCELADA
            documento.motivo_cancelamento = (evento.motivo or "Cancelamento")[:2000]
            documento.cancelado_em = _parse_data_evento(evento.data_evento)
            return "aplicado"
        return "duplicado"

    # A nota ainda não chegou (ordem de NSU não é garantida): guarda o
    # evento para aplicar automaticamente quando o documento for gravado.
    existente = (
        db.query(EventoFiscalPendente)
        .filter(
            EventoFiscalPendente.empresa_id == empresa_id,
            EventoFiscalPendente.tipo == tipo,
            EventoFiscalPendente.chave_acesso == chave,
            EventoFiscalPendente.tipo_evento == evento.tipo_evento,
        )
        .first()
    )
    if existente is not None:
        return "duplicado"

    db.add(
        EventoFiscalPendente(
            empresa_id=empresa_id,
            tipo=tipo,
            chave_acesso=chave,
            tipo_evento=evento.tipo_evento,
            nsu=str(evento.nsu or "0"),
            motivo=(evento.motivo or "Cancelamento")[:2000],
            data_evento=_parse_data_evento(evento.data_evento),
        )
    )
    return "pendente"


def _aplicar_eventos_pendentes(
    db, empresa_id: int, tipo: TipoDocumentoFiscal, chave: str
) -> bool:
    """
    Quando a nota chega, aplica os cancelamentos que ficaram pendentes.
    Retorna True se algum cancelamento foi aplicado agora.
    """
    chave = _normalizar_chave(chave)
    pendentes = (
        db.query(EventoFiscalPendente)
        .filter(
            EventoFiscalPendente.empresa_id == empresa_id,
            EventoFiscalPendente.tipo == tipo,
            EventoFiscalPendente.chave_acesso == chave,
            EventoFiscalPendente.tipo_evento == "cancelamento",
            EventoFiscalPendente.processado.is_(False),
        )
        .all()
    )
    if not pendentes:
        return False

    documento = (
        db.query(DocumentoFiscal)
        .filter(
            DocumentoFiscal.empresa_id == empresa_id,
            DocumentoFiscal.tipo == tipo,
            DocumentoFiscal.chave_acesso == chave,
        )
        .first()
    )
    if documento is None:
        return False

    aplicou = False
    for pendente in pendentes:
        pendente.processado = True
        pendente.documento_id = documento.id
        if documento.status != StatusDocumentoFiscal.CANCELADA:
            documento.status = StatusDocumentoFiscal.CANCELADA
            documento.motivo_cancelamento = pendente.motivo or "Cancelamento"
            documento.cancelado_em = pendente.data_evento or _agora()
            aplicou = True
    return aplicou


def _parse_data_evento(valor: str | None) -> datetime | None:
    if not valor or not str(valor).strip():
        return _agora()
    try:
        dt = date_parser.isoparse(str(valor).strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError, OverflowError):
        return _agora()


def _resumir_avisos(aviso_atual: str | None, novos: list[str], limite: int = 20) -> str:
    """Anexa itens ignorados ao aviso da execução, sem crescer sem limite."""
    itens = [a for a in (aviso_atual or "").split("\n") if a and not a.startswith("…")]
    for novo in novos:
        if novo not in itens:
            itens.append(novo)
    if len(itens) > limite:
        resto = len(itens) - limite
        itens = itens[:limite]
        itens.append(f"… e mais {resto} item(ns) ignorado(s) no total")
    return "\n".join(itens)


def _marcar_erro(db, execucao: ExecucaoImportacao | None, mensagem: str) -> None:
    if execucao is None:
        return
    execucao.status = StatusExecucao.ERRO
    execucao.mensagem_erro = mensagem[:4000] if mensagem else "Erro desconhecido"
    execucao.finalizado_em = _agora()
    db.commit()


# ---------------------------------------------------------------------------
# Agendador (Celery Beat): o "quase 100% automático" de verdade
# ---------------------------------------------------------------------------


@celery_app.task(name="sincronizar_tudo", bind=True, max_retries=0)
def sincronizar_tudo(self) -> dict:
    """
    Varredura do agendador: dispara o que estiver liberado e acorda o que
    estava dormindo. Nenhuma requisição é feita daqui — só decisão.

    Rodar isto a cada poucos minutos é o que torna o sistema autônomo: as
    janelas de consumo (1h por empresa+tipo depois de "nada novo") limitam o
    ritmo por conta própria, então o tick barato é justamente o design certo.
    """
    if not settings.sincronismo_automatico:
        return {"desativado": True}

    db = SessionLocal()
    resumo = {"enfileiradas": 0, "aguardando": 0, "ignoradas": 0, "retomadas": 0}
    try:
        # Batimento do agendador: esta task só roda periodicamente se o Celery
        # Beat estiver vivo. Sem sinal recente, a tela inicial avisa "o
        # agendador parou" — em vez de deixar o operador descobrir pela falta
        # de documentos novos.
        batimento.registrar(
            db, "agendador", f"tick de {settings.sincronismo_intervalo_minutos} min"
        )
        # 1) execuções dormindo cujo bloqueio venceu: retoma (backstop caso o
        #    refiro agendado se perca — restart de worker, broker, etc.)
        vencidas = (
            db.query(ExecucaoImportacao)
            .filter(
                ExecucaoImportacao.status == StatusExecucao.AGUARDANDO,
                ExecucaoImportacao.bloqueado_ate.isnot(None),
                ExecucaoImportacao.bloqueado_ate <= _agora(),
            )
            .limit(50)
            .all()
        )
        for execucao in vencidas:
            empresa = db.get(Empresa, execucao.empresa_id)
            if empresa is None:
                continue
            libertacao = sincronizacao.liberacao_para(db, empresa.id, execucao.tipo)
            if not libertacao.pode:
                # continua dormindo, só empurra o horário
                execucao.bloqueado_ate = libertacao.quando
                continue
            if fila.retomar(db, execucao):
                resumo["retomadas"] += 1
        db.commit()

        # 2) empresas em modo automático cuja janela está livre: enfileira UMA
        #    varredura por empresa+tipo, sempre pela mesma porta (fila.enfileirar),
        #    que respeita o cooldown de 1h. É isto que torna o sistema autônomo:
        #    sem depender de clique manual, ninguém reconsulta antes da hora e o
        #    cronômetro do 656 nunca é zerado. Quem está na janela vira
        #    "aguardando" (não é erro) e o próprio tick tenta de novo mais tarde.
        limite = max(1, int(settings.sincronismo_lote_empresas))
        for empresa, tipos in fila.disponiveis_para_sincronismo_automatico(db, limite=limite):
            for tipo in tipos:
                resultado = fila.enfileirar(db, empresa, tipo, origem="auto")
                if resultado.status == "enfileirada":
                    resumo["enfileiradas"] += 1
                elif resultado.status == "em_cooldown":
                    resumo["aguardando"] += 1
                else:
                    # em_andamento / sem_certificado / sem_uf / fila_indisponivel:
                    # nenhuma requisição foi feita; só não há o que disparar agora.
                    resumo["ignoradas"] += 1
        db.commit()

        if resumo["enfileiradas"] or resumo["retomadas"]:
            log.info("Agendador: %s", resumo)
        return resumo
    except Exception as exc:  # noqa: BLE001 — o tick do agendador nunca derruba o beat
        log.exception("Agendador falhou: %s", exc)
        db.rollback()
        return {"erro": str(exc)[:500], **resumo}
    finally:
        db.close()


def _pendentes_de_completar(db, empresa: Empresa, limite: int) -> list[DocumentoFiscal]:
    """
    NF-e que ainda estão em `resumo` e podem avançar nesta rodada.

    Rejeição definitiva (`manifestacao_erro`) e, em empresa sem manifestação
    automática, nota ainda não manifestada ficariam ocupando as `limite` vagas a
    cada rodada e barrariam todas as outras (head-of-line blocking).
    """
    consulta = db.query(DocumentoFiscal).filter(
        DocumentoFiscal.empresa_id == empresa.id,
        DocumentoFiscal.leiaute == "resumo",
        DocumentoFiscal.tipo == TipoDocumentoFiscal.NFE,
        DocumentoFiscal.manifestacao_erro.is_(None),
    )
    if not empresa.manifestar_automaticamente:
        consulta = consulta.filter(DocumentoFiscal.manifestado_em.isnot(None))
    return consulta.order_by(DocumentoFiscal.id.desc()).limit(limite).all()


@celery_app.task(name="completar_xmls_pendentes", bind=True, max_retries=0)
def completar_xmls_pendentes(self, empresa_id: int | None = None, limite: int | None = None) -> dict:
    """
    Busca o XML completo das notas que chegaram só em resumo (`resNFe`).

    Pelo leiaute oficial, enquanto o destinatário não se manifesta o Ambiente
    Nacional distribui o `resNFe`; o caminho suportado para obter o XML
    integral é a consulta pontual pela chave (`consChNFe`) — limitada a 20
    consultas/h por CNPJ. Por isso este task consome a cota aos poucos, respeita
    o lease da empresa e para imediatamente se vier 656.

    Roda sozinha no agendador; o botão "completar XML" da tela chama a mesma
    task para uma empresa só.
    """
    db = SessionLocal()
    resultado = {
        "completos": 0,
        "indisponiveis": 0,
        "sem_cota": 0,
        "aguardando_janela": 0,
        "empresas": 0,
        "manifestados": 0,
        "aguardando_manifestacao": 0,
        "manifestacao_recusada": 0,
    }
    limite_por_empresa = max(1, min(20, int(limite or settings.limite_consultas_pontuais_por_hora)))
    try:
        batimento.registrar(db, "worker", "completar_xmls_pendentes")
        consulta = db.query(Empresa).filter(Empresa.ativa.is_(True))
        if empresa_id is not None:
            consulta = consulta.filter(Empresa.id == empresa_id)
        empresas = consulta.order_by(Empresa.id).all()

        for empresa in empresas:
            documentos_pendentes = _pendentes_de_completar(db, empresa, limite_por_empresa)
            if not documentos_pendentes:
                continue
            resultado["empresas"] += 1

            certificado = (
                db.query(Certificado)
                .filter(Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True))
                .first()
            )
            if certificado is None:
                continue

            estado = sincronizacao.obter_estado(db, empresa.id, TipoDocumentoFiscal.NFE)
            if estado is None:
                continue
            liberacao = sincronizacao.liberacao_para(db, empresa.id, TipoDocumentoFiscal.NFE)
            if not liberacao.pode:
                resultado["aguardando_janela"] += len(documentos_pendentes)
                continue
            if not sincronizacao.travar(db, estado):
                db.commit()
                continue

            try:
                db.commit()
                # A task pode ter esperado pelo lease; revalida a janela antes
                # de chamar consChNFe. Sem este preflight, o botão "completar
                # XML" gastava cota pontual dentro da mesma 1h e reiniciava
                # bloqueios oficiais.
                liberacao = sincronizacao.liberacao_para(db, empresa.id, TipoDocumentoFiscal.NFE)
                if not liberacao.pode:
                    resultado["aguardando_janela"] += len(documentos_pendentes)
                    continue
                importador = obter_importador(TipoDocumentoFiscal.NFE)
                senha = decifrar_segredo(certificado.senha_cifrada)
                pfx_bytes = ler_pfx_protegido(certificado.arquivo_path)

                with sessao_mtls(pfx_bytes, senha) as (cert_path, key_path):
                    for documento in documentos_pendentes:
                        liberacao = sincronizacao.liberacao_para(db, empresa.id, TipoDocumentoFiscal.NFE)
                        if not liberacao.pode:
                            resultado["aguardando_janela"] += 1
                            break
                        disponivel = sincronizacao.cota_pontual_disponivel(db, estado)
                        if disponivel <= 0:
                            resultado["sem_cota"] += 1
                            break
                        # A distribuição só entrega `resNFe` enquanto a nota
                        # não é manifestada; sem a Ciência da Operação, o
                        # consChNFe abaixo volta vazio para sempre. Por isso
                        # manifestamos ANTES de gastar a cota pontual — mas
                        # somente nas empresas que optaram (ato jurídico).
                        if not documento.manifestado_em:
                            if not empresa.manifestar_automaticamente:
                                resultado["aguardando_manifestacao"] += 1
                                continue
                            try:
                                manifesto = manifestar_ciencia(
                                    chave=documento.chave_acesso,
                                    cnpj=empresa.cnpj_cpf,
                                    cert_path=cert_path,
                                    key_path=key_path,
                                    uf=empresa.uf,
                                )
                            except ManifestacaoRecusada as exc:
                                # Rejeição definitiva: repetir não muda nada.
                                # Guarda o motivo e segue para o próximo.
                                documento.manifestacao_erro = str(exc)[:500]
                                resultado["manifestacao_recusada"] += 1
                                db.commit()
                                continue
                            except AmbienteIndisponivel:
                                break
                            documento.manifestado_em = _agora()
                            documento.manifestacao_erro = None
                            if not manifesto.ja_estava_manifestada:
                                resultado["manifestados"] += 1
                            db.commit()

                        try:
                            completo = importador.buscar_por_chave(
                                cnpj=empresa.cnpj_cpf,
                                cert_path=cert_path,
                                key_path=key_path,
                                chave_acesso=documento.chave_acesso,
                                uf=empresa.uf,
                            )
                        except ConsumoIndevido as exc:
                            sincronizacao.consumir_cota_pontual(db, estado)
                            if exc.ultimo_nsu:
                                sincronizacao.realinhar_cursor(
                                    db, estado, ultimo_nsu=exc.ultimo_nsu, max_nsu=exc.max_nsu
                                )
                            sincronizacao.marcar_consumo_indevido(
                                db, estado, motivo=f"consChNFe: {exc.motivo}", bloqueio=getattr(exc, "bloqueio", None)
                            )
                            db.commit()
                            break
                        except AmbienteIndisponivel:
                            # 5xx/rede não consome a cota oficial; mantém a
                            # consulta pontual disponível para a próxima rodada.
                            break

                        sincronizacao.consumir_cota_pontual(db, estado)
                        if completo is None or not completo.xml:
                            resultado["indisponiveis"] += 1
                            db.commit()
                            continue

                        _sobrescrever_xml(documento, completo)
                        sincronizacao.marcar_consulta_ok(db, estado)
                        resultado["completos"] += 1
                        db.commit()
                        time.sleep(ESPERA_ENTRE_LOTES)
            finally:
                sincronizacao.liberar(db, estado)
                db.commit()

        return resultado
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("completar_xmls_pendentes falhou: %s", exc)
        return {"erro": str(exc)[:500], **resultado}
    finally:
        db.close()


def _sobrescrever_xml(documento: DocumentoFiscal, completo: DocumentoBaixado) -> None:
    """
    Substitui o resumo pelo XML completo, mantendo o mesmo caminho de arquivo.

    O arquivo é reescrito antes do commit: se o commit falhar, o XML na mão do
    usuário ainda é o resumo (o que o banco diz), nunca um documento órfão.
    """
    caminho = documento.xml_path
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "wb") as f:
        f.write(completo.xml)

    documento.leiaute = "completo"
    documento.valor_total = valor_monetario(completo.valor_total or documento.valor_total)
    if completo.data_emissao:
        documento.data_emissao = _parse_data_emissao(completo.data_emissao)
    competencia = _parse_data(completo.competencia)
    if competencia:
        documento.competencia = competencia
    if completo.numero:
        documento.numero = completo.numero[:20]
    if completo.serie:
        documento.serie = completo.serie[:10]
    if completo.emitente_nome:
        documento.emitente_nome = completo.emitente_nome[:255]


@celery_app.task(name="varrer_alertas_webhook", bind=True, max_retries=0)
def varrer_alertas_webhook(self) -> dict:
    """
    Envia os alertas abertos ao webhook externo (Slack/Discord/n8n/gateway).

    Roda no Beat a cada `ALERTA_WEBHOOK_INTERVALO_MINUTOS`. Sem URL
    configurada, não faz nada. Cada alerta respeita o nível mínimo e o
    cooldown de reenvio — ninguém recebe a mesma mensagem a cada 15 min.
    """
    from app.api.routers.alertas import computar_alertas
    from app.models import Escritorio
    from app.services import webhook as svc_webhook

    if not (settings.alerta_webhook_url or "").strip():
        return {"desativado": True}

    db = SessionLocal()
    resumo: dict = {"enviados": 0, "ignorados": 0, "erros": []}
    try:
        escritorios = [linha[0] for linha in db.query(Escritorio.id).all()]
        for escritorio_id in escritorios:
            for alerta in computar_alertas(db, escritorio_id):
                if not svc_webhook.nivel_vale(alerta.nivel, settings.alerta_webhook_min_nivel):
                    continue
                chave = f"webhook:{escritorio_id}:{alerta.id}"
                if svc_webhook.ja_enviado_recente(chave, settings.alerta_webhook_cooldown_minutos):
                    resumo["ignorados"] += 1
                    continue
                ok, detalhe = svc_webhook.disparar(
                    alerta.model_dump(), escritorio_id=escritorio_id
                )
                if ok:
                    resumo["enviados"] += 1
                    svc_webhook.marcar_enviado(chave, settings.alerta_webhook_cooldown_minutos)
                else:
                    resumo["erros"].append(detalhe[:200])
        if resumo["enviados"]:
            log.info("Webhook: %s", resumo)
        return resumo
    except Exception as exc:  # noqa: BLE001 — o tick nunca derruba o beat
        log.exception("Varredura de webhook falhou: %s", exc)
        resumo["erros"].append(str(exc)[:200])
        return resumo
    finally:
        db.close()


@celery_app.task(name="backup_agendado", bind=True, max_retries=0)
def backup_agendado(self) -> dict:
    """
    O backup das 03:00 — disparado pelo Beat, executado aqui.

    Roda no worker para não competir com requisições da UI, e usa o mesmo
    serviço do botão "Executar agora" da Saúde do sistema: um caminho só,
    testado do mesmo jeito.
    """
    from app.services import backup as svc_backup

    if not settings.backup_ativo:
        return {"desativado": True}

    db = SessionLocal()
    try:
        batimento.registrar(db, "worker", "backup_agendado")
        registro = svc_backup.executar_backup(db, tipo="agendado")
        return {
            "status": registro.status.value if hasattr(registro.status, "value") else str(registro.status),
            "caminho": registro.caminho,
            "erro": registro.erro,
        }
    finally:
        db.close()
