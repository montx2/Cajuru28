import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface CartaoProps {
  titulo?: ReactNode;
  descricao?: ReactNode;
  acoes?: ReactNode;
  rodape?: ReactNode;
  /** `compacta` para tabelas densas; `confortavel` para telas de leitura. */
  densidade?: "compacta" | "confortavel";
  children?: ReactNode;
  className?: string;
  classeCorpo?: string;
  /** Faixa de estado de 3 px à esquerda do cabeçalho. */
  tomFaixa?: string;
  semBorda?: boolean;
}

/**
 * Cartão sem sombra: a separação vem da borda de 1 px e do espaço. Ele sobe de
 * nível (sombra) apenas quando vira camada flutuante — nunca no hover.
 */
export function Cartao({
  titulo,
  descricao,
  acoes,
  rodape,
  densidade = "confortavel",
  children,
  className,
  classeCorpo,
  tomFaixa,
  semBorda,
}: CartaoProps) {
  const padding = densidade === "compacta" ? "p-3" : "p-4 sm:p-5";
  return (
    <section
      className={cn(
        "vidro relative overflow-hidden rounded-cartao",
        semBorda && "!border-0",
        className
      )}
    >
      {tomFaixa ? <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[3px]", tomFaixa)} /> : null}
      {titulo || acoes ? (
        <header
          className={cn(
            "flex flex-wrap items-start justify-between gap-3 border-b border-traco",
            densidade === "compacta" ? "px-3 py-2.5" : "px-4 py-3 sm:px-5"
          )}
        >
          <div className="min-w-0">
            {titulo ? <h2 className="text-md font-semibold text-tinta-forte">{titulo}</h2> : null}
            {descricao ? <p className="mt-0.5 max-w-leitura text-sm leading-6 text-tinta-suave">{descricao}</p> : null}
          </div>
          {acoes ? <div className="flex flex-none flex-wrap items-center gap-2">{acoes}</div> : null}
        </header>
      ) : null}
      {children ? <div className={cn(padding, classeCorpo)}>{children}</div> : null}
      {rodape ? (
        <footer className="border-t border-traco bg-fundo-afundado px-4 py-2.5 text-xs text-tinta-suave">{rodape}</footer>
      ) : null}
    </section>
  );
}

export interface CabecalhoPaginaProps {
  /** Contexto curto acima do título (ex.: "Fiscal", competência atual). */
  kicker?: ReactNode;
  titulo: string;
  descricao?: ReactNode;
  acoes?: ReactNode;
  /** Navegação estrutural (Migalhas) acima do título. */
  acima?: ReactNode;
  /** Barra de filtros ou resumo colada ao cabeçalho. */
  children?: ReactNode;
  className?: string;
}

/** Um `h1` por tela, sempre no mesmo lugar — a leitura começa sempre igual. */
export function CabecalhoPagina({ kicker, titulo, descricao, acoes, acima, children, className }: CabecalhoPaginaProps) {
  return (
    <header className={cn("nao-imprimir mb-5", className)}>
      {acima}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          {kicker ? (
            <p className="mb-1 text-2xs font-medium uppercase tracking-[.04em] text-tinta-suave">{kicker}</p>
          ) : null}
          <h1 className="text-lg font-semibold leading-7 text-tinta-forte">{titulo}</h1>
          {descricao ? <p className="mt-1 max-w-leitura text-sm leading-6 text-tinta-suave">{descricao}</p> : null}
        </div>
        {acoes ? <div className="flex flex-wrap items-center gap-2">{acoes}</div> : null}
      </div>
      {children ? <div className="mt-4">{children}</div> : null}
    </header>
  );
}
