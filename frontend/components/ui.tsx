"use client";

import Link from "next/link";
import { Icone } from "./icons";

/**
 * Blocos visuais do painel: cartões de KPI, gráficos SVG sem dependências,
 * esqueletos de carregamento e estados vazios.
 */

export type Tom = "padrao" | "ok" | "alerta" | "perigo" | "info";

const COR_TOM: Record<Tom, string> = {
  padrao: "bg-bg text-ink",
  ok: "bg-accent-soft text-accent-deep",
  alerta: "bg-warn-soft text-warn",
  perigo: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
};

export function TituloSecao({
  titulo,
  subtitulo,
  acao,
}: {
  titulo: string;
  subtitulo?: string;
  acao?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="section-title">{titulo}</h2>
        {subtitulo && <p className="section-meta">{subtitulo}</p>}
      </div>
      {acao}
    </div>
  );
}

export function KpiCard({
  rotulo,
  valor,
  detalhe,
  icone,
  tom = "padrao",
  href,
  variacao,
}: {
  rotulo: string;
  valor: string;
  detalhe?: string;
  icone: string;
  tom?: Tom;
  href?: string;
  /** ex.: +12,4 (em %) — verde se positivo, vermelho se negativo */
  variacao?: number | null;
}) {
  const conteudo = (
    <>
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[.13em] text-ink-muted">{rotulo}</p>
          <p className="mt-3 font-display text-[1.9rem] font-semibold leading-none tracking-tight tabular-nums text-ink">{valor}</p>
        </div>
        <span className={`inline-flex h-9 w-9 items-center justify-center rounded-[10px] ${COR_TOM[tom]}`}>
          <Icone nome={icone} className="h-[18px] w-[18px]" />
        </span>
      </div>
      <div className="mt-4 flex min-h-5 items-center justify-between gap-2 border-t border-line/70 pt-3">
        {detalhe ? <p className="text-xs leading-5 text-ink-faint">{detalhe}</p> : <span />}
        {variacao !== undefined && variacao !== null && (
          <span className={`flex-none rounded-pill px-2 py-1 font-mono text-xs font-semibold ${variacao >= 0 ? "bg-accent-soft text-accent-deep" : "bg-danger-soft text-danger"}`}>
            {variacao >= 0 ? "▲" : "▼"} {Math.abs(variacao).toLocaleString("pt-BR")}%
          </span>
        )}
        {href && <Icone nome="setaDireita" className="h-3.5 w-3.5 flex-none text-ink-faint transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-accent" />}
      </div>
    </>
  );
  const classe = `card card-hover group block min-h-[142px] p-5 text-left ${href ? "cursor-pointer" : ""}`;
  if (href) {
    return (
      <Link href={href} className={classe}>
        {conteudo}
      </Link>
    );
  }
  return <div className={classe}>{conteudo}</div>;
}

/** Barras mensais em SVG puro — sem biblioteca de gráficos. */
export function GraficoBarras({
  dados,
  altura = 160,
}: {
  dados: { rotulo: string; valor: number; titulo?: string }[];
  altura?: number;
}) {
  const maximo = Math.max(1, ...dados.map((d) => d.valor));
  const ultimo = dados.length - 1;
  return (
    <div>
      <div className="flex items-end gap-1.5" style={{ height: altura }}>
        {dados.map((d, i) => {
          const h = Math.max(3, Math.round((d.valor / maximo) * 100));
          const destaque = i === ultimo;
          return (
            <div
              key={d.rotulo}
              title={d.titulo ?? `${d.rotulo}: ${d.valor}`}
              className="group relative flex h-full flex-1 flex-col justify-end"
            >
              <span className="pointer-events-none absolute -top-1 left-1/2 z-10 hidden -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-md bg-ink px-2 py-1 font-mono text-xs text-white group-hover:block">
                {d.titulo ?? d.valor}
              </span>
              <div
                className={`w-full rounded-t-md transition-all duration-300 ${
                  destaque
                    ? "bg-accent"
                    : "bg-accent-soft group-hover:bg-accent/40"
                }`}
                style={{ height: `${h}%` }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex gap-1.5">
        {dados.map((d) => (
          <span
            key={d.rotulo}
            className="flex-1 truncate text-center font-mono text-xs text-ink-faint"
          >
            {d.rotulo}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Donut em SVG puro com legenda. */
export function GraficoDonut({
  fatias,
  centro,
}: {
  fatias: { rotulo: string; valor: number; cor: string }[];
  centro: string;
}) {
  const total = fatias.reduce((s, f) => s + f.valor, 0);
  const RAIO = 54;
  const CIRC = 2 * Math.PI * RAIO;
  let acumulado = 0;
  return (
    <div className="flex items-center gap-5">
      <div className="relative h-36 w-36 flex-none">
        <svg viewBox="0 0 128 128" className="h-full w-full -rotate-90">
          <circle cx="64" cy="64" r={RAIO} fill="none" strokeWidth="16" className="stroke-bg" />
          {total > 0 &&
            fatias.map((f) => {
              const fracao = f.valor / total;
              const el = (
                <circle
                  key={f.rotulo}
                  cx="64"
                  cy="64"
                  r={RAIO}
                  fill="none"
                  stroke={f.cor}
                  strokeWidth="16"
                  strokeDasharray={`${fracao * CIRC} ${CIRC}`}
                  strokeDashoffset={-acumulado * CIRC}
                  strokeLinecap="butt"
                />
              );
              acumulado += fracao;
              return el;
            })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-serif text-xl font-semibold text-ink">{centro}</span>
        </div>
      </div>
      <ul className="min-w-0 flex-1 space-y-2">
        {fatias.map((f) => (
          <li key={f.rotulo} className="flex items-center gap-2 text-sm">
            <span className="h-2.5 w-2.5 flex-none rounded-sm" style={{ background: f.cor }} />
            <span className="min-w-0 flex-1 truncate text-ink">{f.rotulo}</span>
            <span className="font-mono text-xs text-ink-muted">
              {total > 0 ? Math.round((f.valor / total) * 100) : 0}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BarraProgresso({
  valor,
  maximo,
  cor = "bg-accent",
}: {
  valor: number;
  maximo: number;
  cor?: string;
}) {
  const pct = maximo > 0 ? Math.min(100, Math.round((valor / maximo) * 100)) : 0;
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-pill bg-bg">
      <div className={`h-full rounded-pill ${cor} transition-all duration-500`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Esqueleto({ className = "h-24" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

export function EstadoVazio({
  icone = "caixa",
  titulo,
  texto,
  acao,
}: {
  icone?: string;
  titulo: string;
  texto?: string;
  acao?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="inline-flex h-11 w-11 items-center justify-center rounded-[14px] bg-accent-soft text-accent-deep">
        <Icone nome={icone} className="h-5 w-5" />
      </span>
      <p className="mt-4 font-display text-base font-semibold tracking-tight text-ink">{titulo}</p>
      {texto && <p className="mt-1 max-w-sm text-sm leading-6 text-ink-muted">{texto}</p>}
      {acao && <div className="mt-5">{acao}</div>}
    </div>
  );
}

export function SeloNivel({ nivel }: { nivel: string }) {
  if (nivel === "critico")
    return (
      <span className="badge-danger">
        <Icone nome="xCirculo" className="h-3.5 w-3.5" /> Crítico
      </span>
    );
  if (nivel === "atencao")
    return (
      <span className="badge-warn">
        <Icone nome="alerta" className="h-3.5 w-3.5" /> Atenção
      </span>
    );
  return (
    <span className="badge-info">
      <Icone nome="info" className="h-3.5 w-3.5" /> Info
    </span>
  );
}
