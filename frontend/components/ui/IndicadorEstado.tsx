import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { EstadoVisual, Tom } from "@/lib/estados";
import { Icone, type NomeIcone } from "./Icone";

/**
 * A única representação de estado do sistema: tom + ícone + palavra.
 *
 * Três variantes para três densidades — `etiqueta` em telas de decisão,
 * `texto` em tabela densa, `ponto` quando o rótulo já está em outra coluna.
 */

const TONS_TEXTO: Record<Tom, string> = {
  ok: "text-ok",
  espera: "text-espera",
  erro: "text-erro",
  info: "text-info",
  neutro: "text-tinta-suave",
  acento: "text-acento-escuro",
};

const TONS_ETIQUETA: Record<Tom, string> = {
  ok: "border-ok/30 bg-ok-tenue text-ok",
  espera: "border-espera/30 bg-espera-tenue text-espera",
  erro: "border-erro/30 bg-erro-tenue text-erro",
  info: "border-info/30 bg-info-tenue text-info",
  neutro: "border-traco bg-neutro-tenue text-neutro",
  acento: "border-acento-borda bg-acento-tenue text-acento-escuro",
};

const TONS_PONTO: Record<Tom, string> = {
  ok: "bg-ok",
  espera: "bg-espera",
  erro: "bg-erro",
  info: "bg-info",
  neutro: "bg-neutro",
  acento: "bg-acento",
};

export interface IndicadorEstadoProps extends Partial<EstadoVisual> {
  tom: Tom;
  rotulo: string;
  icone?: NomeIcone;
  variante?: "etiqueta" | "texto" | "ponto";
  /** Segunda linha curta (motivo, contagem regressiva). */
  detalhe?: ReactNode;
  /** Camada absoluta — sempre que houver tempo relativo na superfície. */
  titulo?: string;
  className?: string;
  /** Substitui o ícone por um elemento próprio (ex.: spinner). */
  sobrescreverIcone?: ReactNode;
}

export function IndicadorEstado({
  tom,
  rotulo,
  icone,
  variante = "etiqueta",
  pulsa = false,
  detalhe,
  titulo,
  className,
  sobrescreverIcone,
}: IndicadorEstadoProps) {
  const glifo = sobrescreverIcone ?? (icone ? <Icone nome={icone} className="h-3.5 w-3.5 flex-none" /> : null);

  if (variante === "ponto") {
    return (
      <span className={cn("inline-flex items-center gap-2 text-sm text-tinta", className)} title={titulo}>
        <span
          aria-hidden="true"
          className={cn("h-2 w-2 flex-none rounded-full", TONS_PONTO[tom], pulsa && "animate-pulso")}
        />
        <span className="truncate">{rotulo}</span>
        {detalhe ? <span className="truncate text-xs text-tinta-suave">{detalhe}</span> : null}
      </span>
    );
  }

  if (variante === "texto") {
    return (
      <span className={cn("inline-flex min-w-0 flex-col gap-0.5", className)} title={titulo}>
        <span className={cn("inline-flex min-w-0 items-center gap-1.5 text-sm font-medium", TONS_TEXTO[tom])}>
          {glifo ? <span className={cn("flex-none", pulsa && "animate-pulso")}>{glifo}</span> : null}
          <span className="truncate">{rotulo}</span>
        </span>
        {detalhe ? <span className="truncate text-xs font-normal text-tinta-suave">{detalhe}</span> : null}
      </span>
    );
  }

  return (
    <span
      title={titulo}
      className={cn(
        "inline-flex max-w-full flex-col gap-0.5 rounded-badge border px-1.5 py-1 align-middle",
        TONS_ETIQUETA[tom],
        className
      )}
    >
      <span className="inline-flex min-w-0 items-center gap-1.5 text-xs font-medium leading-4">
        {glifo ? <span className={cn("flex-none", pulsa && "animate-pulso")}>{glifo}</span> : null}
        <span className="truncate">{rotulo}</span>
      </span>
      {detalhe ? <span className="truncate text-2xs font-normal leading-4 opacity-90">{detalhe}</span> : null}
    </span>
  );
}
