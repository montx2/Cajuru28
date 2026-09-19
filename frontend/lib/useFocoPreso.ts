"use client";

import { useEffect, useRef, type RefObject } from "react";

const SELECIONAVEIS = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

export interface OpcoesFocoPreso {
  ativo: boolean;
  aoFechar: () => void;
  /** `primeiro` é o padrão; diálogos de perigo pedem `ultimo` (Cancelar). */
  destino?: "primeiro" | "ultimo";
  travarRolagem?: boolean;
}

function visivel(elemento: HTMLElement): boolean {
  return elemento.offsetWidth > 0 || elemento.offsetHeight > 0 || elemento.getClientRects().length > 0;
}

/**
 * Foco preso e devolvido (WCAG 2.1.2 e 2.4.3).
 *
 * Sem isto, o Tab escapa do modal para a página atrás — o operador "perde" a
 * interface e o leitor de tela anuncia conteúdo que não está mais disponível.
 * O foco volta exatamente ao gatilho que abriu a camada.
 */
export function useFocoPreso<T extends HTMLElement>({
  ativo,
  aoFechar,
  destino = "primeiro",
  travarRolagem = true,
}: OpcoesFocoPreso): RefObject<T | null> {
  const container = useRef<T | null>(null);
  const gatilho = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!ativo) return;
    const elemento = container.current;
    if (!elemento) return;

    gatilho.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflowAnterior = document.body.style.overflow;
    if (travarRolagem) document.body.style.overflow = "hidden";

    function focaveis(): HTMLElement[] {
      return Array.from(elemento?.querySelectorAll<HTMLElement>(SELECIONAVEIS) ?? []).filter(visivel);
    }

    // Marca o destino preferido com `data-foco-inicial` quando o conteúdo quer
    // decidir (ex.: campo de confirmação por digitação).
    const preferido = elemento.querySelector<HTMLElement>("[data-foco-inicial]");
    const lista = focaveis();
    const alvo = preferido ?? (destino === "ultimo" ? (lista[lista.length - 1] ?? elemento) : (lista[0] ?? elemento));
    if (alvo === elemento) elemento.setAttribute("tabindex", "-1");
    alvo.focus();

    function aoTeclar(evento: KeyboardEvent) {
      if (evento.key === "Escape") {
        evento.stopPropagation();
        aoFechar();
        return;
      }
      if (evento.key !== "Tab") return;
      const atuais = focaveis();
      if (atuais.length === 0) {
        evento.preventDefault();
        elemento?.focus();
        return;
      }
      const primeiro = atuais[0];
      const ultimo = atuais[atuais.length - 1];
      const ativoAgora = document.activeElement;
      if (evento.shiftKey && (ativoAgora === primeiro || ativoAgora === elemento)) {
        evento.preventDefault();
        ultimo.focus();
      } else if (!evento.shiftKey && ativoAgora === ultimo) {
        evento.preventDefault();
        primeiro.focus();
      }
    }

    elemento.addEventListener("keydown", aoTeclar);
    return () => {
      elemento.removeEventListener("keydown", aoTeclar);
      if (travarRolagem) document.body.style.overflow = overflowAnterior;
      // Devolver o foco só faz sentido se o gatilho ainda existir na página.
      if (gatilho.current?.isConnected) gatilho.current.focus();
    };
  }, [ativo, aoFechar, destino, travarRolagem]);

  return container;
}
