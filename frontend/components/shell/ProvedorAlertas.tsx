"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { usePolling } from "@/lib/usePolling";

export interface ContagemAlertas {
  total: number;
  criticos: number;
  atencao: number;
}

interface ContextoAlertas {
  contagem: ContagemAlertas;
  carregando: boolean;
  erro: unknown;
  atualizar: () => void;
}

const VAZIA: ContagemAlertas = { total: 0, criticos: 0, atencao: 0 };
const Contexto = createContext<ContextoAlertas>({ contagem: VAZIA, carregando: true, erro: null, atualizar: () => undefined });

/**
 * Contagem para o badge do menu e do sino, com polling de 60 s pausado quando a
 * aba está oculta. A lista em si só é buscada quando o operador abre o sino ou a
 * tela de atenção — contagem barata, conteúdo sob demanda.
 */
export function ProvedorAlertas({ children }: { children: ReactNode }) {
  const [contagem, setContagem] = useState<ContagemAlertas>(VAZIA);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<unknown>(null);
  const [versao, setVersao] = useState(0);

  const atualizar = useCallback(() => setVersao((atual) => atual + 1), []);
  const montado = useRef(true);

  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
    };
  }, []);

  const ler = useCallback(async () => {
    try {
      const dados = await api.contagemAlertas();
      if (!montado.current) return;
      setContagem({ total: dados.total ?? 0, criticos: dados.criticos ?? 0, atencao: dados.atencao ?? 0 });
      setErro(null);
    } catch (falha) {
      if (montado.current) setErro(falha);
    } finally {
      if (montado.current) setCarregando(false);
    }
  }, []);

  useEffect(() => {
    setCarregando(true);
    void ler();
  }, [ler, versao]);

  usePolling(ler, 60_000);

  return <Contexto.Provider value={{ contagem, carregando, erro, atualizar }}>{children}</Contexto.Provider>;
}

export function useContagemAlertas(): ContextoAlertas {
  return useContext(Contexto);
}
