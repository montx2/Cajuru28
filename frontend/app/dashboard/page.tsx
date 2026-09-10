"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  formatarCnpjCpf,
  moeda,
  moedaCompacta,
  numero,
  saudacao,
  tempoRelativo,
} from "@/lib/format";
import type {
  AlertasResposta,
  EmpresaRanking,
  EmitenteTop,
  EvolucaoMensal,
  ExecucaoImportacao,
  KpisDashboard,
  TipoBreakdown,
} from "@/lib/types";
import { Icone } from "@/components/icons";
import { useToast } from "@/components/Toast";
import {
  BarraProgresso,
  Esqueleto,
  EstadoVazio,
  GraficoBarras,
  GraficoDonut,
  KpiCard,
  SeloNivel,
  TituloSecao,
} from "@/components/ui";

const CORES_TIPO = ["#1F6F54", "#C9A227", "#2F6FED"];
const CHAVE_ONBOARDING = "notasflow_onboarding_ok";

function iconeStatus(status: string): { icone: string; cor: string } {
  switch (status) {
    case "concluida":
      return { icone: "checkCirculo", cor: "text-accent" };
    case "erro":
      return { icone: "xCirculo", cor: "text-danger" };
    case "aguardando":
      return { icone: "relogio", cor: "text-warn" };
    default:
      return { icone: "raio", cor: "text-info" };
  }
}

