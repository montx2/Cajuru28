"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

interface ContextoProgresso {
  /** Marca uma consulta em voo — a tela continua legível por baixo. */
  definir: (ativo: boolean) => void;
}

const Contexto = createContext<ContextoProgresso>({ definir: () => undefined });

/**
 * Indicador global de atualização.
 *
 * Spinner cobrindo conteúdo já renderizado é o jeito mais rápido de fazer um
 * painel parecer lento: a barra de 2 px diz "está chegando coisa nova" sem
 * esconder nada, e skeleton só aparece no primeiro carregamento.
 */
export function ProvedorProgresso({ children }: { children: ReactNode }) {
  const [ativo, setAtivo] = useState(false);
  const definir = useCallback((valor: boolean) => setAtivo(valor), []);

  return (
    <Contexto.Provider value={{ definir }}>
      <div
        aria-hidden="true"
        className={cn(
          "pointer-events-none fixed left-0 right-0 z-cabecalho h-0.5 overflow-hidden transition-opacity duration-180",
          ativo ? "opacity-100" : "opacity-0"
        )}
      >
        <div className={cn("h-full w-1/3 bg-acento", ativo && "animate-progresso")} />
      </div>
      <p className="sr-only" role="status" aria-live="polite">
        {ativo ? "Atualizando dados" : ""}
      </p>
      {children}
    </Contexto.Provider>
  );
}

export function useProgresso(): ContextoProgresso {
  return useContext(Contexto);
}

/**
 * Liga a barra global enquanto a tela recarrega dados em segundo plano.
 * O `return` desliga ao desmontar: sair da tela não pode deixar barra acesa.
 */
export function useSinalizarAtualizacao(atualizando: boolean): void {
  const { definir } = useProgresso();
  useEffect(() => {
    if (!atualizando) return;
    definir(true);
    return () => definir(false);
  }, [atualizando, definir]);
}
