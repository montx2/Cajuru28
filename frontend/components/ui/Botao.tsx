"use client";

import Link from "next/link";
import { forwardRef, type ButtonHTMLAttributes, type ComponentProps, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Spinner } from "./Spinner";

export type VarianteBotao = "primaria" | "secundaria" | "sutil" | "perigo" | "perigo-sutil" | "link";
export type TamanhoBotao = "sm" | "md" | "lg";

export interface BotaoProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: VarianteBotao;
  tamanho?: TamanhoBotao;
  /** Mostra o spinner e mantém a largura e o nome acessível do botão. */
  carregando?: boolean;
  iconeEsquerda?: ReactNode;
  iconeDireita?: ReactNode;
  /** Exige `aria-label`: sem rótulo visível, o botão precisa de nome. */
  somenteIcone?: boolean;
  /** Tecla exibida ao lado do rótulo — atalho documentado no próprio controle. */
  atalho?: string;
}

/* Uma primária por tela: `primaria` é o acento índigo e só aparece uma vez.
   As demais variantes vivem sobre superfície ou sem fundo, para que a hierarquia
   de ação seja lida antes do clique. */
const VARIANTES: Record<VarianteBotao, string> = {
  primaria:
    "border-acento bg-acento text-acento-contraste hover:border-acento-escuro hover:bg-acento-escuro active:bg-acento-escuro",
  secundaria:
    "border-borda-controle bg-superficie text-tinta hover:border-tinta-suave hover:bg-fundo-afundado active:bg-fundo-afundado",
  sutil: "border-transparent bg-transparent text-tinta-suave hover:bg-fundo-afundado hover:text-tinta-forte active:bg-traco",
  perigo: "border-erro bg-erro text-acento-contraste hover:opacity-90 active:opacity-80",
  "perigo-sutil": "border-erro/45 bg-superficie text-erro hover:border-erro hover:bg-erro-tenue active:bg-erro-tenue",
  link: "border-transparent bg-transparent px-0 text-acento underline-offset-4 hover:underline",
};

const TAMANHOS: Record<TamanhoBotao, string> = {
  sm: "h-8 gap-1.5 px-2.5 text-xs",
  md: "h-9 gap-2 px-3 text-sm",
  lg: "h-11 gap-2 px-4 text-base",
};

/** Classes compartilhadas por `Botao` e `BotaoLink` — um visual, dois elementos. */
function classesDoBotao(variante: VarianteBotao, tamanho: TamanhoBotao, somenteIcone: boolean, className?: string): string {
  return cn(
    "relative inline-flex select-none items-center justify-center rounded-controle border font-medium",
    "transition-[background-color,border-color,color,opacity] duration-120 ease-produto",
    "disabled:pointer-events-none disabled:opacity-45",
    VARIANTES[variante],
    TAMANHOS[tamanho],
    somenteIcone && "aspect-square px-0",
    somenteIcone && tamanho === "sm" && "h-8 w-8",
    somenteIcone && tamanho === "md" && "h-9 w-9",
    somenteIcone && tamanho === "lg" && "h-11 w-11",
    variante === "link" && "h-auto rounded-none disabled:opacity-60",
    className
  );
}

export const Botao = forwardRef<HTMLButtonElement, BotaoProps>(function Botao(
  {
    variante = "secundaria",
    tamanho = "md",
    carregando = false,
    iconeEsquerda,
    iconeDireita,
    somenteIcone = false,
    atalho,
    className,
    children,
    disabled,
    type = "button",
    ...props
  },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || carregando}
      aria-busy={carregando || undefined}
      className={classesDoBotao(variante, tamanho, somenteIcone, className)}
      {...props}
    >
      {/* O conteúdo fica invisível (não oculto para leitores de tela) durante o
          carregamento: a geometria do botão não muda e o nome acessível fica. */}
      <span className={cn("inline-flex min-w-0 items-center gap-[inherit]", carregando && "opacity-0")}>
        {iconeEsquerda}
        {children ? <span className="truncate">{children}</span> : null}
        {iconeDireita}
        {atalho ? (
          <kbd className="ml-1 rounded-badge border border-current/35 px-1 font-mono text-2xs font-normal leading-4 opacity-80">
            {atalho}
          </kbd>
        ) : null}
      </span>
      {carregando ? (
        <span className="absolute inset-0 inline-flex items-center justify-center gap-2">
          <Spinner className={tamanho === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} />
        </span>
      ) : null}
    </button>
  );
});

export interface BotaoLinkProps extends Omit<ComponentProps<typeof Link>, "className"> {
  variante?: VarianteBotao;
  tamanho?: TamanhoBotao;
  iconeEsquerda?: ReactNode;
  iconeDireita?: ReactNode;
  somenteIcone?: boolean;
  atalho?: string;
  className?: string;
  /** Link desabilitado de verdade: `aria-disabled` + sem navegação + motivo. */
  indisponivel?: boolean;
  motivo?: string;
}

/**
 * Navegação com cara de botão.
 *
 * `<Link>` e não `<button onClick={router.push}>`: pré-carregamento, abrir em
 * nova aba e o "voltar" do navegador só funcionam com âncora real.
 */
export function BotaoLink({
  variante = "secundaria",
  tamanho = "md",
  iconeEsquerda,
  iconeDireita,
  somenteIcone = false,
  atalho,
  className,
  indisponivel = false,
  motivo,
  children,
  ...props
}: BotaoLinkProps) {
  return (
    <Link
      aria-disabled={indisponivel || undefined}
      title={motivo}
      tabIndex={indisponivel ? -1 : undefined}
      onClick={(evento) => {
        if (indisponivel) evento.preventDefault();
      }}
      className={classesDoBotao(variante, tamanho, somenteIcone, cn(indisponivel && "pointer-events-none opacity-45", className))}
      {...props}
    >
      <span className="inline-flex min-w-0 items-center gap-[inherit]">
        {iconeEsquerda}
        {children ? <span className="truncate">{children}</span> : null}
        {iconeDireita}
        {atalho ? (
          <kbd className="ml-1 rounded-badge border border-current/35 px-1 font-mono text-2xs font-normal leading-4 opacity-80">{atalho}</kbd>
        ) : null}
      </span>
    </Link>
  );
}