export default function VisaoGeralPage() {
  const toast = useToast();
  const [kpis, setKpis] = useState<KpisDashboard | null>(null);
  const [evolucao, setEvolucao] = useState<EvolucaoMensal[]>([]);
  const [porTipo, setPorTipo] = useState<TipoBreakdown[]>([]);
  const [emitentes, setEmitentes] = useState<EmitenteTop[]>([]);
  const [ranking, setRanking] = useState<EmpresaRanking[]>([]);
  const [atividades, setAtividades] = useState<ExecucaoImportacao[]>([]);
  const [alertas, setAlertas] = useState<AlertasResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [onboardingOk, setOnboardingOk] = useState(true);

  useEffect(() => {
    try {
      setOnboardingOk(window.localStorage.getItem(CHAVE_ONBOARDING) === "1");
    } catch {
      setOnboardingOk(true);
    }
  }, []);

  const carregar = useCallback(async (silencioso = false) => {
    if (!silencioso) setCarregando(true);
    try {
      const [k, e, t, em, r, a, al] = await Promise.all([
        api.kpis(),
        api.evolucao(12),
        api.porTipo(),
        api.topEmitentes(undefined, 6),
        api.rankingEmpresas(undefined, 6),
        api.atividades(8),
        api.alertas(),
      ]);
      setKpis(k);
      setEvolucao(e);
      setPorTipo(t);
      setEmitentes(em);
      setRanking(r);
      setAtividades(a);
      setAlertas(al);
    } catch {
      if (!silencioso) toast.erro("Não foi possível carregar o painel.");
    } finally {
      setCarregando(false);
    }
  }, [toast]);

  useEffect(() => {
    carregar();
    const intervalo = setInterval(() => carregar(true), 30_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  const hoje = new Date().toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const mostrarOnboarding =
    !onboardingOk &&
    kpis !== null &&
    (kpis.empresas_total === 0 || kpis.documentos_total === 0 || kpis.empresas_sem_certificado > 0);

  const passoEmpresa = (kpis?.empresas_total ?? 0) > 0;
  const passoCert = passoEmpresa && (kpis?.empresas_sem_certificado ?? 0) === 0;
  const passoImport = (kpis?.documentos_total ?? 0) > 0;

  function dispensarOnboarding() {
    setOnboardingOk(true);
    try {
      window.localStorage.setItem(CHAVE_ONBOARDING, "1");
    } catch {}
  }

  const maxEmitente = Math.max(1, ...emitentes.map((e) => e.valor));
  const alertasTopo = (alertas?.itens ?? []).filter((a) => a.nivel !== "info").slice(0, 3);

  return (
    <div className="animate-fade-up">
      {/* cabeçalho */}
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ink-muted">{hoje}</p>
          <h1 className="mt-1 font-serif text-3xl font-semibold text-ink">
            {saudacao()} 👋
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            {kpis ? (
              <>
                <span className="font-semibold text-ink">{numero(kpis.documentos_mes)} notas</span>{" "}
                em {kpis.competencia} ·{" "}
                <span className="font-semibold text-accent-deep">{kpis.combinacoes_em_dia}</span> de{" "}
                {kpis.combinacoes_total} sincronismos em dia
              </>
            ) : (
              "Carregando os números…"
            )}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href="/dashboard/importacoes" className="btn-primary btn-sm">
            <Icone nome="importacao" className="h-4 w-4" /> Importar
          </Link>
          <Link href="/dashboard/relatorios" className="btn-ghost btn-sm">
            <Icone nome="grafico" className="h-4 w-4" /> Fechamento
          </Link>
          <button type="button" onClick={() => carregar()} className="btn-ghost btn-sm" title="Atualizar agora">
            <Icone nome="atualizar" className="h-4 w-4" />
          </button>
        </div>
      </div>

      {carregando && !kpis ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Esqueleto className="h-32" />
            <Esqueleto className="h-32" />
            <Esqueleto className="h-32" />
            <Esqueleto className="h-32" />
          </div>
          <Esqueleto className="h-64" />
        </div>
      ) : (
        <>
          {/* onboarding */}
          {mostrarOnboarding && (
            <section className="card-pad mb-6 border-accent/30 bg-gradient-to-r from-accent-soft/60 to-surface">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-serif text-lg font-semibold text-ink">Vamos colocar para rodar 🚀</p>
                  <p className="text-sm text-ink-muted">Três passos e o escritório se importa sozinho.</p>
                </div>
                <button type="button" onClick={dispensarOnboarding} className="btn-icon" aria-label="Dispensar">
                  <Icone nome="x" className="h-4 w-4" />
                </button>
              </div>
              <ol className="mt-4 grid gap-3 md:grid-cols-3">
                {[
                  {
                    ok: passoEmpresa,
                    titulo: "1. Cadastre as empresas",
                    texto: "Uma a uma ou em massa com os .pfx.",
                    href: "/dashboard/empresas",
                    cta: "Abrir empresas",
                  },
                  {
                    ok: passoCert,
                    titulo: "2. Envie os certificados A1",
                    texto: "Sem o .pfx a SEFAZ nem conversa.",
                    href: "/dashboard/empresas",
                    cta: "Enviar certificados",
                  },
                  {
                    ok: passoImport,
                    titulo: "3. Rode a primeira importação",
                    texto: "Depois o agendador assume sozinho.",
                    href: "/dashboard/importacoes",
                    cta: "Importar agora",
                  },
                ].map((p) => (
                  <li key={p.titulo} className={`rounded-xl border p-3 ${p.ok ? "border-accent/40 bg-accent-soft/50" : "border-line bg-surface"}`}>
                    <p className="flex items-center gap-2 text-sm font-semibold text-ink">
                      <span className={p.ok ? "text-accent" : "text-ink-faint"}>
                        <Icone nome={p.ok ? "checkCirculo" : "relogio"} className="h-4 w-4" />
                      </span>
                      {p.titulo}
                    </p>
                    <p className="mt-1 text-xs text-ink-muted">{p.texto}</p>
                    {!p.ok && (
                      <Link href={p.href} className="link mt-2 inline-block text-xs font-semibold">
                        {p.cta} →
                      </Link>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          )}

          {/* KPIs */}
          {kpis && (
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              <KpiCard
                rotulo={`Documentos em ${kpis.competencia}`}
                valor={numero(kpis.documentos_mes)}
                detalhe={`${numero(kpis.documentos_total)} no total`}
                icone="documento"
                tom="ok"
                href="/dashboard/documentos"
                variacao={kpis.variacao_pct}
              />
              <KpiCard
                rotulo="Valor líquido no mês"
                valor={moedaCompacta(kpis.valor_mes)}
                detalhe={`${kpis.canceladas_mes} cancelada(s) excluídas`}
                icone="moeda"
                tom="padrao"
                href="/dashboard/relatorios"
              />
              <KpiCard
                rotulo="Empresas em dia"
                valor={`${kpis.empresas_em_dia}/${kpis.empresas_total}`}
                detalhe={
                  kpis.bloqueadas_agora > 0
                    ? `${kpis.bloqueadas_agora} na janela da SEFAZ`
                    : kpis.em_andamento > 0
                      ? `${kpis.em_andamento} varrendo agora`
                      : "Nada pendente"
                }
                icone="checkCirculo"
                tom={kpis.bloqueadas_agora > 0 ? "alerta" : "ok"}
                href="/dashboard/importacoes"
              />
              <KpiCard
                rotulo="Certificados A1"
                valor={
                  kpis.certificados_vencidos > 0
                    ? `${kpis.certificados_vencidos} vencidos`
                    : kpis.certificados_vencendo > 0
                      ? `${kpis.certificados_vencendo} vencendo`
                      : "Em ordem"
                }
                detalhe={
                  kpis.empresas_sem_certificado > 0
                    ? `${kpis.empresas_sem_certificado} empresa(s) sem certificado`
                    : "Todos válidos"
                }
                icone="escudo"
                tom={kpis.certificados_vencidos > 0 ? "perigo" : kpis.certificados_vencendo > 0 || kpis.empresas_sem_certificado > 0 ? "alerta" : "ok"}
                href="/dashboard/configuracoes"
              />
            </div>
          )}

          {/* alertas críticos em destaque */}
          {alertasTopo.length > 0 && (
            <section className="mt-6 grid gap-3 md:grid-cols-3">
              {alertasTopo.map((a) => (
                <Link
                  key={a.id}
                  href={a.acao_href ?? "/dashboard/alertas"}
                  className={`card-pad card-hover block border-l-4 ${
                    a.nivel === "critico" ? "border-l-danger" : "border-l-warn"
                  }`}
                >
                  <SeloNivel nivel={a.nivel} />
                  <p className="mt-2 line-clamp-1 text-sm font-semibold text-ink">{a.titulo}</p>
                  <p className="mt-0.5 line-clamp-2 text-xs text-ink-muted">{a.detalhe}</p>
                </Link>
              ))}
            </section>
          )}

          {/* gráficos */}
          <div className="mt-6 grid gap-4 xl:grid-cols-3">
            <section className="card-pad xl:col-span-2">
              <TituloSecao
                titulo="Evolução dos últimos 12 meses"
                subtitulo="Documentos importados por competência"
                acao={
                  <Link href="/dashboard/relatorios" className="link text-xs font-semibold">
                    ver fechamento →
                  </Link>
                }
              />
              {evolucao.every((e) => e.total === 0) ? (
                <p className="py-8 text-center text-sm text-ink-muted">
                  Ainda sem documentos — rode a primeira importação para ver o gráfico ganhar vida.
                </p>
              ) : (
                <GraficoBarras
                  dados={evolucao.map((e) => ({
                    rotulo: e.rotulo,
                    valor: e.total,
                    titulo: `${e.rotulo}: ${numero(e.total)} notas · ${moeda(e.valor)}`,
                  }))}
                />
              )}
            </section>
            <section className="card-pad">
              <TituloSecao titulo="Por tipo" subtitulo="Todo o banco" />
              {porTipo.every((t) => t.total === 0) ? (
                <p className="py-8 text-center text-sm text-ink-muted">Sem documentos ainda.</p>
              ) : (
                <>
                  <GraficoDonut
                    fatias={porTipo.map((t, i) => ({ rotulo: t.rotulo, valor: t.total, cor: CORES_TIPO[i % CORES_TIPO.length] }))}
                    centro={numero(porTipo.reduce((s, t) => s + t.total, 0))}
                  />
                  <ul className="mt-4 space-y-1 border-t border-line pt-3">
                    {porTipo.map((t) => (
                      <li key={t.tipo} className="flex items-center justify-between text-xs">
                        <span className="text-ink-muted">{t.rotulo}</span>
                        <span className="font-mono text-ink">{moedaCompacta(t.valor)}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          </div>

          {/* ranking + emitentes + atividades */}
          <div className="mt-4 grid gap-4 xl:grid-cols-3">
            <section className="card-pad">
              <TituloSecao
                titulo="Empresas que mais movimentam"
                acao={
                  <Link href="/dashboard/empresas" className="link text-xs font-semibold">
                    todas →
                  </Link>
                }
              />
              {ranking.length === 0 ? (
                <p className="py-6 text-center text-sm text-ink-muted">Sem movimento ainda.</p>
              ) : (
                <ul className="space-y-3">
                  {ranking.map((e, i) => (
                    <li key={e.empresa_id}>
                      <Link
                        href={`/dashboard/empresa?id=${e.empresa_id}`}
                        className="group flex items-baseline gap-2"
                      >
                        <span className="font-mono text-xs text-ink-faint">{String(i + 1).padStart(2, "0")}</span>
                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink group-hover:underline">
                          {e.razao_social}
                        </span>
                        <span className="font-mono text-xs text-ink-muted">{numero(e.total)}</span>
                      </Link>
                      <div className="ml-7 mt-1">
                        <BarraProgresso valor={e.total} maximo={ranking[0]?.total ?? 1} />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card-pad">
              <TituloSecao titulo="Maiores emitentes" subtitulo="Notas tomadas · por valor" />
              {emitentes.length === 0 ? (
                <p className="py-6 text-center text-sm text-ink-muted">Sem notas tomadas ainda.</p>
              ) : (
                <ul className="space-y-3">
                  {emitentes.map((e) => (
                    <li key={`${e.documento}-${e.nome}`}>
                      <div className="flex items-baseline justify-between gap-2">
                        <span className="min-w-0 flex-1 truncate text-sm font-medium text-ink" title={e.nome ?? ""}>
                          {e.nome || formatarCnpjCpf(e.documento)}
                        </span>
                        <span className="font-mono text-xs text-ink">{moedaCompacta(e.valor)}</span>
                      </div>
                      <p className="font-mono text-[11px] text-ink-faint">
                        {e.documento ? formatarCnpjCpf(e.documento) : "—"} · {e.total} nota(s)
                      </p>
                      <div className="mt-1">
                        <BarraProgresso valor={e.valor} maximo={maxEmitente} cor="bg-gold" />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card-pad">
              <TituloSecao
                titulo="Atividade recente"
                subtitulo="O que o sistema andou fazendo"
                acao={
                  <Link href="/dashboard/importacoes" className="link text-xs font-semibold">
                    histórico →
                  </Link>
                }
              />
              {atividades.length === 0 ? (
                <EstadoVazio
                  icone="raio"
                  titulo="Nenhuma atividade ainda"
                  texto="As importações aparecem aqui assim que rodarem."
                />
              ) : (
                <ul className="space-y-1">
                  {atividades.map((a) => {
                    const st = iconeStatus(a.status);
                    return (
                      <li key={a.id}>
                        <Link
                          href={`/dashboard/importacoes?execucao=${a.id}`}
                          className="flex items-start gap-3 rounded-lg px-2 py-2 hover:bg-bg"
                        >
                          <span className={`mt-0.5 ${st.cor}`}>
                            <Icone nome={st.icone} className="h-4 w-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm text-ink">
                              {a.empresa_razao_social ?? `#${a.empresa_id}`} ·{" "}
                              <span className="uppercase">{a.tipo}</span>
                            </span>
                            <span className="block text-xs text-ink-muted">
                              {a.documentos_importados} nota(s)
                              {a.documentos_cancelados > 0 && ` · ${a.documentos_cancelados} cancelada(s)`} ·{" "}
                              {tempoRelativo(a.iniciado_em)}
                            </span>
                          </span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </div>

          {/* resumo rápido do mês */}
          {kpis && kpis.sem_xml_completo > 0 && (
            <p className="mt-4 rounded-card border border-warn/30 bg-warn-soft/60 px-4 py-3 text-sm text-ink">
              <span className="font-semibold text-warn">{numero(kpis.sem_xml_completo)} documento(s)</span>{" "}
              chegaram só em resumo e aguardam o XML completo (cota de 20/h por CNPJ).{" "}
              <Link href="/dashboard/documentos" className="link font-semibold">
                Ver documentos →
              </Link>
            </p>
          )}
        </>
      )}
    </div>
  );
}
