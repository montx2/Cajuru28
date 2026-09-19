"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { percentual } from "@/lib/format";
import { Dica } from "./Dica";
import { EsqueletoNumero } from "./Esqueleto";
import { Icone } from "./Icone";
import type { Tom } from "@/lib/estados";

export interface VariacaoKpi {
  /** Percentual já calculado (12.4 = +12,4%). `null` quando não há base de comparação. */
  valor: number | null;
  /** Contra o que compara — vira o `title`, para o número não ficar solto. */
  base?: string;
  /** Crescer é ruim aqui (canceladas, erros): inverte o tom. */
  invertida?: boolean;
}

export interface KpiProps {
  rotulo: string;
  /** Já formatado por quem chama: o KPI não sabe se é moeda, contagem ou razão. */
  valor: ReactNode;
  contexto?: ReactNode;
  variacao?: VariacaoKpi;
  tom?: Tom;
  dica?: string;
  href?: string;
  carregando?: boolean;
  className?: string;
}

const COR_VALOR: Record<Tom, string> = {
  ok: "text-ok",
  espera: "text-espera",
  erro: "text-erro",
  info: "text-info",
  neutro: "text-tinta-forte",
  acento: "text-tinta-forte",
};

/**
 * Número grande, rótulo pequeno, nada de ícone em círculo colorido.
 *
 * O cartão não levanta no hover: ele é leitura, não botão. Quando `href` existe,
 * a única mudança é a borda — e o cartão inteiro vira um link nomeado.
 */
export function Kpi({ rotulo, valor, contexto, variacao, tom = "neutro", dica, href, carregando, className }: KpiProps) {
  const conteudo = (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <p className="truncate text-xs text-tinta-suave">{rotulo}</p>
        {dica ? (
          <Dica texto={dica}>
            <span tabIndex={0} className="flex-none text-tinta-fraca">
              <Icone nome="info" className="h-3.5 w-3.5" />
              <span className="sr-only">Sobre este indicador: {dica}</span>
            </span>
          </Dica>
        ) : null}
      </div>

      <p className={cn("nums mt-1 truncate text-xl font-semibold tracking-tight", COR_VALOR[tom])}>
        {carregando ? <EsqueletoNumero className="h-7 w-20" /> : valor}
      </p>

      {contexto ? <p className="nums mt-0.5 truncate text-xs text-tinta-suave">{contexto}</p> : null}

      {variacao && variacao.valor !== null ? (
        <p
          className={cn(
            "nums mt-1.5 flex items-center gap-1 text-xs",
            variacao.invertida ? (variacao.valor > 0 ? "text-erro" : "text-ok") : variacao.valor > 0 ? "text-ok" : "text-erro"
          )}
          title={variacao.base}
        >
          <Icone nome="tendencia" className={cn("h-3.5 w-3.5 flex-none", variacao.valor < 0 && "-scale-y-100")} />
          {variacao.valor > 0 ? "+" : ""}
          {percentual(variacao.valor, 1)}
          <span className="truncate font-normal text-tinta-suave">{variacao.base ?? "vs. período anterior"}</span>
        </p>
      ) : null}
    </>
  );

  const classe = cn(
    "block rounded-cartao border border-traco bg-superficie p-3.5 transition-colors duration-120",
    href && "hover:border-traco-forte",
    className
  );

  if (href) {
    return (
      <Link href={href} className={classe} aria-label={`${rotulo}: ${typeof valor === "string" || typeof valor === "number" ? valor : "ver detalhes"}`}>
        {conteudo}
      </Link>
    );
  }
  return <div className={classe}>{conteudo}</div>;
}

export interface GradeKpisProps {
  itens: KpiProps[];
  /** Colunas no breakpoint largo; abaixo disso a grade empilha em 1–2. */
  colunas?: 3 | 4 | 5 | 6;
  rotulo?: string;
  className?: string;
}

const COLUNAS = {
  3: "xl:grid-cols-3",
  4: "xl:grid-cols-4",
  5: "xl:grid-cols-5",
  6: "xl:grid-cols-6",
} as const;

/** Grade de KPIs: mesma altura, mesmo espaçamento, sem hierarquia inventada. */
export function GradeKpis({ itens, colunas = 5, rotulo = "Indicadores do período", className }: GradeKpisProps) {
  return (
    <section aria-label={rotulo} className={cn("grid grid-cols-2 gap-3 lg:grid-cols-3", COLUNAS[colunas], className)}>
      {itens.map((item) => (
        <Kpi key={item.rotulo} {...item} />
      ))}
    </section>
  );
}
