"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { ehAdmin, podeOperar, somenteLeitura } from "@/lib/papel";
import type { UsuarioAtual } from "@/lib/types";

export interface Sessao {
  usuario: UsuarioAtual | null;
  carregando: boolean;
  erro: unknown;
  papel: string;
  ehAdmin: boolean;
  podeOperar: boolean;
  somenteLeitura: boolean;
  atualizar: () => void;
  sair: () => Promise<void>;
}

const Contexto = createContext<Sessao | null>(null);

/**
 * Uma leitura de `/auth/me` por sessão, compartilhada.
 *
 * Antes cada tela chamava por conta: cinco requisições iguais no carregamento e
 * papéis divergentes entre menu e botões. A sessão é cookie HttpOnly — o
 * JavaScript nunca vê token; este contexto guarda apenas nome, e-mail e papel.
 */
export function ProvedorSessao({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [usuario, setUsuario] = useState<UsuarioAtual | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<unknown>(null);
  const [versao, setVersao] = useState(0);

  useEffect(() => {
    let vivo = true;
    setCarregando(true);
    api
      .quemSouEu()
      .then((dados) => {
        if (!vivo) return;
        setUsuario(dados);
        setErro(null);
      })
      .catch((falha: unknown) => {
        if (!vivo) return;
        setErro(falha);
      })
      .finally(() => {
        if (vivo) setCarregando(false);
      });
    return () => {
      vivo = false;
    };
  }, [versao]);

  const atualizar = useCallback(() => setVersao((atual) => atual + 1), []);

  const sair = useCallback(async () => {
    try {
      // Quem apaga o cookie HttpOnly é a API; ao navegador resta navegar.
      await api.logout();
    } finally {
      router.replace("/login");
    }
  }, [router]);

  const papel = usuario?.papel ?? "";

  return (
    <Contexto.Provider
      value={{
        usuario,
        carregando,
        erro,
        papel,
        ehAdmin: ehAdmin(papel),
        podeOperar: podeOperar(papel),
        somenteLeitura: somenteLeitura(papel),
        atualizar,
        sair,
      }}
    >
      {children}
    </Contexto.Provider>
  );
}

export function useSessao(): Sessao {
  const contexto = useContext(Contexto);
  if (!contexto) {
    // Fora do shell (login, página raiz) nada é garantido: papel vazio significa
    // "sem permissão afirmativa", então a interface esconde ação administrativa.
    return {
      usuario: null,
      carregando: false,
      erro: null,
      papel: "",
      ehAdmin: false,
      podeOperar: false,
      somenteLeitura: true,
      atualizar: () => undefined,
      sair: async () => undefined,
    };
  }
  return contexto;
}
