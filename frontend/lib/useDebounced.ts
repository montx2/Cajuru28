"use client";

import { useEffect, useState } from "react";

/**
 * Espera o operador parar de digitar antes de propagar o valor.
 * 300 ms é o padrão do produto: menos que isso cada tecla vira uma consulta;
 * mais que isso a busca parece travada.
 */
export function useDebounced<T>(valor: T, atrasoMs = 300): T {
  const [estavel, setEstavel] = useState(valor);

  useEffect(() => {
    const temporizador = setTimeout(() => setEstavel(valor), atrasoMs);
    return () => clearTimeout(temporizador);
  }, [valor, atrasoMs]);

  return estavel;
}
