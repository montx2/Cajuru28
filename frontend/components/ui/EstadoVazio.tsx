import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Icone, type NomeIcone } from "./Icone";

export interface EstadoVazioProps {
  titulo: string;
  /** Uma frase que instrui. Estado vazio não é decoração: é o próximo passo. */
  instrucao?: ReactNode;
  acao?: ReactNode;
  icone?: NomeIcone;
  className?: string;
  /** Sem moldura: para usar dentro de cartões e tabelas. */
  inline?: boolean;
}

export function EstadoVazio({ titulo, instrucao, acao, icone = "caixa", className, inline }: EstadoVazioProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center px-5 py-8 text-center",
        !inline && "rounded-cartao border border-traco bg-superficie",
        className
      )}
    >
      <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-traco bg-fundo-afundado"><Icone nome={icone} className="h-5 w-5 text-tinta-suave" /></span>
      <p className="mt-3 text-sm font-medium text-tinta-forte">{titulo}</p>
      {instrucao ? <p className="mt-1 max-w-md text-sm leading-6 text-tinta-suave">{instrucao}</p> : null}
      {acao ? <div className="mt-4 flex flex-wrap items-center justify-center gap-2">{acao}</div> : null}
    </div>
  );
}
