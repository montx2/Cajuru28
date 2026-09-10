"use client";

import { createContext, useCallback, useContext, useState } from "react";
import { Icone } from "./icons";

/** Toasts globais: `const toast = useToast(); toast.sucesso("ZIP pronto!")`. */

type TipoToast = "sucesso" | "erro" | "info";

interface ItemToast {
  id: number;
  tipo: TipoToast;
  mensagem: string;
}

const Contexto = createContext<{
  sucesso: (mensagem: string) => void;
  erro: (mensagem: string) => void;
  info: (mensagem: string) => void;
}>({ sucesso: () => {}, erro: () => {}, info: () => {} });

export const useToast = () => useContext(Contexto);

let proximoId = 1;

export function ProvedorToast({ children }: { children: React.ReactNode }) {
  const [itens, setItens] = useState<ItemToast[]>([]);

  const remover = useCallback((id: number) => {
    setItens((atual) => atual.filter((item) => item.id !== id));
  }, []);

  const adicionar = useCallback(
    (tipo: TipoToast, mensagem: string) => {
      const id = proximoId++;
      setItens((atual) => [...atual.slice(-3), { id, tipo, mensagem }]);
      setTimeout(() => remover(id), 5000);
    },
    [remover]
  );

  return (
    <Contexto.Provider
      value={{
        sucesso: (m) => adicionar("sucesso", m),
        erro: (m) => adicionar("erro", m),
        info: (m) => adicionar("info", m),
      }}
    >
      {children}
      <div className="no-print pointer-events-none fixed bottom-4 right-4 z-[100] flex w-80 flex-col gap-2">
        {itens.map((item) => (
          <div
            key={item.id}
            className={`animate-slide-in-right pointer-events-auto flex items-start gap-3 rounded-xl border bg-surface p-3 shadow-pop ${
              item.tipo === "sucesso"
                ? "border-accent/30"
                : item.tipo === "erro"
                  ? "border-danger/30"
                  : "border-info/30"
            }`}
          >
            <span
              className={`mt-0.5 ${
                item.tipo === "sucesso"
                  ? "text-accent"
                  : item.tipo === "erro"
                    ? "text-danger"
                    : "text-info"
              }`}
            >
              <Icone
                nome={item.tipo === "sucesso" ? "checkCirculo" : item.tipo === "erro" ? "xCirculo" : "info"}
                className="h-5 w-5"
              />
            </span>
            <p className="flex-1 text-sm text-ink">{item.mensagem}</p>
            <button
              type="button"
              onClick={() => remover(item.id)}
              className="text-ink-faint hover:text-ink"
              aria-label="Fechar aviso"
            >
              <Icone nome="x" className="h-4 w-4" />
            </button>
          </div>
        ))}
      </div>
    </Contexto.Provider>
  );
}
