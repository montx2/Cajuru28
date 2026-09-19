"use client";

import {
  cloneElement,
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import { cn } from "@/lib/cn";

export type LadoDica = "topo" | "base" | "esquerda" | "direita";

const POSICAO: Record<LadoDica, string> = {
  topo: "bottom-full left-1/2 mb-2 -translate-x-1/2",
  base: "top-full left-1/2 mt-2 -translate-x-1/2",
  esquerda: "right-full top-1/2 mr-2 -translate-y-1/2",
  direita: "left-full top-1/2 ml-2 -translate-y-1/2",
};

export interface DicaProps {
  texto: string;
  /** Elemento que recebe `aria-describedby`. Precisa ser focável. */
  children: ReactElement<{ "aria-describedby"?: string }>;
  lado?: LadoDica;
  className?: string;
}

/**
 * Complemento curto de um controle — nunca informação necessária e nunca ação
 * (para ação existe `Popover`). Abre em 400 ms porque a dica não deve piscar a
 * cada passagem de mouse; fecha em 80 ms para não deixar rastro ao sair.
 */
export function Dica({ texto, children, lado = "topo", className }: DicaProps) {
  const id = useId();
  const [aberta, setAberta] = useState(false);
  const abrir = useRef<number | null>(null);
  const fechar = useRef<number | null>(null);

  function limpar() {
    if (abrir.current) window.clearTimeout(abrir.current);
    if (fechar.current) window.clearTimeout(fechar.current);
    abrir.current = null;
    fechar.current = null;
  }

  function agendarAbertura() {
    limpar();
    abrir.current = window.setTimeout(() => setAberta(true), 400);
  }

  function agendarFechamento() {
    limpar();
    fechar.current = window.setTimeout(() => setAberta(false), 80);
  }

  useEffect(() => limpar, []);

  function aoTeclar(evento: KeyboardEvent<HTMLSpanElement>) {
    if (evento.key === "Escape") {
      limpar();
      setAberta(false);
    }
  }

  return (
    <span
      className={cn("relative inline-flex", className)}
      onMouseEnter={agendarAbertura}
      onMouseLeave={agendarFechamento}
      onFocus={(evento: FocusEvent<HTMLSpanElement>) => {
        // Foco por teclado mostra na hora: não há cursor passeando aqui.
        if (evento.target instanceof HTMLElement && evento.target.matches(":focus-visible")) setAberta(true);
        else agendarAbertura();
      }}
      onBlur={agendarFechamento}
      onKeyDown={aoTeclar}
    >
      {cloneElement(children, { "aria-describedby": aberta ? id : children.props["aria-describedby"] })}
      {aberta ? (
        <span
          id={id}
          role="tooltip"
          className={cn(
            "pointer-events-none absolute z-camada max-w-64 rounded-controle bg-grafite px-2 py-1 text-xs leading-4 text-sobre-grafite shadow-nivel1 animate-entrar",
            POSICAO[lado]
          )}
        >
          {texto}
        </span>
      ) : null}
    </span>
  );
}
