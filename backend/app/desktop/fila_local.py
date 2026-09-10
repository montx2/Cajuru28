"""
Fila em processo: o Celery do modo desktop, sem Redis e sem broker.

Por que não usar Celery no programa instalado?

- o Celery precisa de um broker (Redis) — que precisaria ser **instalado e
  mantido em cada computador** do escritório, o oposto de "baixa o .exe e
  pronto";
- a fila existe para *desacoplar* o processo web do processo de trabalho, o que
  faz sentido em servidor e não em uma máquina que roda um painel para uma
  pessoa;
- o desenho desta aplicação já é seguro sem broker: o estado que importa
  (cursor de NSU, janela de consumo, lease, checkpoint) mora no **banco**, não
  na fila. Uma fila que morre não perde nota — só para de disparar até
  reiniciar.

O que este módulo implementa é o subconjunto exato da API do Celery que o
sistema usa (`@app.task`, `.delay()`, `.apply_async(countdown=...)`,
`conf.beat_schedule`), para que `app/worker/tasks.py` continue idêntico nos dois
modos. Trocar de volta para Celery + Redis é uma variável no `.env`
(`MODO_DESKTOP=false`).
"""

from __future__ import annotations

import heapq
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.desktop import caminhos

log = logging.getLogger("notasflow.fila")

ARQUIVO_AGENDA = "agenda.json"


def _agora() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(order=True)
class _Item:
    quando: float
    sequencia: int
    nome: str = field(compare=False, default="")
    kwargs: dict = field(compare=False, default_factory=dict)
    args: tuple = field(compare=False, default=())
    ao_terminar: Callable[[], None] | None = field(compare=False, default=None)


class _Conf:
    """
    `celery_app.conf` falso, com o mínimo que o código usa.

    `beat_schedule` é atribuído depois da criação do app (em
    `app/worker/celery_app.py`), então o agendador lê este atributo na hora de
    disparar — não na criação.
    """

    def __init__(self) -> None:
        self.beat_schedule: dict[str, dict[str, Any]] = {}
        self.timezone = "America/Sao_Paulo"
        self.enable_utc = True

    def update(self, **valores: Any) -> None:
        for chave, valor in valores.items():
            setattr(self, chave, valor)


class _Control:
    def __init__(self, fila: "MiniCelery") -> None:
        self._fila = fila

    def shutdown(self, **_kwargs: Any) -> None:  # assinatura do Celery
        self._fila.parar()


