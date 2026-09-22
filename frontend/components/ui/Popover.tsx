"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useCamada } from "@/lib/useCamada";
import { Botao, type TamanhoBotao, type VarianteBotao } from "./Botao";
import { Dica } from "./Dica";
import { Icone, type NomeIcone } from "./Icone";

export interface PopoverProps {
  rotulo: string;
  icone?: NomeIcone;
  variante?: VarianteBotao;
  tamanho?: TamanhoBotao;
  /** Contagem no gatilho (alertas, itens selecionados). */
  contador?: number;
  tomContador?: "erro" | "espera" | "neutro";
  alinhamento?: "esquerda" | "direita";
  largura?: string;
  dica?: string;
  /** Conteúdo recebe `fechar` para encerrar a camada depois de uma ação. */
  children: (fechar: () => void) => ReactNode;
  className?: string;
  carregando?: boolean;
}

const POSICAO = {
  esquerda: "left-0",
  direita: "right-0",
} as const;

const TOM_CONTADOR = {
  erro: "bg-erro text-white",
  espera: "bg-espera text-white",
  neutro: "bg-neutro-tenue text-neutro",
} as const;

/**
 * Camada acionada por botão, com clique fora e `Esc` fechando.
 * Diferente de `Dica`: aqui pode haver ação — e por isso é foco gerenciado.
 */
export function Popover({
  rotulo,
  icone,
  variante = "sutil",
  tamanho = "md",
  contador,
  tomContador = "neutro",
  alinhamento = "direita",
  largura = "w-64",
  dica,
  children,
  className,
  carregando,
}: PopoverProps) {
  const camada = useCamada("dialog");

  const gatilho = (
    <Botao
      variante={variante}
      tamanho={tamanho}
      onClick={camada.alternar}
      carregando={carregando}
      aria-label={rotulo}
      {...camada.propsGatilho}
      className={cn(
        "relative h-10 w-10 px-0 text-tinta-suave hover:text-tinta-forte",
        camada.aberto && "bg-fundo-afundado text-tinta-forte"
      )}
    >
      {icone ? <Icone nome={icone} className="h-4 w-4" /> : <span className="truncate text-sm">{rotulo}</span>}
      {contador && contador > 0 ? (
        <span
          className={cn(
            "nums absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-2xs font-medium leading-none",
            TOM_CONTADOR[tomContador]
          )}
        >
          {contador > 99 ? "99+" : contador}
        </span>
      ) : null}
    </Botao>
  );

  return (
    <div ref={camada.container} className={cn("relative", className)}>
      {dica ? <Dica texto={dica}>{gatilho}</Dica> : gatilho}
      {camada.aberto ? (
        <div
          id={camada.idPainel}
          role="dialog"
          aria-label={rotulo}
          className={cn(
            "vidro absolute top-full z-camada mt-1.5 overflow-hidden rounded-cartao shadow-nivel1 animate-subir",
            POSICAO[alinhamento],
            largura
          )}
        >
          {children(camada.fechar)}
        </div>
      ) : null}
    </div>
  );
}

/** Cabeçalho padrão de popover: título curto + ação secundária. */
export function PopoverCabecalho({ titulo, acao }: { titulo: string; acao?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-traco px-3 py-2">
      <p className="text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">{titulo}</p>
      {acao}
    </div>
  );
}
