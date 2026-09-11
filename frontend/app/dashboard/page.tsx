"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { dataHora, moedaCompacta, numero, saudacao, tempoRelativo } from "@/lib/format";
import type {
  AlertasResposta,
  CentralExecucoes,
  PainelOperacional,
} from "@/lib/types";
import { Icone } from "@/components/icons";
import { useToast } from "@/components/Toast";
import { Esqueleto, EstadoVazio, KpiCard, SeloNivel, TituloSecao } from "@/components/ui";

/**
 * Painel — a primeira tela do operador.
 *
 * Não é um dashboard "executivo" de vaidade: cada bloco responde a uma
 * pergunta de trabalho, na ordem em que ela aparece no dia:
 *
 * 1. Está tudo funcionando?           → banner de status geral
 * 2. Preciso resolver algo?           → Precisa da sua atenção
 * 3. O que a máquina está fazendo?    → rodando agora / próximas janelas
 * 4. Quanto trabalho saiu disso?      → documentos de hoje
 */

const ROTULO_TIPO: Record<string, string> = { nfse: "NFS-e", nfe: "NFe", cte: "CT-e" };

const ROTULO_COMPONENTE: Record<string, string> = {
  api: "API",
  banco: "Banco",
  fila: "Fila",
  worker: "Worker",
  agendador: "Agendador",
};

function BannerStatus({ painel }: { painel: PainelOperacional }) {
  const mapa = {
    operando: {
      cor: "border-accent/30 bg-accent-soft",
      ponto: "bg-accent",
      icone: "checkCirculo",
      iconeCor: "text-accent-deep",
    },
    atencao: {
      cor: "border-warn/30 bg-warn-soft",
      ponto: "bg-warn",
      icone: "alerta",
      iconeCor: "text-warn",
    },
    critico: {
      cor: "border-danger/30 bg-danger-soft",
      ponto: "bg-danger",
      icone: "xCirculo",
      iconeCor: "text-danger",
    },
  } as const;
  const visual = mapa[(painel.status_geral as keyof typeof mapa) ?? "atencao"] ?? mapa.atencao;

  return (
    <div className={`card flex flex-wrap items-center gap-4 border ${visual.cor}`}>
      <span className={`inline-flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-surface ${visual.iconeCor}`}>
        <Icone nome={visual.icone} className="h-6 w-6" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 font-serif text-lg font-semibold text-ink">
          <span className={`inline-block h-2.5 w-2.5 rounded-full ${visual.ponto}`} />
          {painel.status_geral === "operando"
            ? "Está tudo funcionando"
            : painel.status_geral === "atencao"
              ? "Funcionando, com pendências"
              : "Precisa de você agora"}
        </p>
        <p className="mt-0.5 text-sm text-ink-muted">{painel.mensagem}</p>
      </div>
      {painel.alertas.criticos + painel.alertas.atencao > 0 && (
        <Link href="/dashboard/atencao" className="btn-primary btn-sm no-print">
          Ver o que preciso resolver
        </Link>
      )}
    </div>
  );
}

