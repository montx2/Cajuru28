"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";

export interface Camada {
  aberto: boolean;
  abrir: () => void;
  fechar: () => void;
  alternar: () => void;
  container: React.RefObject<HTMLDivElement | null>;
  painel: React.RefObject<HTMLDivElement | null>;
  idPainel: string;
  /** Props ARIA prontas para o gatilho. */
  propsGatilho: {
    "aria-haspopup": "dialog" | "menu" | "true";
    "aria-expanded": boolean;
    "aria-controls": string;
  };
}

/**
 * Estado de camada flutuante: clique fora fecha, `Esc` fecha, e o gatilho já
 * sai com `aria-expanded`/`aria-controls` ligados ao painel. É o mesmo
 * comportamento em popover, menu, seletor de colunas e sino de alertas — por
 * isso vive num hook só.
 */
export function useCamada(tipo: "dialog" | "menu" = "dialog", aoAbrir?: () => void): Camada {
  const [aberto, setAberto] = useState(false);
  const container = useRef<HTMLDivElement | null>(null);
  const painel = useRef<HTMLDivElement | null>(null);
  const idGerado = useId();
  const idPainel = `camada-${idGerado}`;

  const fechar = useCallback(() => {
    setAberto(false);
    container.current?.querySelector<HTMLElement>("[aria-haspopup]")?.focus({ preventScroll: true });
  }, []);
  const abrir = useCallback(() => {
    setAberto(true);
    aoAbrir?.();
  }, [aoAbrir]);
  const alternar = useCallback(() => {
    setAberto((atual) => {
      if (!atual) aoAbrir?.();
      return !atual;
    });
  }, [aoAbrir]);

  useEffect(() => {
    if (!aberto) return;
    function focaveisEm(elemento: HTMLElement): HTMLElement[] {
      return Array.from(elemento.querySelectorAll<HTMLElement>("a[href],button:not([disabled]),input:not([disabled]):not([type='hidden']),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex='-1'])"))
        .filter((item) => !item.closest("[hidden],[aria-hidden='true']") && getComputedStyle(item).display !== "none" && getComputedStyle(item).visibility !== "hidden");
    }
    // Portais ficam no fim do body: sem mover o foco, Tab nunca chegaria aos
    // filtros. O efeito só roda na abertura, sem roubar o cursor ao digitar.
    if (tipo === "dialog" && painel.current) {
      painel.current.tabIndex = -1;
      (focaveisEm(painel.current)[0] ?? painel.current).focus({ preventScroll: true });
    }
    function aoClicarFora(evento: MouseEvent) {
      const alvo = evento.target as Node;
      if (!container.current?.contains(alvo) && !painel.current?.contains(alvo)) setAberto(false);
    }
    function aoTeclar(evento: KeyboardEvent) {
      if (evento.key === "Escape") {
        evento.preventDefault();
        evento.stopPropagation();
        fechar();
        return;
      }
      if (evento.key !== "Tab" || tipo !== "dialog" || !painel.current) return;
      const focaveis = focaveisEm(painel.current);
      const atual = document.activeElement;
      if (focaveis.length === 0) {
        evento.preventDefault();
        fechar();
      } else if (evento.shiftKey && atual === focaveis[0]) {
        evento.preventDefault();
        fechar();
      } else if (!evento.shiftKey && atual === focaveis[focaveis.length - 1]) {
        evento.preventDefault();
        const gatilho = container.current?.querySelector<HTMLElement>("[aria-haspopup]");
        const modal = container.current?.closest<HTMLElement>("[aria-modal='true']");
        const proximos = focaveisEm(modal ?? document.body).filter((item) => !painel.current?.contains(item));
        const indice = gatilho ? proximos.indexOf(gatilho) : -1;
        fechar();
        (proximos[indice + 1] ?? (modal ? proximos[0] : gatilho))?.focus({ preventScroll: true });
      }
    }
    // `pointerdown` pega também toque; o `keydown` fica no documento porque o
    // foco pode estar no gatilho, fora do painel.
    document.addEventListener("pointerdown", aoClicarFora);
    document.addEventListener("keydown", aoTeclar, true);
    return () => {
      document.removeEventListener("pointerdown", aoClicarFora);
      document.removeEventListener("keydown", aoTeclar, true);
    };
  }, [aberto, fechar, tipo]);

  return { aberto, abrir, fechar, alternar, container, painel, idPainel, propsGatilho: { "aria-haspopup": tipo, "aria-expanded": aberto, "aria-controls": idPainel } };
}
