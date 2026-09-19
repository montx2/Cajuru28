"use client";

import { forwardRef, type ComponentProps } from "react";
import { cn } from "@/lib/cn";
import { Botao, type VarianteBotao } from "./Botao";
import { Dica } from "./Dica";

export interface BotaoIconeProps extends Omit<ComponentProps<typeof Botao>, "children" | "variante"> {
  /** Nome acessível obrigatório: é o que sobra quando não há rótulo visível. */
  rotulo: string;
  icone: React.ReactNode;
  variante?: Exclude<VarianteBotao, "link">;
  /** Dica curta sobre a ação. Ícone isolado sem tooltip é ícone sem nome. */
  dica?: string;
  ladoDica?: "topo" | "base" | "esquerda" | "direita";
}

/* Alvo de 40 px mesmo quando o glifo tem 16 px (WCAG 2.5.8). A dica é exigida
   pela regra de produto, não opcional: `rotulo` já resolve o leitor de tela. */
export const BotaoIcone = forwardRef<HTMLButtonElement, BotaoIconeProps>(function BotaoIcone(
  { rotulo, icone, dica, ladoDica = "topo", className, variante = "sutil", ...props },
  ref
) {
  const botao = (
    <Botao
      ref={ref}
      variante={variante}
      aria-label={rotulo}
      somenteIcone
      className={cn("h-10 w-10 flex-none text-tinta-suave hover:text-tinta-forte", className)}
      {...props}
    >
      {icone}
    </Botao>
  );
  if (!dica) return botao;
  return (
    <Dica texto={dica} lado={ladoDica}>
      {botao}
    </Dica>
  );
});
