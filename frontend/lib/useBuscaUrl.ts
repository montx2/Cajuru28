"use client";

import { useCallback, useEffect, useState } from "react";
import { useDebounced } from "./useDebounced";
import { useUrlEstado } from "./urlEstado";

/**
 * Busca digitada → URL, com debounce de 300 ms.
 *
 * O estado local existe porque escrever cada tecla na URL geraria uma consulta
 * por caractere; o efeito que sincroniza de volta (URL → campo) mantém o
 * "voltar" do navegador e o link colado funcionando.
 */
export function useBuscaUrl(chave = "busca", atrasoMs = 300): { valor: string; aoMudar: (valor: string) => void } {
  const { definir, ler } = useUrlEstado();
  const daUrl = ler(chave);
  const [local, setLocal] = useState(daUrl);
  const debounced = useDebounced(local, atrasoMs);

  useEffect(() => {
    setLocal(daUrl);
  }, [daUrl]);

  useEffect(() => {
    if (debounced === daUrl) return;
    definir({ [chave]: debounced || null });
  }, [chave, daUrl, debounced, definir]);

  const aoMudar = useCallback((valor: string) => setLocal(valor), []);
  return { valor: local, aoMudar };
}
