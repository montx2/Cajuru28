import { cn } from "@/lib/cn";
import { LogoFluxa } from "./LogoFluxa";

export interface MarcaFluxaProps {
  /** `lg` é a marca de capa (login); `md`, a do cabeçalho e da lateral. */
  tamanho?: "md" | "lg";
  /** Cor do ponto final: herda o acento do contexto (`tinta` no login mobile). */
  ponto?: "acento" | "lateral" | "tinta";
  /** Lateral colapsada: só o símbolo (o nome continua no `aria-label` do link). */
  comNome?: boolean;
  className?: string;
}

const PONTO = {
  acento: "text-acento",
  lateral: "text-[var(--lateral-acento)]",
  tinta: "text-tinta-forte",
} as const;

/**
 * A marca: o quadrado menta com o símbolo e o wordmark "fluxa.".
 *
 * Estava escrita três vezes (lateral, capa do login e topo do login no
 * celular), com o mesmo *tracking* negativo digitado em dois lugares e tamanhos
 * ligeiramente diferentes — o tipo de detalhe que ninguém percebe até a marca
 * aparecer com dois pesos na mesma tela.
 */
export function MarcaFluxa({ tamanho = "md", ponto = "lateral", comNome = true, className }: MarcaFluxaProps) {
  const grande = tamanho === "lg";
  return (
    <span className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <span
        className={cn(
          "marca-fluxa flex flex-none items-center justify-center rounded-lg",
          grande ? "h-10 w-10" : "h-9 w-9"
        )}
      >
        <LogoFluxa className={grande ? "h-7 w-7" : "h-6 w-6"} />
      </span>
      {comNome ? (
        <span className={cn("truncate font-semibold tracking-[-.04em]", grande ? "text-xl" : "text-lg")}>
          fluxa<span className={PONTO[ponto]}>.</span>
        </span>
      ) : null}
    </span>
  );
}