class TarefaLocal:
    """
    O objeto que substitui a `Task` do Celery.

    Guarda o nome (para o agendador achar pelo `beat_schedule`) e sabe se
    enfileirar (`delay`/`apply_async`) ou executar direto (`__call__`).
    """

    def __init__(self, fila: "MiniCelery", nome: str, func: Callable[..., Any], *, bind: bool) -> None:
        self.fila = fila
        self.name = nome
        self.func = func
        self.bind = bind
        self.__doc__ = func.__doc__
        self.__name__ = getattr(func, "__name__", nome)

    # -- API do Celery usada pelo projeto -----------------------------------
    def delay(self, *args: Any, **kwargs: Any) -> str:
        return self.fila.enfileirar(self.name, kwargs, countdown=0)

    def apply_async(
        self,
        args: tuple | list | None = None,
        kwargs: dict | None = None,
        countdown: float | None = None,
        eta: datetime | None = None,
        **_opcoes: Any,
    ) -> str:
        atraso = float(countdown or 0)
        if eta is not None and countdown is None:
            alvo = eta if eta.tzinfo else eta.replace(tzinfo=timezone.utc)
            atraso = max(0.0, (alvo - _agora()).total_seconds())
        return self.fila.enfileirar(self.name, dict(kwargs or {}), countdown=atraso, args=args)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Chamada direta (usada em teste e no botão 'rodar agora' do suporte)."""
        return self.fila.executar_agora(self.name, dict(kwargs), args=args)

    # -- execução interna ----------------------------------------------------
    def _executar(self, kwargs: dict, args: tuple | list | None = None) -> Any:
        posicionais = tuple(args or ())
        if self.bind:
            return self.func(self, *posicionais, **kwargs)
        return self.func(*posicionais, **kwargs)


class MiniCelery:
    """
    Fila + agendador em processo.

    Três peças, todas em threads daemon (o processo pode encerrar a qualquer
    momento sem travar o Windows esperando thread):

    - **executores**: N threads que tiram o próximo item vencido da fila;
    - **relógio** (equivalente ao `celery beat`): dispara o que estiver em
      `conf.beat_schedule` respeitando o intervalo, com o último disparo
      gravado em disco para o intervalo sobreviver a "fechou e abriu de novo";
    - **contadores**: o que está pendente/rodando, para a tela de Configurações
      conseguir mostrar "3 varreduras na fila" em vez de um spinner mudo.
    """

    def __init__(self, *, concorrencia: int = 4, intervalo_relogio: float = 15.0) -> None:
        self.conf = _Conf()
        self.control = _Control(self)
        self._tarefas: dict[str, TarefaLocal] = {}
        self._fila: list[_Item] = []
        self._cond = threading.Condition()
        self._sequencia = 0
        self._parado = threading.Event()
        self._concorrencia = max(1, int(concorrencia))
        self._intervalo_relogio = max(5.0, float(intervalo_relogio))
        self._threads: list[threading.Thread] = []
        self._em_execucao: dict[str, int] = {}
        self._ultimo_disparo: dict[str, datetime] = {}
        self._proximo_disparo: dict[str, datetime] = {}
        self._arquivo_agenda = caminhos.pasta_dados() / ARQUIVO_AGENDA
        self._iniciado = False

    # -- registro -----------------------------------------------------------
    def task(self, *args: Any, name: str | None = None, bind: bool = False, **_opcoes: Any):
        """
        Decorador com a mesma assinatura do Celery.

        Aceita `@app.task` e `@app.task(name="...", bind=True)` — que são as
        duas formas usadas no projeto.
        """

        def decorador(func: Callable[..., Any]) -> TarefaLocal:
            tarefa = TarefaLocal(self, name or getattr(func, "__name__", "tarefa"), func, bind=bind)
            self._tarefas[tarefa.name] = tarefa
            return tarefa

        if args and callable(args[0]) and len(args) == 1 and not isinstance(args[0], str):
            # Usado como @app.task "pelado", sem parênteses.
            return decorador(args[0])
        return decorador

    def registrar_tarefa(self, nome: str, func: Callable[..., Any], *, bind: bool = False) -> TarefaLocal:
        tarefa = TarefaLocal(self, nome, func, bind=bind)
        self._tarefas[nome] = tarefa
        return tarefa

    def obter_tarefa(self, nome: str) -> TarefaLocal | None:
        return self._tarefas.get(nome)

    # -- enfileiramento -----------------------------------------------------
    def enfileirar(
        self,
        nome: str,
        kwargs: dict | None = None,
        *,
        countdown: float = 0.0,
        args: tuple | list | None = None,
        ao_terminar: Callable[[], None] | None = None,
    ) -> str:
        if nome not in self._tarefas:
            raise KeyError(f"Tarefa desconhecida na fila local: {nome}")
        with self._cond:
            self._sequencia += 1
            identificador = f"local-{self._sequencia}"
            heapq.heappush(
                self._fila,
                _Item(
                    quando=time.monotonic() + max(0.0, float(countdown or 0)),
                    sequencia=self._sequencia,
                    nome=nome,
                    kwargs=dict(kwargs or {}),
                    args=tuple(args or ()),
                    ao_terminar=ao_terminar,
                ),
            )
            self._cond.notify_all()
        if countdown:
            log.info("Fila: %s agendada para daqui a %s s", nome, int(countdown))
        return identificador

    def executar_agora(self, nome: str, kwargs: dict | None = None, *, args: tuple | list | None = None) -> Any:
        """Executa uma tarefa na thread atual (sem passar pela fila)."""
        tarefa = self._tarefas.get(nome)
        if tarefa is None:
            raise KeyError(f"Tarefa desconhecida: {nome}")
        return tarefa._executar(dict(kwargs or {}), args)

    # -- ciclo de vida ------------------------------------------------------
    def iniciar(self) -> None:
        if self._iniciado:
            return
        self._iniciado = True
        self._carregar_agenda()
        for indice in range(self._concorrencia):
            t = threading.Thread(
                target=self._laco_executor, name=f"notasflow-worker-{indice}", daemon=True
            )
            t.start()
            self._threads.append(t)
        relogio = threading.Thread(target=self._laco_relogio, name="notasflow-relogio", daemon=True)
        relogio.start()
        self._threads.append(relogio)
        log.info(
            "Fila local iniciada: %s executor(es), %s tarefa(s) registrada(s)",
            self._concorrencia,
            len(self._tarefas),
        )

    def parar(self, tempo_limite: float = 10.0) -> None:
        self._parado.set()
        with self._cond:
            self._cond.notify_all()
        limite = time.monotonic() + tempo_limite
        for thread in self._threads:
            restante = max(0.1, limite - time.monotonic())
            thread.join(timeout=restante)

    # -- laços --------------------------------------------------------------
    def _proximo_vencido(self) -> _Item | None:
        """O próximo item já vencido (a heap está ordenada por horário). Chame com o lock."""
        if self._fila and self._fila[0].quando <= time.monotonic():
            return heapq.heappop(self._fila)
        return None

    def _laco_executor(self) -> None:
        while not self._parado.is_set():
            item: _Item | None = None
            with self._cond:
                item = self._proximo_vencido()
                if item is None:
                    espera = 1.0
                    if self._fila:
                        espera = max(0.05, min(1.0, self._fila[0].quando - time.monotonic()))
                    # Fora do `with`, o relógio também usa a condição: a espera
                    # com timeout deixa o despertar de qualquer um dos dois.
                    self._cond.wait(timeout=espera)
            if item is None:
                continue
            self._rodar(item)

    def _rodar(self, item: _Item) -> None:
        tarefa = self._tarefas.get(item.nome)
        if tarefa is None:
            log.warning("Fila: tarefa %s desapareceu antes de rodar", item.nome)
            return
        self._marcar_inicio(item.nome)
        inicio = time.monotonic()
        try:
            tarefa._executar(item.kwargs, item.args)
            log.info("Fila: %s concluída em %.1fs", item.nome, time.monotonic() - inicio)
        except Exception as exc:  # noqa: BLE001 — uma tarefa que estoura não pode derrubar o executor
            log.exception("Fila: %s falhou (%s)", item.nome, exc)
        finally:
            self._marcar_fim(item.nome)
            if item.ao_terminar is not None:
                try:
                    item.ao_terminar()
                except Exception:  # noqa: BLE001
                    log.exception("Fila: callback de fim de %s falhou", item.nome)

    def _marcar_inicio(self, nome: str) -> None:
        with self._cond:
            self._em_execucao[nome] = self._em_execucao.get(nome, 0) + 1

    def _marcar_fim(self, nome: str) -> None:
        with self._cond:
            self._em_execucao[nome] = max(0, self._em_execucao.get(nome, 1) - 1)

    def esta_em_execucao(self, nome: str) -> bool:
        with self._cond:
            return self._em_execucao.get(nome, 0) > 0

    # -- relógio (beat) -----------------------------------------------------
    def _laco_relogio(self) -> None:
        # Espera o servidor subir antes do primeiro tick: abrir o programa não
        # pode disparar consulta na SEFAZ antes da tela existir.
        atraso_inicial = float(getattr(self.conf, "atraso_inicial_segundos", 20) or 0)
        if self._parado.wait(timeout=atraso_inicial):
            return
        while not self._parado.is_set():
            for nome_entrada, entrada in list(self.conf.beat_schedule.items()):
                if self._parado.is_set():
                    return
                try:
                    self._talvez_disparar(nome_entrada, entrada)
                except Exception:  # noqa: BLE001 — o relógio nunca morre por causa de uma entrada
                    log.exception("Relógio: falha ao processar %s", nome_entrada)
            self._parado.wait(timeout=self._intervalo_relogio)

    def _talvez_disparar(self, nome_entrada: str, entrada: dict[str, Any]) -> None:
        nome_tarefa = str(entrada.get("task") or "").strip()
        if nome_tarefa not in self._tarefas:
            return

        intervalo = _segundos(entrada.get("schedule"))
        if intervalo <= 0:
            return

        agora = _agora()
        ultimo = self._ultimo_disparo.get(nome_entrada)
        if ultimo is None:
            ultimo = self._ler_agenda(nome_entrada)
        if ultimo is None:
            # Nunca rodou: o primeiro disparo é agora (o `atraso_inicial` do
            # relógio já deu tempo do banco e da tela subirem).
            self._disparar(nome_entrada, nome_tarefa, agora, intervalo)
            return
        if (agora - ultimo).total_seconds() >= intervalo:
            self._disparar(nome_entrada, nome_tarefa, agora, intervalo)
            return
        self._proximo_disparo[nome_entrada] = ultimo + timedelta(seconds=intervalo)

    def _disparar(
        self, nome_entrada: str, nome_tarefa: str, agora: datetime, intervalo: float
    ) -> None:
        if self.esta_em_execucao(nome_tarefa):
            # Tarefa de agenda ainda rodando (ex.: varredura longa): o próximo
            # tick espera. Empilhar a mesma sincronização não acelera nada —
            # quem manda no ritmo é a janela de consumo da SEFAZ.
            log.info("Relógio: %s já está rodando, pulando este tick", nome_tarefa)
            return

        def ao_terminar() -> None:
            with self._cond:
                self._cond.notify_all()

        self.enfileirar(nome_tarefa, {}, ao_terminar=ao_terminar)
        self._ultimo_disparo[nome_entrada] = agora
        self._proximo_disparo[nome_entrada] = agora + timedelta(seconds=intervalo)
        self._gravar_agenda(nome_entrada, agora)
        log.info("Relógio: %s disparada", nome_tarefa)

    # -- persistência da agenda --------------------------------------------
    def _ler_agenda(self, nome_entrada: str) -> datetime | None:
        try:
            dados = json.loads(self._arquivo_agenda.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        bruto = dados.get(nome_entrada)
        if not bruto:
            return None
        try:
            lido = datetime.fromisoformat(str(bruto))
        except ValueError:
            return None
        return lido if lido.tzinfo else lido.replace(tzinfo=timezone.utc)

    def _carregar_agenda(self) -> None:
        for nome_entrada, entrada in self.conf.beat_schedule.items():
            ultimo = self._ler_agenda(nome_entrada)
            if ultimo is not None:
                self._ultimo_disparo[nome_entrada] = ultimo
                intervalo = _segundos(entrada.get("schedule"))
                self._proximo_disparo[nome_entrada] = ultimo + timedelta(seconds=max(0, intervalo))

    def _gravar_agenda(self, nome_entrada: str, quando: datetime) -> None:
        dados: dict[str, str] = {}
        try:
            dados = json.loads(self._arquivo_agenda.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = {}
        dados[nome_entrada] = quando.isoformat()
        try:
            self._arquivo_agenda.write_text(json.dumps(dados, indent=2), encoding="utf-8")
        except OSError:
            log.warning("Não foi possível gravar a agenda em %s", self._arquivo_agenda)

    def esquecer_agenda(self) -> None:
        """Faz o próximo tick rodar agora (botão 'sincronizar agora' do suporte)."""
        self._ultimo_disparo.clear()

    # -- observabilidade ----------------------------------------------------
    def estatisticas(self) -> dict[str, Any]:
        with self._cond:
            pendentes = len(self._fila)
            em_execucao = {nome: qtd for nome, qtd in self._em_execucao.items() if qtd}
        return {
            "concorrencia": self._concorrencia,
            "pendentes": pendentes,
            "em_execucao": em_execucao,
            "agenda": {
                nome: {
                    "tarefa": entrada.get("task"),
                    "intervalo_segundos": _segundos(entrada.get("schedule")),
                    "proximo": (
                        self._proximo_disparo[nome].isoformat()
                        if nome in self._proximo_disparo
                        else None
                    ),
                }
                for nome, entrada in self.conf.beat_schedule.items()
            },
        }


def _segundos(agendamento: Any) -> float:
    """Aceita `timedelta` (o que o beat do Celery usa) ou segundos em número."""
    if agendamento is None:
        return 0.0
    if isinstance(agendamento, timedelta):
        return agendamento.total_seconds()
    try:
        return float(agendamento)
    except (TypeError, ValueError):
        return 0.0
