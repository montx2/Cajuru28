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
  /** Filtros segmentados não fingem controlar painéis de conteúdo. */
  modo?: "abas" | "filtros";
}

/**
 * Tablist ARIA: roving tabindex, setas, Home/End e ativação automática.
 * O estado mora na URL (quem chama decide), então a aba sobrevive a reload e
 * pode ser enviada por link.
 */
export function Abas({ abas, valor, aoMudar, idBase, className, rotulo, modo = "abas" }: AbasProps) {
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
    <div ref={container} role={modo === "abas" ? "tablist" : "group"} aria-label={rotulo} onKeyDown={aoTeclar} className={cn("rolagem-fina flex max-w-full gap-1 overflow-x-auto rounded-lg border border-traco bg-fundo-afundado p-1", className)}>
      {abas.map((aba) => {
        const ativa = aba.valor === valor;
        return (
          <button
            key={aba.valor}
            id={`${idBase}-aba-${aba.valor}`}
            role={modo === "abas" ? "tab" : undefined}
            type="button"
            aria-selected={modo === "abas" ? ativa : undefined}
            aria-pressed={modo === "filtros" ? ativa : undefined}
            aria-controls={modo === "abas" ? `${idBase}-painel-${aba.valor}` : undefined}
            tabIndex={ativa ? 0 : -1}
            disabled={aba.desabilitada}
            title={aba.motivo}
            onClick={() => aoMudar(aba.valor)}
            className={cn(
              "relative flex min-h-10 flex-none items-center gap-2 whitespace-nowrap rounded-controle border border-transparent px-3.5 text-sm transition-colors duration-150",
              ativa
                ? "border-acento-borda bg-superficie-alta font-medium text-acento"
                : "text-tinta-suave hover:bg-superficie hover:text-tinta",
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
  return (
    <div id={`${idBase}-painel-${valor}`} role="tabpanel" aria-labelledby={`${idBase}-aba-${valor}`} hidden={!ativo} tabIndex={ativo ? 0 : -1} className={cn("outline-none", className)}>
      {ativo ? children : null}
    </div>
  );
}

/** Mantém os destinos ARIA de todas as abas sem montar conteúdo inativo. */
export function PainelAbas({ abas, valor, idBase, children, className }: Pick<AbasProps, "abas" | "valor" | "idBase" | "className"> & { children: ReactNode }) {
  return abas.map((aba) => (
    <PainelAba key={aba.valor} idBase={idBase} valor={aba.valor} ativo={aba.valor === valor} className={className}>
      {children}
    </PainelAba>
  ));
}
