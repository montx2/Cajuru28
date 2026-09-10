"use client";

import { useEffect, useState } from "react";
import { api } from "./api";
import type { UsuarioAtual } from "./types";

/**
 * Papel do usuário logado, com cache em memória (uma chamada por sessão).
 * A API barra de verdade; aqui é só para esconder/desabilitar botões.
 */

let cache: UsuarioAtual | null | undefined;

export function usePapel() {
  const [usuario, setUsuario] = useState<UsuarioAtual | null>(cache ?? null);

  useEffect(() => {
    if (cache !== undefined) {
      setUsuario(cache);
      return;
    }
    api
      .quemSouEu()
      .then((u) => {
        cache = u;
        setUsuario(u);
      })
      .catch(() => {});
  }, []);

  const papel = usuario?.papel ?? "admin";
  return {
    usuario,
    papel,
    carregando: usuario === null,
    ehAdmin: papel === "admin",
    podeOperar: papel === "admin" || papel === "operador",
    somenteLeitura: papel === "leitura",
  };
}

export function limparCachePapel() {
  cache = undefined;
}
