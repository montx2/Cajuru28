"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { useFocoPreso } from "@/lib/useFocoPreso";
import { Icone } from "./Icone";

export interface PainelProps {
  aberto: boolean;
  aoFechar: () => void;
  titulo: ReactNode;
  /** Linha de contexto abaixo do título (empresa, chave, competência). */
  contexto?: ReactNode;
  children?: ReactNode;
  rodape?: ReactNode;
  acoes?: ReactNode;
  className?: string;
  semPadding?: boolean;
}

/**
 * Painel lateral (drawer) para detalhe de registro: o operador lê o item sem
 * perder a lista de onde veio — fechar com `Esc` devolve o foco à linha.
 */
export function Painel({ aberto, aoFechar, titulo, contexto, children, rodape, acoes, className, semPadding }: PainelProps) {
  const [montado, setMontado] = useState(false);
  const container = useFocoPreso<HTMLDivElement>({ ativo: aberto && montado, aoFechar });

  useEffect(() => {
    setMontado(true);
  }, []);

  if (!aberto || !montado) return null;

  return createPortal(
    <div className="fixed inset-0 z-modal flex justify-end">
      <div aria-hidden="true" className="absolute inset-0 bg-grafite/50 animate-entrar" onClick={aoFechar} />
      <div
        ref={container}
        role="dialog"
        aria-modal="true"
        aria-label={typeof titulo === "string" ? titulo : "Detalhe"}
        className={cn(
          "relative flex h-full w-max-painel max-w-full flex-col border-l border-traco bg-superficie-alta shadow-nivel2 animate-deslizar",
          className
        )}
      >
        <header className="flex items-start justify-between gap-4 border-b border-traco px-5 py-3.5">
          <div className="min-w-0 flex-1">
            <h2 className="text-md font-semibold text-tinta-forte">{titulo}</h2>
            {contexto ? <div className="mt-1 text-xs text-tinta-suave">{contexto}</div> : null}
          </div>
          <div className="flex flex-none items-center gap-1">
            {acoes}
            <button
              type="button"
              onClick={aoFechar}
              aria-label="Fechar painel"
              className="flex h-9 w-9 items-center justify-center rounded-controle text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta-forte"
            >
              <Icone nome="fechar" className="h-4 w-4" />
            </button>
          </div>
        </header>
        {children ? (
          <div className={cn("rolagem-fina min-h-0 flex-1 overflow-y-auto", semPadding ? "" : "px-5 py-4")}>{children}</div>
        ) : null}
        {rodape ? <footer className="border-t border-traco bg-fundo-afundado px-5 py-3">{rodape}</footer> : null}
      </div>
    </div>,
    document.body
  );
}
