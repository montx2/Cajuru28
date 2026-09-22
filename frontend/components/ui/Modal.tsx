"use client";

import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { useFocoPreso } from "@/lib/useFocoPreso";
import { Icone } from "./Icone";

export type LarguraModal = "estreita" | "media" | "larga" | "extralarga";

const LARGURAS: Record<LarguraModal, string> = {
  estreita: "max-w-md",
  media: "max-w-xl",
  larga: "max-w-3xl",
  extralarga: "max-w-6xl",
};

export interface ModalProps {
  aberto: boolean;
  aoFechar: () => void;
  titulo: string;
  descricao?: ReactNode;
  children?: ReactNode;
  rodape?: ReactNode;
  largura?: LarguraModal;
  /** Diálogos de perigo abrem com o foco no último botão (Cancelar). */
  focoNoFim?: boolean;
  className?: string;
  /** Conteúdo sem padding (tabelas e listas que ocupam a largura toda). */
  semPadding?: boolean;
}

/**
 * Modal em portal, com foco preso e devolvido, `Esc` e overlay clicável.
 *
 * Portal é necessário: dentro da árvore da tabela o `overflow` do container
 * cortaria a camada, e o empilhamento brigaria com o cabeçalho sticky.
 */
export function Modal({ aberto, aoFechar, titulo, descricao, children, rodape, largura = "media", focoNoFim, className, semPadding }: ModalProps) {
  const [montado, setMontado] = useState(false);
  const container = useFocoPreso<HTMLDivElement>({ ativo: aberto && montado, aoFechar, destino: focoNoFim ? "ultimo" : "primeiro" });

  useEffect(() => {
    setMontado(true);
  }, []);

  if (!aberto || !montado) return null;
  const idTitulo = `modal-titulo-${titulo.replace(/\W+/g, "-").toLowerCase()}`;

  return createPortal(
    <div className="fixed inset-0 z-modal flex items-start justify-center overflow-y-auto p-4 sm:p-6">
      <div
        aria-hidden="true"
        className="fixed inset-0 bg-grafite/50 animate-entrar"
        onClick={aoFechar}
      />
      <div
        ref={container}
        role="dialog"
        aria-modal="true"
        aria-labelledby={idTitulo}
        aria-describedby={descricao ? `${idTitulo}-descricao` : undefined}
        className={cn(
          "vidro relative my-auto flex max-h-[calc(100vh-3rem)] w-full flex-col overflow-hidden rounded-camada shadow-nivel2 animate-subir",
          LARGURAS[largura],
          className
        )}
      >
        <header className="flex items-start justify-between gap-4 border-b border-traco px-5 py-3.5">
          <div className="min-w-0">
            <h2 id={idTitulo} className="text-md font-semibold text-tinta-forte">
              {titulo}
            </h2>
            {descricao ? (
              <p id={`${idTitulo}-descricao`} className="mt-1 max-w-leitura text-sm leading-6 text-tinta-suave">
                {descricao}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={aoFechar}
            aria-label="Fechar"
            className="-mr-1.5 flex h-9 w-9 flex-none items-center justify-center rounded-controle text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta-forte"
          >
            <Icone nome="fechar" className="h-4 w-4" />
          </button>
        </header>
        {children ? (
          <div className={cn("rolagem-fina min-h-0 flex-1 overflow-y-auto", semPadding ? "" : "px-5 py-4")}>{children}</div>
        ) : null}
        {rodape ? (
          <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-traco bg-fundo-afundado px-5 py-3">
            {rodape}
          </footer>
        ) : null}
      </div>
    </div>,
    document.body
  );
}