function CardAtencao({ alertas }: { alertas: AlertasResposta | null }) {
  const itens = (alertas?.itens ?? []).slice(0, 5);
  const resto = Math.max(0, (alertas?.total ?? 0) - itens.length);

  if (!alertas) return <Esqueleto className="h-64" />;

  if (itens.length === 0) {
    return (
      <div className="card card-pad">
        <TituloSecao titulo="Precisa da sua atenção" />
        <div className="flex items-center gap-3 rounded-card bg-accent-soft px-4 py-5">
          <Icone nome="checkCirculo" className="h-8 w-8 flex-none text-accent-deep" />
          <div>
            <p className="font-semibold text-ink">Nada exigindo ação</p>
            <p className="text-sm text-ink-muted">
              A automação está cuidando de tudo — só voltamos a te avisar quando
              houver algo real.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card card-pad">
      <TituloSecao
        titulo="Precisa da sua atenção"
        subtitulo={`${alertas.criticos} crítico(s) · ${alertas.atencao} atenção · ${alertas.infos} info`}
        acao={
          <Link href="/dashboard/atencao" className="link text-xs font-semibold">
            ver tudo →
          </Link>
        }
      />
      <ul className="divide-y divide-line/70">
        {itens.map((a) => (
          <li key={a.id} className="py-2.5 first:pt-0 last:pb-0">
            <Link
              href={a.acao_href ?? "/dashboard/atencao"}
              className="group -mx-2 flex items-start gap-3 rounded-lg px-2 py-1.5 hover:bg-bg"
            >
              <span className="mt-0.5 flex-none">
                <SeloNivel nivel={a.nivel} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-ink">{a.titulo}</span>
                <span className="mt-0.5 line-clamp-1 block text-xs text-ink-muted">{a.detalhe}</span>
              </span>
              {a.acao_rotulo && (
                <span className="btn-ghost btn-sm flex-none opacity-0 transition-opacity group-hover:opacity-100">
                  {a.acao_rotulo}
                </span>
              )}
            </Link>
          </li>
        ))}
      </ul>
      {resto > 0 && (
        <p className="mt-3 text-xs text-ink-faint">+ {resto} outro(s) na lista completa</p>
      )}
    </div>
  );
}

function CardAgora({ execucoes }: { execucoes: CentralExecucoes | null }) {
  if (!execucoes) return <Esqueleto className="h-64" />;

  const vivas = execucoes.agora;
  const proximas = execucoes.proximas.slice(0, 5);

  if (vivas.length === 0 && proximas.length === 0) {
    return (
      <div className="card card-pad">
        <TituloSecao
          titulo="O que está rodando agora"
          acao={
            <Link href="/dashboard/execucoes" className="link text-xs font-semibold">
              central →
            </Link>
          }
        />
        <EstadoVazio
          icone="atividade"
          titulo="Nenhuma varredura em curso"
          texto="O agendador dispara cada empresa dentro da janela oficial de consumo — quando chegar a hora, aparece aqui."
        />
      </div>
    );
  }

  return (
    <div className="card card-pad">
      <TituloSecao
        titulo="O que está rodando agora"
        subtitulo={vivas.length > 0 ? `${vivas.length} varredura(s) em curso` : undefined}
        acao={
          <Link href="/dashboard/execucoes" className="link text-xs font-semibold">
            central →
          </Link>
        }
      />
      <ul className="space-y-2">
        {vivas.map((e) => (
          <li
            key={e.execucao_id}
            className="flex items-center gap-3 rounded-lg border border-line bg-bg px-3 py-2"
          >
            <span className="pulso-andamento inline-block h-2 w-2 flex-none rounded-full bg-info" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-ink">
                {e.razao_social}
                <span className="ml-1.5 font-normal text-ink-faint">{ROTULO_TIPO[e.tipo] ?? e.tipo}</span>
              </span>
              <span className="block text-xs text-ink-muted">
                {e.status === "aguardando"
                  ? `Aguardando janela${e.aguardando_ate ? ` até ${tempoRelativo(e.aguardando_ate)}` : ""}`
                  : `Consultando · ${numero(e.documentos_importados)} documento(s) · desde ${tempoRelativo(e.iniciado_em)}`}
              </span>
            </span>
            <Icone nome="raio" className="h-4 w-4 flex-none text-info" />
          </li>
        ))}
      </ul>
      {proximas.length > 0 && (
        <div className="mt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-faint">
            Próximas janelas
          </p>
          <ul className="space-y-1.5">
            {proximas.map((p) => (
              <li
                key={`${p.empresa_id}-${p.tipo}`}
                className="flex items-center justify-between gap-3 text-sm"
              >
                <span className="min-w-0 flex-1 truncate text-ink-muted">
                  {p.razao_social}
                  <span className="ml-1.5 text-ink-faint">{ROTULO_TIPO[p.tipo] ?? p.tipo}</span>
                  {p.pendencia > 0 && (
                    <span className="ml-1.5 rounded-pill bg-warn-soft px-1.5 py-px font-mono text-[10px] font-bold text-warn">
                      {numero(p.pendencia)} pendente(s)
                    </span>
                  )}
                </span>
                <span className="flex-none font-mono text-xs text-ink-faint">
                  {tempoRelativo(p.proxima_consulta_em)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function CardComponentes({ painel }: { painel: PainelOperacional }) {
  const COR: Record<string, string> = {
    ok: "bg-accent-soft text-accent-deep",
    atencao: "bg-warn-soft text-warn",
    erro: "bg-danger-soft text-danger",
    desconhecido: "bg-bg text-ink-faint",
    desligado: "bg-bg text-ink-faint",
  };
  const ICONE: Record<string, string> = {
    ok: "checkCirculo",
    atencao: "alerta",
    erro: "xCirculo",
    desconhecido: "info",
    desligado: "relogio",
  };

  return (
    <div className="card card-pad">
      <TituloSecao
        titulo="Máquina"
        subtitulo="Componentes de fundo"
        acao={
          <Link href="/dashboard/saude" className="link text-xs font-semibold">
            saúde →
          </Link>
        }
      />
      <ul className="space-y-2">
        {painel.componentes.map((c) => (
          <li key={c.nome} className="flex items-center gap-3">
            <span
              className={`inline-flex h-7 w-7 flex-none items-center justify-center rounded-lg ${
                COR[c.status] ?? COR.desconhecido
              }`}
            >
              <Icone nome={ICONE[c.status] ?? "info"} className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-medium text-ink">
                {ROTULO_COMPONENTE[c.nome] ?? c.nome}
              </span>
              <span className="block truncate text-xs text-ink-muted">{c.detalhe}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CardUltimas({ painel }: { painel: PainelOperacional }) {
  const ultimas = painel.ultimas_sincronizacoes;

  if (ultimas.length === 0) {
    return (
      <div className="card card-pad">
        <TituloSecao titulo="Últimas sincronizações" />
        <p className="py-6 text-center text-sm text-ink-muted">
          Nenhuma varredura registrada ainda — cadastre uma empresa com certificado
          e a automação começa a trabalhar.
        </p>
      </div>
    );
  }

  const visual: Record<string, { icone: string; cor: string }> = {
    concluida: { icone: "checkCirculo", cor: "text-accent" },
    erro: { icone: "xCirculo", cor: "text-danger" },
    aguardando: { icone: "relogio", cor: "text-warn" },
    em_andamento: { icone: "raio", cor: "text-info" },
  };

  return (
    <div className="card card-pad">
      <TituloSecao
        titulo="Últimas sincronizações"
        acao={
          <Link href="/dashboard/execucoes" className="link text-xs font-semibold">
            histórico →
          </Link>
        }
      />
      <ul className="divide-y divide-line/70">
        {ultimas.map((u, i) => {
          const v = visual[u.status] ?? visual.em_andamento;
          return (
            <li key={`${u.empresa_id}-${u.tipo}-${i}`} className="flex items-center gap-3 py-2 first:pt-0">
              <Icone nome={v.icone} className={`h-4 w-4 flex-none ${v.cor}`} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm text-ink">
                  {u.razao_social}
                  <span className="ml-1.5 text-xs text-ink-faint">{ROTULO_TIPO[u.tipo] ?? u.tipo}</span>
                </span>
                <span className="block truncate text-xs text-ink-muted">
                  {u.status === "erro"
                    ? u.mensagem_erro ?? "Falhou"
                    : u.status === "concluida"
                      ? `${numero(u.documentos)} documento(s) · ${dataHora(u.finalizado_em)}`
                      : u.aviso ?? "Aguardando janela"}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function PainelPage() {
  const toast = useToast();
  const [painel, setPainel] = useState<PainelOperacional | null>(null);
  const [execucoes, setExecucoes] = useState<CentralExecucoes | null>(null);
  const [alertas, setAlertas] = useState<AlertasResposta | null>(null);
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(
    async (silencioso = false) => {
      if (!silencioso) setCarregando(true);
      try {
        const [p, e, a] = await Promise.all([
          api.painelOperacional(),
          api.centralExecucoes(10),
          api.alertas(),
        ]);
        setPainel(p);
        setExecucoes(e);
        setAlertas(a);
      } catch {
        if (!silencioso) toast.erro("Não foi possível carregar o painel.");
      } finally {
        setCarregando(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    carregar();
    const intervalo = setInterval(() => carregar(true), 30_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  const hora = new Date().toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  if (carregando || !painel) {
    return (
      <div className="space-y-4">
        <Esqueleto className="h-24" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, i) => (
            <Esqueleto key={i} className="h-32" />
          ))}
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Esqueleto className="h-64" />
          <Esqueleto className="h-64" />
        </div>
      </div>
    );
  }

  const { empresas, certificados, execucoes: exec, documentos } = painel;

  return (
    <div className="animate-fade-up space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="font-serif text-3xl font-semibold text-ink">{saudacao()}</h1>
          <p className="mt-1 text-sm capitalize text-ink-muted">{hora}</p>
        </div>
        <p className="text-xs text-ink-faint">atualiza a cada 30 s</p>
      </div>

      <BannerStatus painel={painel} />

      {/* KPIs operacionais — saúde da automação em uma linha */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <KpiCard
          icone="empresa"
          rotulo="Empresas ativas"
          valor={numero(empresas.ativas)}
          detalhe={`${empresas.sincronizadas_hoje} sincronizada(s) hoje`}
          href="/dashboard/empresas"
        />
        <KpiCard
          icone="raio"
          rotulo="Rodando agora"
          valor={numero(exec.em_andamento)}
          detalhe={`${exec.aguardando} aguardando janela`}
          tom={exec.em_andamento > 0 ? "info" : "padrao"}
          href="/dashboard/execucoes"
        />
        <KpiCard
          icone="xCirculo"
          rotulo="Erros 24 h"
          valor={numero(exec.erros_24h)}
          detalhe={exec.erros_24h > 0 ? `${empresas.com_erro_24h} empresa(s) afetada(s)` : "nenhum"}
          tom={exec.erros_24h > 0 ? "perigo" : "ok"}
          href="/dashboard/execucoes"
        />
        <KpiCard
          icone="escudo"
          rotulo="Certificados"
          valor={numero(certificados.vencidos + certificados.vencendo)}
          detalhe={`${certificados.vencidos} vencido(s) · ${certificados.vencendo} vencendo`}
          tom={
            certificados.vencidos > 0
              ? "perigo"
              : certificados.vencendo > 0
                ? "alerta"
                : "ok"
          }
          href="/dashboard/certificados"
        />
        <KpiCard
          icone="documento"
          rotulo="Documentos hoje"
          valor={numero(documentos.hoje)}
          detalhe={`${documentos.aguardando_xml_completo} aguardando XML completo`}
          href="/dashboard/documentos"
        />
        <KpiCard
          icone="relogio"
          rotulo="Tempo médio"
          valor={exec.duracao_media_minutos !== null ? `${exec.duracao_media_minutos} min` : "—"}
          detalhe={`${numero(exec.concluidas_hoje)} varredura(s) concluída(s) hoje`}
          href="/dashboard/execucoes"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <CardAtencao alertas={alertas} />
        <CardAgora execucoes={execucoes} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <CardUltimas painel={painel} />
        <div className="space-y-4">
          <CardComponentes painel={painel} />
          <div className="card card-pad">
            <TituloSecao
              titulo={`Competência ${documentos.competencia}`}
              subtitulo="Contexto do mês corrente"
              acao={
                <Link href="/dashboard/relatorios" className="link text-xs font-semibold">
                  fechamento →
                </Link>
              }
            />
            <div className="grid grid-cols-3 gap-3 text-center">
              <div>
                <p className="font-serif text-2xl font-semibold text-ink">{numero(documentos.mes)}</p>
                <p className="text-xs text-ink-muted">documentos</p>
              </div>
              <div>
                <p className="font-serif text-2xl font-semibold text-ink">
                  {moedaCompacta(documentos.valor_mes)}
                </p>
                <p className="text-xs text-ink-muted">valor total</p>
              </div>
              <div>
                <p className="font-serif text-2xl font-semibold text-ink">{numero(documentos.total)}</p>
                <p className="text-xs text-ink-muted">no acervo</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
