"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/** Mantém filtros reproduzíveis sem empilhar histórico a cada alteração. */
export function useUrlEstado() {
  const router = useRouter();
  const caminho = usePathname();
  const atuais = useSearchParams();
  const definir = useCallback((mudancas: Record<string, string | number | null | undefined>) => {
    const params = new URLSearchParams(atuais.toString());
    Object.entries(mudancas).forEach(([chave, valor]) => {
      if (valor === null || valor === undefined || valor === "") params.delete(chave);
      else params.set(chave, String(valor));
    });
    router.replace(`${caminho}${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
  }, [atuais, caminho, router]);
  return { parametros: atuais, definir };
}
