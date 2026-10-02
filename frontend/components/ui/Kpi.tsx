"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { percentual } from "@/lib/format";
import { Dica } from "./Dica";
import { EsqueletoNumero } from "./Esqueleto";
import { Icone, type NomeIcone } from "./Icone";
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
  icone?: NomeIcone;
  /** Já formatado por quem chama: o KPI não sabe se é moeda, contagem ou razão. */
  valor: ReactNode;
  contexto?: ReactNode;
  variacao?: VariacaoKpi;
  tom?: Tom;
  dica?: string;
  href?: string;
  carregando?: boolean;
  /** O número que conduz a leitura da grade recebe escala maior. */
  destaque?: boolean;
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
export function Kpi({ rotulo, icone, valor, contexto, variacao, tom = "neutro", dica, href, carregando, destaque = false, className }: KpiProps) {
  const conteudo = (
    <>
      <div className="flex min-h-9 items-start justify-between gap-3">
        <p className="flex min-w-0 items-start gap-2 text-xs font-medium text-tinta-suave">
          {icone ? <Icone nome={icone} className="mt-0.5 h-4 w-4 flex-none" /> : null}
          <span className="line-clamp-2" title={rotulo}>{rotulo}</span>
        </p>
        {dica ? (
          <Dica texto={dica}>
            <span tabIndex={0} className="flex-none text-tinta-fraca">
              <Icone nome="info" className="h-3.5 w-3.5" />
              <span className="sr-only">Sobre este indicador: {dica}</span>
            </span>
          </Dica>
        ) : null}
      </div>

      <div className={cn("nums my-3 min-w-0 break-words font-semibold tracking-[-.035em]", destaque ? "text-2xl" : "text-xl", COR_VALOR[tom])}>
        {carregando ? <EsqueletoNumero className={destaque ? "h-9 w-28" : "h-7 w-20"} /> : valor}
      </div>

      {contexto ? <p className="nums text-xs text-tinta-suave">{contexto}</p> : null}

      {variacao ? (
        <p
          className={cn(
            "nums mt-3 flex flex-wrap items-center gap-1.5 text-xs",
            variacao.valor === null || variacao.valor === 0
              ? "text-tinta-suave"
              : variacao.invertida
                ? variacao.valor > 0
                  ? "text-erro"
                  : "text-ok"
                : variacao.valor > 0
                  ? "text-ok"
                  : "text-erro"
          )}
          title={variacao.base}
        >
          <Icone nome="tendencia" className={cn("h-3.5 w-3.5 flex-none", (variacao.valor ?? 0) < 0 && "-scale-y-100")} />
          {variacao.valor === null ? "sem base" : `${variacao.valor > 0 ? "+" : ""}${percentual(variacao.valor, 1)}`}
          <span className="truncate font-normal text-tinta-suave">{variacao.base ?? "vs. período anterior"}</span>
        </p>
      ) : null}
    </>
  );

  const classe = cn(
    "cartao-produto flex h-full min-w-0 flex-col rounded-cartao p-4 transition-colors duration-150 sm:p-5",
    destaque && "border-acento-borda",
    href && "hover:border-borda-controle hover:bg-superficie-alta",
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
    <section aria-label={rotulo} className={cn("grid gap-3 lg:grid-cols-3", colunas === 3 ? "grid-cols-1 min-[480px]:grid-cols-2" : "grid-cols-2", COLUNAS[colunas], className)}>
      {itens.map((item) => (
        <Kpi key={item.rotulo} {...item} />
      ))}
    </section>
  );
}
