"use client";

import { useEffect, useRef } from "react";

/**
 * Polling que pausa com a aba oculta.
 *
 * O Painel consulta a cada 30 s e Execuções a cada 15 s. Com cinco abas abertas
 * e o operador num telefone, isso é requisição à toa contra a API e cota da
 * SEFAZ gasta sem ninguém olhando. Ao voltar para a aba, a ação roda na hora —
 * o operador nunca vê dado velho esperando o próximo tick.
 */
export function usePolling(acao: () => void, intervaloMs: number | null, ativo = true): void {
  const acaoAtual = useRef(acao);
  acaoAtual.current = acao;

  useEffect(() => {
    if (!ativo || !intervaloMs || intervaloMs <= 0) return;
    let temporizador = 0;

    function agendar() {
      temporizador = window.setInterval(() => {
        if (!document.hidden) acaoAtual.current();
      }, intervaloMs as number);
    }

    function aoMudarVisibilidade() {
      if (document.hidden) {
        window.clearInterval(temporizador);
        return;
      }
      acaoAtual.current();
      agendar();
    }

    agendar();
    document.addEventListener("visibilitychange", aoMudarVisibilidade);
    return () => {
      window.clearInterval(temporizador);
      document.removeEventListener("visibilitychange", aoMudarVisibilidade);
    };
  }, [ativo, intervaloMs]);
}
