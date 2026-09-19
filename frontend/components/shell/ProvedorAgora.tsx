"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const Contexto = createContext<number | null>(null);

/**
 * Um relógio só para a aplicação inteira.
 *
 * Tempo relativo e contagem regressiva aparecem em dezenas de linhas ao mesmo
 * tempo; se cada uma tivesse o próprio `setInterval`, o Painel com 500 empresas
 * acordaria 500 vezes por minuto. O tick é de 30 s e pausa com a aba oculta.
 */
export function ProvedorAgora({ children }: { children: ReactNode }) {
  const [agora, setAgora] = useState(() => Date.now());

  useEffect(() => {
    let temporizador = 0;

    function agendar() {
      temporizador = window.setInterval(() => {
        if (!document.hidden) setAgora(Date.now());
      }, 30_000);
    }

    function aoMudarVisibilidade() {
      if (document.hidden) {
        window.clearInterval(temporizador);
        return;
      }
      setAgora(Date.now());
      agendar();
    }

    agendar();
    document.addEventListener("visibilitychange", aoMudarVisibilidade);
    return () => {
      window.clearInterval(temporizador);
      document.removeEventListener("visibilitychange", aoMudarVisibilidade);
    };
  }, []);

  return <Contexto.Provider value={agora}>{children}</Contexto.Provider>;
}

/**
 * Instante de referência compartilhado (ms), atualizado a cada 30 s. Fora do
 * provedor devolve o relógio do momento — o componente nunca quebra.
 */
export function useAgora(): number {
  return useContext(Contexto) ?? Date.now();
}
