"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";

export interface Camada {
  aberto: boolean;
  abrir: () => void;
  fechar: () => void;
  alternar: () => void;
  container: React.RefObject<HTMLDivElement | null>;
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
  const idGerado = useId();
  const idPainel = `camada-${idGerado}`;

  const fechar = useCallback(() => setAberto(false), []);
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
    function aoClicarFora(evento: MouseEvent) {
      if (container.current && !container.current.contains(evento.target as Node)) setAberto(false);
    }
    function aoTeclar(evento: KeyboardEvent) {
      if (evento.key === "Escape") setAberto(false);
    }
    // `pointerdown` pega também toque; o `keydown` fica no documento porque o
    // foco pode estar no gatilho, fora do painel.
    document.addEventListener("pointerdown", aoClicarFora);
    document.addEventListener("keydown", aoTeclar);
    return () => {
      document.removeEventListener("pointerdown", aoClicarFora);
      document.removeEventListener("keydown", aoTeclar);
    };
  }, [aberto]);

  return { aberto, abrir, fechar, alternar, container, idPainel, propsGatilho: { "aria-haspopup": tipo, "aria-expanded": aberto, "aria-controls": aberto ? idPainel : idPainel } };
}
