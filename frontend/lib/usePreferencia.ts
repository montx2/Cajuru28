"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { PREFIXO_ARMAZENAMENTO } from "./atalhos";

/**
 * Preferências de trabalho, nunca credenciais: densidade, colunas, navegação e
 * alertas lidos. Servidor e primeira renderização do cliente usam o mesmo
 * padrão; o armazenamento é lido depois de montar, sem quebrar a hidratação.
 */
export function usePreferencia<T>(chave: string, padrao: T): [T, (valor: T | ((atual: T) => T)) => void] {
  const [valor, setValor] = useState<T>(padrao);
  const padraoAtual = useRef(padrao);
  padraoAtual.current = padrao;

  useEffect(() => {
    try {
      const bruto = window.localStorage.getItem(`${PREFIXO_ARMAZENAMENTO}${chave}`);
      setValor(bruto === null ? padraoAtual.current : (JSON.parse(bruto) as T));
    } catch {
      setValor(padraoAtual.current);
    }
  }, [chave]);

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
