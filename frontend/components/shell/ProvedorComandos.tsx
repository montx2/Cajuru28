"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { rotaDaTecla } from "@/lib/rotas";
import { PaletaComandos } from "./PaletaComandos";
import { AtalhosTeclado } from "./AtalhosTeclado";
import { useSessao } from "./ProvedorSessao";

export interface Comandos {
  abrirPaleta: () => void;
  abrirAtalhos: () => void;
  /** Verdadeiro quando paleta ou atalhos estão abertos — as telas pausam atalhos próprios. */
  camadaAberta: boolean;
}

const Contexto = createContext<Comandos>({ abrirPaleta: () => undefined, abrirAtalhos: () => undefined, camadaAberta: false });

const JANELA_PREFIXO_G = 1_200;

/**
 * Atalhos globais: `Ctrl/⌘K` paleta, `?` mapa, `/` filtro, `g + letra` navegação.
 *
 * Nenhum atalho dispara enquanto o foco está num campo (senão "g" digitaria
 * nada) nem com um `aria-modal` aberto — camada aberta devolve controle ao
 * `Esc` e ao foco preso dela.
 */
export function ProvedorComandos({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { papel } = useSessao();
  const [paletaAberta, setPaletaAberta] = useState(false);
  const [atalhosAbertos, setAtalhosAbertos] = useState(false);
  const ultimoG = useRef(0);

  const abrirPaleta = useCallback(() => {
    setAtalhosAbertos(false);
    setPaletaAberta(true);
  }, []);

  const abrirAtalhos = useCallback(() => {
    setPaletaAberta(false);
    setAtalhosAbertos(true);
  }, []);

  useEffect(() => {
    function aoTeclar(evento: KeyboardEvent) {
      const camadaAberta = document.querySelector("[aria-modal='true']") !== null;

      if ((evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === "k") {
        evento.preventDefault();
        if (!camadaAberta) abrirPaleta();
        return;
      }

      if (camadaAberta) return;

      const alvo = evento.target as HTMLElement | null;
      const digitando =
        alvo !== null &&
        (alvo.isContentEditable ||
          alvo.closest("input, textarea, select, [contenteditable='true'], [role='combobox']") !== null);
      if (digitando) return;

      if (evento.key === "?") {
        evento.preventDefault();
        abrirAtalhos();
        return;
      }

      if (evento.key === "/") {
        const campo = document.querySelector<HTMLElement>("[data-atalho-filtro]");
        if (campo) {
          evento.preventDefault();
          campo.focus();
          if (campo instanceof HTMLInputElement) campo.select();
        }
        return;
      }

      if (evento.key.toLowerCase() === "g" && !evento.ctrlKey && !evento.metaKey && !evento.altKey) {
        ultimoG.current = Date.now();
        return;
      }

      if (Date.now() - ultimoG.current <= JANELA_PREFIXO_G) {
        ultimoG.current = 0;
        const destino = rotaDaTecla(evento.key, papel);
        if (destino) {
          evento.preventDefault();
          router.push(destino);
        }
      }
    }

    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [abrirAtalhos, abrirPaleta, papel, router]);

  return (
    <Contexto.Provider value={{ abrirPaleta, abrirAtalhos, camadaAberta: paletaAberta || atalhosAbertos }}>
      {children}
      <PaletaComandos
        aberto={paletaAberta}
        aoFechar={() => setPaletaAberta(false)}
        aoAbrirAtalhos={() => setAtalhosAbertos(true)}
      />
      <AtalhosTeclado aberto={atalhosAbertos} aoFechar={() => setAtalhosAbertos(false)} />
    </Contexto.Provider>
  );
}

export function useComandos(): Comandos {
  return useContext(Contexto);
}
