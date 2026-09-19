"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { Tom } from "@/lib/estados";
import { Icone, type NomeIcone } from "./Icone";

/** Aviso flutuante (toast). O nome difere do `Aviso` em linha de propósito. */
export interface AvisoFlutuante {
  id: number;
  tom: Tom;
  titulo: string;
  descricao?: ReactNode;
  acao?: { rotulo: string; aoClicar: () => void };
  /** 0 mantém na tela até o fechamento manual. */
  duracao?: number;
}

interface ContextoToast {
  avisar: (aviso: Omit<AvisoFlutuante, "id">) => number;
  fechar: (id: number) => void;
}

const Contexto = createContext<ContextoToast | null>(null);

const TONS: Record<Tom, { icone: NomeIcone; faixa: string; tinta: string }> = {
  ok: { icone: "verificar-circulo", faixa: "bg-ok", tinta: "text-ok" },
  espera: { icone: "ampulheta", faixa: "bg-espera", tinta: "text-espera" },
  erro: { icone: "alerta", faixa: "bg-erro", tinta: "text-erro" },
  info: { icone: "info", faixa: "bg-info", tinta: "text-info" },
  neutro: { icone: "info", faixa: "bg-neutro", tinta: "text-neutro" },
  acento: { icone: "verificar", faixa: "bg-acento", tinta: "text-acento" },
};

const MAXIMO_NA_FILA = 3;
const DURACAO_PADRAO = 5000;

/**
 * Fila de avisos flutuantes.
 *
 * Três por vez, cinco segundos, pausa no hover: aviso que empilha sem limite
 * cobre a tabela e aviso que some enquanto é lido é pior que nenhum. A região é
 * `role="status"` — interromper o leitor de tela fica reservado a `role="alert"`
 * dentro das telas.
 */
export function ProvedorToast({ children }: { children: ReactNode }) {
  const [avisos, setAvisos] = useState<AvisoFlutuante[]>([]);
  const proximoId = useRef(1);
  const temporizadores = useRef(new Map<number, number>());

  const fechar = useCallback((id: number) => {
    setAvisos((atuais) => atuais.filter((aviso) => aviso.id !== id));
    const temporizador = temporizadores.current.get(id);
    if (temporizador) window.clearTimeout(temporizador);
    temporizadores.current.delete(id);
  }, []);

  const agendar = useCallback(
    (id: number, duracao: number) => {
      if (duracao <= 0) return;
      temporizadores.current.set(id, window.setTimeout(() => fechar(id), duracao));
    },
    [fechar]
  );

  const avisar = useCallback(
    (aviso: Omit<AvisoFlutuante, "id">) => {
      const id = proximoId.current;
      proximoId.current += 1;
      setAvisos((atuais) => [...atuais.slice(-(MAXIMO_NA_FILA - 1)), { ...aviso, id }]);
      agendar(id, aviso.duracao ?? DURACAO_PADRAO);
      return id;
    },
    [agendar]
  );

  useEffect(() => {
    const mapa = temporizadores.current;
    return () => {
      mapa.forEach((temporizador) => window.clearTimeout(temporizador));
      mapa.clear();
    };
  }, []);

  function pausar(id: number) {
      const temporizador = temporizadores.current.get(id);
    if (temporizador) {
      window.clearTimeout(temporizador);
      temporizadores.current.delete(id);
    }
  }

  function retomar(aviso: AvisoFlutuante) {
      agendar(aviso.id, 2500);
  }

  return (
    <Contexto.Provider value={{ avisar, fechar }}>
      {children}
      <div
        role="status"
        aria-live="polite"
        aria-relevant="additions"
        className="nao-imprimir pointer-events-none fixed bottom-4 right-4 z-aviso flex w-[min(26rem,calc(100vw-2rem))] flex-col gap-2"
      >
        {avisos.map((aviso) => {
          const tom = TONS[aviso.tom] ?? TONS.neutro;
          return (
            <div
              key={aviso.id}
              onMouseEnter={() => pausar(aviso.id)}
              onMouseLeave={() => retomar(aviso)}
              className="pointer-events-auto relative flex gap-3 overflow-hidden rounded-cartao border border-traco bg-superficie px-3.5 py-3 shadow-nivel1 animate-subir"
            >
              <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[3px]", tom.faixa)} />
              <Icone nome={tom.icone} className={cn("mt-0.5 h-4 w-4 flex-none", tom.tinta)} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-tinta-forte">{aviso.titulo}</p>
                {aviso.descricao ? <div className="mt-0.5 text-sm leading-6 text-tinta-suave">{aviso.descricao}</div> : null}
                {aviso.acao ? (
                  <button
                    type="button"
                    onClick={() => {
                      aviso.acao?.aoClicar();
                      fechar(aviso.id);
                    }}
                    className="mt-2 rounded-badge text-sm font-medium text-acento underline-offset-4 hover:underline"
                  >
                    {aviso.acao.rotulo}
                  </button>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => fechar(aviso.id)}
                aria-label="Fechar aviso"
                className="-mr-1 -mt-1 flex h-8 w-8 flex-none items-center justify-center self-start rounded-badge text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta-forte"
              >
                <Icone nome="fechar" className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </Contexto.Provider>
  );
}

export function useToast(): ContextoToast {
  const contexto = useContext(Contexto);
  if (!contexto) {
    // Fora do provedor (teste, tela isolada) devolve um no-op: nada quebra e
    // nenhum aviso fantasma aparece.
    return { avisar: () => 0, fechar: () => undefined };
  }
  return contexto;
}
