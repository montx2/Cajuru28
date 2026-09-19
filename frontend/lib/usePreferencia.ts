"use client";

import { useCallback, useState } from "react";
import { PREFIXO_ARMAZENAMENTO } from "./atalhos";

/**
 * Preferência de trabalho persistida: tema, densidade, colunas visíveis, barra
 * lateral colapsada, alertas lidos.
 *
 * É contexto de trabalho, nunca credencial — a sessão vive em cookie HttpOnly e
 * nada aqui é segredo. A leitura acontece no inicializador com guarda de SSR:
 * o shell só renderiza depois de `/auth/me`, então não há hidratação divergente.
 */
export function usePreferencia<T>(chave: string, padrao: T): [T, (valor: T | ((atual: T) => T)) => void] {
  const [valor, setValor] = useState<T>(() => {
    if (typeof window === "undefined") return padrao;
    try {
      const bruto = window.localStorage.getItem(`${PREFIXO_ARMAZENAMENTO}${chave}`);
      return bruto === null ? padrao : (JSON.parse(bruto) as T);
    } catch {
      return padrao;
    }
  });

  const definir = useCallback(
    (proximo: T | ((atual: T) => T)) => {
      setValor((atual) => {
        const resolvido = typeof proximo === "function" ? (proximo as (atual: T) => T)(atual) : proximo;
        try {
          window.localStorage.setItem(`${PREFIXO_ARMAZENAMENTO}${chave}`, JSON.stringify(resolvido));
        } catch {
          /* modo privado ou cota cheia: a preferência segue valendo nesta sessão */
        }
        return resolvido;
      });
    },
    [chave]
  );

  return [valor, definir];
}
