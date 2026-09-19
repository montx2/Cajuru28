"use client";

import { useCallback, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

type ValorParametro = string | number | boolean | null | undefined;

/**
 * URL como fonte da verdade de todo filtro, aba, ordenação e página.
 *
 * Duas decisões moram aqui:
 *  - `router.replace` (nunca `push`): digitar num filtro não pode empilhar 40
 *    entradas de histórico e tornar o "voltar" inútil;
 *  - `scroll: false`: atualizar filtro não joga o operador para o topo da tela.
 */
export function useUrlEstado() {
  const router = useRouter();
  const caminho = usePathname();
  const parametros = useSearchParams();

  const definir = useCallback(
    (mudancas: Record<string, ValorParametro>, opcoes?: { preservar?: string[] }) => {
      const proximos = new URLSearchParams(parametros.toString());
      if (opcoes?.preservar) {
        for (const chave of Object.keys(mudancas)) {
          if (!opcoes.preservar.includes(chave)) proximos.delete(chave);
        }
      }
      for (const [chave, valor] of Object.entries(mudancas)) {
        if (valor === null || valor === undefined || valor === "") proximos.delete(chave);
        else if (valor === false) proximos.delete(chave);
        else proximos.set(chave, String(valor));
      }
      const texto = proximos.toString();
      router.replace(texto ? `${caminho}?${texto}` : caminho, { scroll: false });
    },
    [caminho, parametros, router]
  );

  const ler = useCallback(
    (chave: string, padrao = ""): string => parametros.get(chave) ?? padrao,
    [parametros]
  );

  const lerNumero = useCallback(
    (chave: string, padrao?: number): number | undefined => {
      const bruto = parametros.get(chave);
      if (bruto === null) return padrao;
      const valor = Number(bruto);
      return Number.isFinite(valor) ? valor : padrao;
    },
    [parametros]
  );

  const lerBooleano = useCallback(
    (chave: string, padrao = false): boolean => {
      const bruto = parametros.get(chave);
      if (bruto === null) return padrao;
      return bruto === "1" || bruto === "true" || bruto === "sim";
    },
    [parametros]
  );

  /** Chave estável para `useEffect`: muda só quando o estado da URL muda. */
  const assinatura = useMemo(() => parametros.toString(), [parametros]);

  return { parametros, assinatura, definir, ler, lerNumero, lerBooleano };
}
