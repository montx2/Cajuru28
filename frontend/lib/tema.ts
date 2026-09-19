"use client";

import { useCallback, useEffect, useState } from "react";
import { PREFIXO_ARMAZENAMENTO } from "./atalhos";

export type Tema = "claro" | "escuro" | "sistema";

const CHAVE_TEMA = `${PREFIXO_ARMAZENAMENTO}tema`;

function escuroDoSistema(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Aplica o tema no `<html>`; o script inline do layout já fez a primeira pintura. */
export function aplicarTema(tema: Tema): void {
  if (typeof document === "undefined") return;
  const escuro = tema === "escuro" || (tema === "sistema" && escuroDoSistema());
  document.documentElement.dataset.tema = escuro ? "escuro" : "claro";
}

export function lerTema(): Tema {
  if (typeof window === "undefined") return "sistema";
  const salvo = window.localStorage.getItem(CHAVE_TEMA);
  return salvo === "claro" || salvo === "escuro" ? salvo : "sistema";
}

/**
 * Tema é preferência de trabalho, persistida e com opção "seguir o sistema".
 * Nenhuma credencial passa por aqui — sessão vive em cookie HttpOnly.
 */
export function useTema(): { tema: Tema; definir: (tema: Tema) => void; escuro: boolean; alternar: () => void } {
  const [tema, setTema] = useState<Tema>("sistema");
  const [escuro, setEscuro] = useState(false);

  useEffect(() => {
    const inicial = lerTema();
    setTema(inicial);
    aplicarTema(inicial);
    setEscuro(document.documentElement.dataset.tema === "escuro");

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    function aoMudarSistema() {
      if (lerTema() !== "sistema") return;
      aplicarTema("sistema");
      setEscuro(document.documentElement.dataset.tema === "escuro");
    }
    media.addEventListener("change", aoMudarSistema);
    return () => media.removeEventListener("change", aoMudarSistema);
  }, []);

  const definir = useCallback((proximo: Tema) => {
    setTema(proximo);
    aplicarTema(proximo);
    setEscuro(document.documentElement.dataset.tema === "escuro");
    try {
      window.localStorage.setItem(CHAVE_TEMA, proximo);
    } catch {
      /* sem armazenamento disponível: o tema vale para esta sessão */
    }
  }, []);

  const alternar = useCallback(() => {
    definir(document.documentElement.dataset.tema === "escuro" ? "claro" : "escuro");
  }, [definir]);

  return { tema, definir, escuro, alternar };
}
