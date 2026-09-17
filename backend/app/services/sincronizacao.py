"""
Governador de consumo: a camada que decide *quando* se pode consultar.

Todo o resto do sistema sabe baixar nota. O que separa um importador que roda
para sempre de um que trava é respeitar as regras de uso dos ambientes:

| Regra (fonte oficial)                                   | Onde é aplicada aqui          |
| -------------------------------------------------------- | ----------------------------- |
| Depois de `cStat=137` (nada novo), aguardar 1 hora        | `marcar_sem_novidade()`       |
| `cStat=656` ⇒ bloqueado 1h; tentar antes zera a contagem | `marcar_consumo_indevido()`   |
| A próxima consulta tem que usar o `ultNSU` devolvido     | cursor único + realinhamento  |
| Máximo 50 documentos por lote, 2 s entre requisições     | `worker.tasks`                |
| `consChNFe`/`consNSU`: no máximo 20 consultas por hora   | `consumir_cota_pontual()`     |
| Dois clientes consultando o mesmo CNPJ brigam pela cota  | lease (`travar`/`liberar`)    |

O estado mora em `sincronizacoes_dfe` (uma linha por empresa+tipo). É
deliberadamente separado de `execucoes_importacao`: execução é *log*, e log
não deve ser a fonte da verdade de um cursor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import SincronizacaoDFe, TipoDocumentoFiscal

# Duração do lease de uma empresa+tipo. Tem que ser maior que o tempo normal de
# uma varredura e menor que "duas rodadas seguidas", senão o agendador fica
# travado para sempre por um worker que morreu no meio.
LEASE_MAXIMO = timedelta(minutes=25)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    if valor.tzinfo is None:
        # Alguns drivers devolvem "naive" mesmo com timezone=True; tudo aqui é
        # gravado com datetime.now(timezone.utc), então assumir UTC é correto.
        return valor.replace(tzinfo=timezone.utc)
    return valor


def cooldown_oficial() -> timedelta:
    """1h + margem, como manda a NT 2014.002 / manual do ADN."""
    return timedelta(hours=max(1, settings.cooldown_horas), minutes=settings.margem_cooldown_minutos)


@dataclass
class Liberacao:
    """Resposta de "posso consultar agora?" — com explicação para o operador."""

    pode: bool
    quando: datetime
    motivo: str | None = None
    bloqueado: bool = False

    @property
    def esperar_segundos(self) -> int:
        return max(0, int((self.quando - _agora()).total_seconds()))


def obter_estado(
    db: Session, empresa_id: int, tipo: TipoDocumentoFiscal, *, criar: bool = True
) -> SincronizacaoDFe | None:
    estado = db.scalars(
        select(SincronizacaoDFe).where(
            SincronizacaoDFe.empresa_id == empresa_id, SincronizacaoDFe.tipo == tipo
        )
    ).first()
    if estado is not None or not criar:
        return estado

    estado = SincronizacaoDFe(empresa_id=empresa_id, tipo=tipo, ultimo_nsu="0")
    db.add(estado)
    try:
        db.flush()
    except Exception:  # noqa: BLE001 — outra task criou o mesmo estado agora
        db.rollback()
        return db.scalars(
            select(SincronizacaoDFe).where(
                SincronizacaoDFe.empresa_id == empresa_id, SincronizacaoDFe.tipo == tipo
            )
        ).first()
    return estado


def liberacao_para(
    db: Session, empresa_id: int, tipo: TipoDocumentoFiscal, *, agora: datetime | None = None
) -> Liberacao:
    """
    Quando a empresa+tipo pode ser consultada de novo.

    Uma empresa sem histórico pode ser consultada imediatamente; uma que ouviu
    "nada novo" há 10 minutos só volta daqui a ~50; uma bloqueada com 656
    respeita o bloqueio inteiro.
    """
    agora = agora or _agora()
    estado = obter_estado(db, empresa_id, tipo, criar=False)
    if estado is None:
        return Liberacao(pode=True, quando=agora)

    bloqueado_ate = _aware(estado.bloqueado_ate)
    proxima = _aware(estado.proxima_consulta_em)
    janelas: list[tuple[datetime, str, bool]] = []
    if bloqueado_ate and bloqueado_ate > agora:
        janelas.append((bloqueado_ate, estado.motivo_bloqueio or "Bloqueado por consumo indevido", True))
    if proxima and proxima > agora:
        janelas.append((proxima, "Sem documentos novos na última consulta — o ambiente pede 1 hora de espera.", False))
    if janelas:
        quando, motivo, bloqueado = max(janelas, key=lambda item: item[0])
        return Liberacao(pode=False, quando=quando, motivo=motivo, bloqueado=bloqueado)

    return Liberacao(pode=True, quando=agora)


def avançar_cursor(
    db: Session,
    estado: SincronizacaoDFe,
    *,
    ultimo_nsu: str | None,
    max_nsu: str | None = None,
    agora: datetime | None = None,
) -> None:
    """
    Atualiza o cursor. **Nunca regride** — só o realinhamento explícito
    (`realinhar_cursor`) pode mudar o sentido, porque aí quem mandou foi a
    própria SEFAZ.
    """
    agora = agora or _agora()
    novo = _para_inteiro(ultimo_nsu)
    if novo is not None:
        atual = _para_inteiro(estado.ultimo_nsu) or 0
        if atual is None or novo > atual:
            estado.ultimo_nsu = str(novo)
    novo_max = _para_inteiro(max_nsu)
    if novo_max is not None:
        estado.max_nsu = str(novo_max)
    estado.ultima_consulta_em = agora
    estado.atualizado_em = agora


def realinhar_cursor(
    db: Session, estado: SincronizacaoDFe, *, ultimo_nsu: str, max_nsu: str | None = None
) -> bool:
    """
    Adota o `ultNSU`/`maxNSU` que o ambiente devolveu.

    Caso real: outro sistema (ou uma segunda janela do painel) consultou o
    mesmo CNPJ e o nosso cursor ficou para trás. Continuar de onde estávamos é
    "consultar fora da sequência" — regra de uso indevido. O ambiente mesmo diz
    qual é o certo; escutar é o que destrava o loop de 656.
    """
    mudou = False
    novo = _para_inteiro(ultimo_nsu)
    atual = _para_inteiro(estado.ultimo_nsu)
    if novo is not None and novo != atual:
        estado.ultimo_nsu = str(novo)
        mudou = True
    novo_max = _para_inteiro(max_nsu)
    if novo_max is not None:
        estado.max_nsu = str(novo_max)
    estado.atualizado_em = _agora()
    return mudou


def marcar_sem_novidade(db: Session, estado: SincronizacaoDFe, *, agora: datetime | None = None) -> datetime:
    """
    O ambiente respondeu "não há nada novo". A partir de agora, a próxima
    consulta desta empresa+tipo só depois do cooldown oficial.
    """
    agora = agora or _agora()
    quando = agora + cooldown_oficial()
    estado.proxima_consulta_em = quando
    # Se acabou de consultar e a resposta oficial foi 137, qualquer bloqueio
    # antigo já venceu; manter `bloqueado_ate` no passado fazia painéis e
    # prévias continuarem mostrando a empresa como bloqueada.
    estado.bloqueado_ate = None
    estado.motivo_bloqueio = None
    estado.bloqueios_seguidos = 0
    estado.atualizado_em = agora
    return quando


def marcar_consulta_ok(db: Session, estado: SincronizacaoDFe, *, agora: datetime | None = None) -> None:
    """Trouxe documento? Então existe fila de distribuição: não há motivo para esperar."""
    agora = agora or _agora()
    estado.proxima_consulta_em = None
    estado.bloqueado_ate = None
    estado.motivo_bloqueio = None
    estado.bloqueios_seguidos = 0
    estado.atualizado_em = agora


def marcar_consumo_indevido(
    db: Session,
    estado: SincronizacaoDFe,
    *,
    motivo: str,
    bloqueio: timedelta | None = None,
    agora: datetime | None = None,
) -> datetime:
    """
    Registramos o bloqueio e agendamos a volta **depois** dele.

    `bloqueios_seguidos` existe para o painel contar o caso em que o CNPJ está
    sendo consumido por outro sistema: ali a resposta certa é "use um único
    importador", não "insista".

    `bloqueio` é a duração exata quando o ambiente a informa (ex.: header
    `Retry-After` do ADN). Sem ela, cai no cooldown oficial de 1h + margem —
    que é o que a SEFAZ (NFe/CT-e) usa, já que ela nunca devolve o tempo.
    """
    agora = agora or _agora()
    espera = bloqueio if (bloqueio and bloqueio.total_seconds() > 0) else cooldown_oficial()
    quando = agora + espera
    estado.bloqueado_ate = quando
    estado.proxima_consulta_em = quando
    estado.motivo_bloqueio = (motivo or "")[:2000]
    estado.bloqueios_seguidos = (estado.bloqueios_seguidos or 0) + 1
    estado.atualizado_em = agora
    return quando


def limpar_bloqueio(db: Session, estado: SincronizacaoDFe, *, agora: datetime | None = None) -> None:
    agora = agora or _agora()
    estado.bloqueado_ate = None
    estado.motivo_bloqueio = None
    estado.bloqueios_seguidos = 0
    estado.proxima_consulta_em = None
    estado.atualizado_em = agora


# ---------------------------------------------------------------------------
# Cota de consultas pontuais (consChNFe / consNSU): 20 por hora por CNPJ
# ---------------------------------------------------------------------------


def cota_pontual_disponivel(
    db: Session, estado: SincronizacaoDFe, *, agora: datetime | None = None
) -> int:
    agora = agora or _agora()
    limite = max(1, settings.limite_consultas_pontuais_por_hora)
    inicio_janela = _aware(estado.janela_pontual_em)
    if inicio_janela is None or agora - inicio_janela >= timedelta(hours=1):
        return limite
    return max(0, limite - (estado.consultas_pontuais or 0))


def consumir_cota_pontual(db: Session, estado: SincronizacaoDFe, *, agora: datetime | None = None) -> None:
    agora = agora or _agora()
    inicio_janela = _aware(estado.janela_pontual_em)
    if inicio_janela is None or agora - inicio_janela >= timedelta(hours=1):
        estado.janela_pontual_em = agora
        estado.consultas_pontuais = 0
    estado.consultas_pontuais = (estado.consultas_pontuais or 0) + 1
    estado.atualizado_em = agora


# ---------------------------------------------------------------------------
# Lease por empresa+tipo — o antídoto contra "dois sistemas, um CNPJ"
# ---------------------------------------------------------------------------


def travar(db: Session, estado: SincronizacaoDFe, *, agora: datetime | None = None) -> bool:
    """
    Tenta assumir a empresa+tipo. Retorna False se outra task já está nela.

    A comparação e a escrita acontecem num único `UPDATE ... WHERE`, para que
    dois workers concorrentes não decidam ao mesmo tempo que "ninguém está
    usando". Duas varreduras simultâneas no mesmo CNPJ avançam cursores
    diferentes — exatamente o padrão que a SEFAZ pune com 656.
    """
    agora = agora or _agora()
    limite = agora - LEASE_MAXIMO
    resultado = db.execute(
        update(SincronizacaoDFe)
        .where(SincronizacaoDFe.id == estado.id)
        .where(
            (SincronizacaoDFe.travado_em.is_(None))
            | (SincronizacaoDFe.travado_em < limite)
        )
        .values(travado_em=agora, atualizado_em=agora)
        # `synchronize_session=False`: o SQLite devolve datetime "naive", e o
        # avaliador de identidade do SQLAlchemy quebra comparando naive × aware.
        # Mantemos o objeto em memória coerente logo abaixo.
        .execution_options(synchronize_session=False)
    )
    adquirido = resultado.rowcount == 1
    if adquirido:
        estado.travado_em = agora
    db.flush()
    return adquirido


def renovar_lease(db: Session, estado: SincronizacaoDFe, *, agora: datetime | None = None) -> None:
    estado.travado_em = agora or _agora()
    db.flush()


def liberar(db: Session, estado: SincronizacaoDFe, *, agora: datetime | None = None) -> None:
    estado.travado_em = None
    estado.atualizado_em = agora or _agora()
    db.flush()


def esta_travado(estado: SincronizacaoDFe, *, agora: datetime | None = None) -> bool:
    agora = agora or _agora()
    travado_em = _aware(estado.travado_em)
    return bool(travado_em and travado_em > agora - LEASE_MAXIMO)


def esta_em_dia(estado: SincronizacaoDFe) -> bool:
    """
    Definição oficial de "em dia": `ultNSU == maxNSU` (NT 2014.002). É o que o
    painel mostra como ✔ — sem precisar de clique nenhum.
    """
    ult = _para_inteiro(estado.ultimo_nsu)
    maximo = _para_inteiro(estado.max_nsu)
    if ult is None or maximo is None:
        return False
    return ult >= maximo


def pendencia_de_documentos(estado: SincronizacaoDFe) -> int:
    """Quantos NSUs ainda faltam varrer (0 quando está em dia ou desconhecido)."""
    ult = _para_inteiro(estado.ultimo_nsu)
    maximo = _para_inteiro(estado.max_nsu)
    if ult is None or maximo is None:
        return 0
    return max(0, maximo - ult)


def _para_inteiro(valor: str | int | None) -> int | None:
    if valor is None:
        return None
    digitos = "".join(c for c in str(valor) if c.isdigit())
    return int(digitos) if digitos else None
