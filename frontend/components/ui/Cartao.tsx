import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Icone, type NomeIcone } from "./Icone";

export interface CartaoProps {
  titulo?: ReactNode;
  descricao?: ReactNode;
  icone?: NomeIcone;
  acoes?: ReactNode;
  rodape?: ReactNode;
  densidade?: "compacta" | "confortavel";
  children?: ReactNode;
  className?: string;
  classeCorpo?: string;
  tomFaixa?: string;
  semBorda?: boolean;
}

/** Superfície opaca e ações alinhadas ao título, sem vidro sobre os dados. */
export function Cartao({ titulo, descricao, icone, acoes, rodape, densidade = "confortavel", children, className, classeCorpo, tomFaixa, semBorda }: CartaoProps) {
  const compacta = densidade === "compacta";
  return (
    <section className={cn("cartao-produto relative min-w-0 rounded-cartao", semBorda && "!border-0", className)}>
      {tomFaixa ? <span aria-hidden="true" className={cn("absolute inset-y-3 left-0 w-[3px] rounded-full", tomFaixa)} /> : null}
      {titulo || acoes ? (
        <header className={cn("flex min-w-0 flex-wrap items-center justify-between gap-3 border-b border-traco", compacta ? "px-4 py-3" : "px-4 py-4 sm:px-5")}>
          <div className="min-w-0 flex-1 basis-48">
            {titulo ? (
              <h2 className="flex items-center gap-2.5 text-md font-semibold tracking-tight text-tinta-forte">
                {icone ? <Icone nome={icone} className="h-[18px] w-[18px] flex-none text-tinta-suave" /> : null}
                <span>{titulo}</span>
              </h2>
            ) : null}
            {descricao ? <p className="mt-1 max-w-leitura text-xs leading-5 text-tinta-suave">{descricao}</p> : null}
          </div>
          {acoes ? <div className="flex min-w-0 flex-wrap items-center gap-2">{acoes}</div> : null}
        </header>
      ) : null}
      {children ? <div className={cn(compacta ? "p-4" : "p-4 sm:p-5", classeCorpo)}>{children}</div> : null}
      {rodape ? <footer className="rounded-b-cartao border-t border-traco bg-fundo-afundado px-4 py-3 text-xs text-tinta-suave sm:px-5">{rodape}</footer> : null}
    </section>
  );
}

export interface CabecalhoPaginaProps {
  kicker?: ReactNode;
  titulo: string;
  descricao?: ReactNode;
  acoes?: ReactNode;
  acima?: ReactNode;
  children?: ReactNode;
  className?: string;
}

/** Uma linha de leitura estável. Quando não há espaço, as ações ocupam uma
 * linha própria, em vez de espremer o título ou quebrar rótulos dos botões. */
export function CabecalhoPagina({ kicker, titulo, descricao, acoes, acima, children, className }: CabecalhoPaginaProps) {
  return (
    <header className={cn("cabecalho-pagina nao-imprimir", className)}>
      {acima ? <div className="mb-5">{acima}</div> : null}
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-5">
        <div className="min-w-0 flex-1 basis-72">
          {kicker ? <p className="mb-2 text-xs font-medium uppercase tracking-[.12em] text-tinta-suave">{kicker}</p> : null}
          <h1 className="text-xl font-semibold text-tinta-forte">{titulo}</h1>
          {descricao ? <p className="mt-2 max-w-leitura text-sm leading-6 text-tinta-suave">{descricao}</p> : null}
        </div>
        {acoes ? <div className="acoes-pagina sm:pt-1">{acoes}</div> : null}
      </div>
      {children ? <div className="mt-5">{children}</div> : null}
    </header>
  );
}
