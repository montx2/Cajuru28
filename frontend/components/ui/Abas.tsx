"use client";

import { useRef, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { numero } from "@/lib/format";
import { Icone, type NomeIcone } from "./Icone";

export interface Aba {
  valor: string;
  rotulo: string;
  icone?: NomeIcone;
  contador?: number;
  desabilitada?: boolean;
  motivo?: string;
}

export interface AbasProps {
  abas: Aba[];
  valor: string;
  aoMudar: (valor: string) => void;
  /** Prefixo dos ids — liga `tab` a `tabpanel` sem colisão entre telas. */
  idBase: string;
  className?: string;
  rotulo: string;
}

/**
 * Tablist ARIA: roving tabindex, setas, Home/End e ativação automática.
 * O estado mora na URL (quem chama decide), então a aba sobrevive a reload e
 * pode ser enviada por link.
 */
export function Abas({ abas, valor, aoMudar, idBase, className, rotulo }: AbasProps) {
  const container = useRef<HTMLDivElement | null>(null);

  function aoTeclar(evento: React.KeyboardEvent<HTMLDivElement>) {
    const habilitadas = abas.filter((aba) => !aba.desabilitada);
    if (habilitadas.length < 2) return;
    const indice = habilitadas.findIndex((aba) => aba.valor === valor);
    let proximo = indice;
    if (evento.key === "ArrowRight") proximo = (indice + 1) % habilitadas.length;
    else if (evento.key === "ArrowLeft") proximo = (indice - 1 + habilitadas.length) % habilitadas.length;
    else if (evento.key === "Home") proximo = 0;
    else if (evento.key === "End") proximo = habilitadas.length - 1;
    else return;
    evento.preventDefault();
    const aba = habilitadas[proximo];
    aoMudar(aba.valor);
    container.current?.querySelector<HTMLElement>(`#${idBase}-aba-${aba.valor}`)?.focus();
  }

  return (
    <div ref={container} role="tablist" aria-label={rotulo} onKeyDown={aoTeclar} className={cn("rolagem-fina flex gap-1 overflow-x-auto border-b border-traco", className)}>
      {abas.map((aba) => {
        const ativa = aba.valor === valor;
        return (
          <button
            key={aba.valor}
            id={`${idBase}-aba-${aba.valor}`}
            role="tab"
            type="button"
            aria-selected={ativa}
            aria-controls={`${idBase}-painel-${aba.valor}`}
            tabIndex={ativa ? 0 : -1}
            disabled={aba.desabilitada}
            title={aba.motivo}
            onClick={() => aoMudar(aba.valor)}
            className={cn(
              "relative -mb-px flex min-h-10 items-center gap-2 whitespace-nowrap border-b-2 px-3 text-sm transition-colors duration-120",
              ativa
                ? "border-acento font-medium text-tinta-forte"
                : "border-transparent text-tinta-suave hover:border-traco-forte hover:text-tinta",
              aba.desabilitada && "cursor-not-allowed opacity-55 hover:border-transparent"
            )}
          >
            {aba.icone ? <Icone nome={aba.icone} className="h-4 w-4 flex-none" /> : null}
            {aba.rotulo}
            {aba.contador !== undefined ? (
              <span className={cn("nums rounded-badge px-1.5 py-0.5 text-2xs font-medium", ativa ? "bg-acento-tenue text-acento-escuro" : "bg-neutro-tenue text-neutro")}>
                {numero(aba.contador)}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function PainelAba({ idBase, valor, ativo, children, className }: { idBase: string; valor: string; ativo: boolean; children: ReactNode; className?: string }) {
  if (!ativo) return null;
  return (
    <div id={`${idBase}-painel-${valor}`} role="tabpanel" aria-labelledby={`${idBase}-aba-${valor}`} tabIndex={0} className={cn("pt-4 outline-none", className)}>
      {children}
    </div>
  );
}
