"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CHAVE_TEMA, TEMA_PADRAO, ehTemaEscuro, normalizarTema, type Tema } from "./preferenciaTema";

export type { Tema } from "./preferenciaTema";
const EVENTO_TEMA = "fluxa:tema-alterado";

function escuroDoSistema(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function aplicarTema(tema: Tema): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.tema = ehTemaEscuro(tema, tema === "sistema" && escuroDoSistema()) ? "escuro" : "claro";
}

export function lerTema(): Tema {
  if (typeof window === "undefined") return TEMA_PADRAO;
  try {
    return normalizarTema(window.localStorage.getItem(CHAVE_TEMA));
  } catch {
    return TEMA_PADRAO;
  }
}

/** Preferência visual, nunca credencial. Escuro por padrão; claro e sistema
 * continuam disponíveis. A escolha funciona mesmo sem armazenamento. */
export function useTema(): { tema: Tema; definir: (tema: Tema) => void; escuro: boolean; alternar: () => void } {
  const [tema, setTema] = useState<Tema>(TEMA_PADRAO);
  const [escuro, setEscuro] = useState(true);
  const temaAtual = useRef<Tema>(TEMA_PADRAO);

  useEffect(() => {
    function sincronizar(proximo: Tema) {
      temaAtual.current = proximo;
      setTema(proximo);
      aplicarTema(proximo);
      setEscuro(document.documentElement.dataset.tema === "escuro");
    }
    sincronizar(lerTema());
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    function aoMudarSistema() {
      if (temaAtual.current === "sistema") sincronizar("sistema");
    }
    function aoMudarArmazenamento(evento: StorageEvent) {
      if (evento.key === CHAVE_TEMA || evento.key === null) sincronizar(normalizarTema(evento.newValue));
    }
    function aoMudarTema(evento: Event) {
      sincronizar((evento as CustomEvent<Tema>).detail);
    }
    media.addEventListener("change", aoMudarSistema);
    window.addEventListener("storage", aoMudarArmazenamento);
    window.addEventListener(EVENTO_TEMA, aoMudarTema);
    return () => {
      media.removeEventListener("change", aoMudarSistema);
      window.removeEventListener("storage", aoMudarArmazenamento);
      window.removeEventListener(EVENTO_TEMA, aoMudarTema);
    };
  }, []);

  const definir = useCallback((proximo: Tema) => {
    temaAtual.current = proximo;
    setTema(proximo);
    aplicarTema(proximo);
    setEscuro(document.documentElement.dataset.tema === "escuro");
    try {
      window.localStorage.setItem(CHAVE_TEMA, proximo);
    } catch {
      /* A preferência continua válida nesta aba, mesmo em modo privado. */
    }
    window.dispatchEvent(new CustomEvent<Tema>(EVENTO_TEMA, { detail: proximo }));
  }, []);

  const alternar = useCallback(() => {
    definir(document.documentElement.dataset.tema === "escuro" ? "claro" : "escuro");
  }, [definir]);

  return { tema, definir, escuro, alternar };
}
