"use client";

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

type Variante = "primaria" | "secundaria" | "sutil" | "perigo" | "perigo-sutil" | "link";
type Tamanho = "sm" | "md" | "lg";
export interface BotaoProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: Variante; tamanho?: Tamanho; carregando?: boolean; iconeEsquerda?: ReactNode;
  iconeDireita?: ReactNode; somenteIcone?: boolean; atalho?: string;
}
const variantes: Record<Variante, string> = {
  primaria: "border-acento bg-acento text-white hover:bg-acento-escuro",
  secundaria: "border-traco-forte bg-superficie text-tinta hover:bg-fundo-afundado",
  sutil: "border-transparent bg-transparent text-tinta-suave hover:bg-fundo-afundado hover:text-tinta",
  perigo: "border-erro bg-erro text-white hover:opacity-90",
  "perigo-sutil": "border-erro/40 bg-superficie text-erro hover:bg-erro-tenue",
  link: "border-transparent bg-transparent px-0 text-acento underline-offset-4 hover:underline",
};
const tamanhos: Record<Tamanho, string> = { sm: "h-8 px-3 text-xs", md: "h-9 px-3 text-sm", lg: "h-11 px-4 text-base" };

/** Ação consistente; o estado ocupado conserva a geometria e o nome acessível. */
export const Botao = forwardRef<HTMLButtonElement, BotaoProps>(function Botao(
  { variante = "secundaria", tamanho = "md", carregando = false, iconeEsquerda, iconeDireita, somenteIcone, atalho, className, children, disabled, ...props }, ref
) {
  return <button ref={ref} disabled={disabled || carregando} aria-busy={carregando || undefined}
    className={cn("relative inline-flex min-w-6 items-center justify-center gap-2 rounded-md border font-medium transition-colors duration-120 ease-produto disabled:cursor-not-allowed disabled:opacity-50", variantes[variante], tamanhos[tamanho], somenteIcone && "w-10 px-0", className)} {...props}>
    {carregando && <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-r-transparent" aria-hidden="true" />}
    {!carregando && iconeEsquerda}<span className={cn(carregando && "sr-only")}>{children}</span>{!carregando && iconeDireita}
    {atalho && <kbd className="ml-1 rounded-sm border border-current/30 px-1 text-2xs font-normal">{atalho}</kbd>}
  </button>;
});
