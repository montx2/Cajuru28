import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { Tom } from "@/lib/estados";

/**
 * Etiqueta (badge) e Pastilha (chip).
 *
 * Cor de estado só acompanha um ícone e uma palavra — nunca é o único canal
 * (8% dos homens são daltônicos e o relatório impresso sai em preto e branco).
 */

const TONS: Record<Tom, string> = {
  ok: "border-ok/30 bg-ok-tenue text-ok",
  espera: "border-espera/30 bg-espera-tenue text-espera",
  erro: "border-erro/30 bg-erro-tenue text-erro",
  info: "border-info/30 bg-info-tenue text-info",
  neutro: "border-traco bg-neutro-tenue text-neutro",
  acento: "border-acento-borda bg-acento-tenue text-acento-escuro",
};

const PONTOS: Record<Tom, string> = {
  ok: "bg-ok",
  espera: "bg-espera",
  erro: "bg-erro",
  info: "bg-info",
  neutro: "bg-neutro",
  acento: "bg-acento",
};

export interface EtiquetaProps {
  tom?: Tom;
  icone?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Ponto colorido antes do texto — reforço redundante ao tom. */
  ponto?: boolean;
  titulo?: string;
}

export function Etiqueta({ tom = "neutro", icone, children, className, ponto, titulo }: EtiquetaProps) {
  return (
    <span
      title={titulo}
      className={cn(
        "inline-flex max-w-full items-center gap-1 whitespace-nowrap rounded-badge border px-1.5 py-0.5 text-xs font-medium leading-4",
        TONS[tom],
        className
      )}
    >
      {ponto ? <span aria-hidden="true" className={cn("h-1.5 w-1.5 flex-none rounded-full", PONTOS[tom])} /> : null}
      {icone ? <span className="flex-none [&>svg]:h-3.5 [&>svg]:w-3.5">{icone}</span> : null}
      <span className="truncate">{children}</span>
    </span>
  );
}

export interface PastilhaProps {
  rotulo: string;
  valor?: ReactNode;
  ativa?: boolean;
  aoRemover?: () => void;
  aoClicar?: () => void;
  className?: string;
}

/** Filtro ativo visível: o operador precisa ver o que está restringindo a tela. */
export function Pastilha({ rotulo, valor, ativa, aoRemover, aoClicar, className }: PastilhaProps) {
  const Conteudo = (
    <>
      <span className="truncate text-tinta-suave">{rotulo}</span>
      {valor !== undefined ? <span className="nums truncate font-medium text-tinta-forte">{valor}</span> : null}
      {aoRemover ? (
        <span aria-hidden="true" className="ml-0.5 flex-none text-tinta-suave">
          ×
        </span>
      ) : null}
    </>
  );
  const classe = cn(
    "inline-flex h-7 max-w-full items-center gap-1.5 rounded-badge border px-2 text-xs transition-colors duration-120",
    ativa ? "border-acento-borda bg-acento-tenue text-acento-escuro" : "border-traco bg-superficie",
    (aoRemover || aoClicar) && "hover:border-traco-forte hover:bg-fundo-afundado",
    className
  );

  if (aoRemover) {
    return (
      <button type="button" onClick={aoRemover} className={classe} aria-label={`Remover filtro ${rotulo}${valor ? `: ${valor}` : ""}`}>
        {Conteudo}
      </button>
    );
  }
  if (aoClicar) {
    return (
      <button type="button" onClick={aoClicar} className={classe}>
        {Conteudo}
      </button>
    );
  }
  return <span className={classe}>{Conteudo}</span>;
}
