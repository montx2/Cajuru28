"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface Recurso<T> {
  dados: T | null;
  erro: unknown | null;
  /** Primeira carga: é o único momento em que skeleton é aceitável. */
  carregando: boolean;
  /** Recarga com conteúdo já na tela — nunca substitui por skeleton. */
  atualizando: boolean;
  atualizar: () => void;
  /** Atualização otimista local (reverter em caso de erro é responsabilidade de quem chama). */
  definir: (valor: T | null) => void;
  ultimaAtualizacao: number | null;
}

export interface OpcoesRecurso {
  /** false = só carrega quando `atualizar()` é chamado. */
  automatico?: boolean;
}

/**
 * Leitura de dados com cancelamento e com os quatro estados separados.
 *
 * Dois detalhes que evitam os bugs clássicos de painel:
 *  - a flag `vivo` descarta resposta de requisição antiga (trocar de filtro duas
 *    vezes seguidas não pode deixar a resposta lenta vencer a rápida);
 *  - `carregando` só é true enquanto não há dado nenhum. Refetch mantém o
 *    conteúdo na tela e sinaliza `atualizando`, porque piscar skeleton em cima
 *    de uma tabela que o operador está lendo é a pior experiência possível aqui.
 */
export function useRecurso<T>(carregar: () => Promise<T>, dependencias: unknown[] = [], opcoes?: OpcoesRecurso): Recurso<T> {
  const automatico = opcoes?.automatico !== false;
  const [dados, setDados] = useState<T | null>(null);
  const [erro, setErro] = useState<unknown | null>(null);
  const [carregando, setCarregando] = useState(automatico);
  const [atualizando, setAtualizando] = useState(false);
  const [ultimaAtualizacao, setUltimaAtualizacao] = useState<number | null>(null);
  const [gatilho, setGatilho] = useState(0);

  const carregador = useRef(carregar);
  carregador.current = carregar;
  const temDados = useRef(false);
  temDados.current = dados !== null;

  // A chave serializa as dependências: objetos novos a cada render não podem
  // disparar um efeito (seria um loop de requisições).
  const chave = dependencias.map((dependencia) => String(dependencia)).join("|");

  useEffect(() => {
    if (!automatico && gatilho === 0) return;
    let vivo = true;

    if (temDados.current) setAtualizando(true);
    else setCarregando(true);

    carregador
      .current()
      .then((resultado) => {
        if (!vivo) return;
        setDados(resultado);
        setErro(null);
        setUltimaAtualizacao(Date.now());
      })
      .catch((falha: unknown) => {
        if (!vivo) return;
        setErro(falha);
      })
      .finally(() => {
        if (!vivo) return;
        setCarregando(false);
        setAtualizando(false);
      });

    return () => {
      vivo = false;
    };
    // `chave` e `gatilho` são as dependências de recarga; `automatico` entra de
    // propósito: ligar depois (ex.: período escolhido) dispara a primeira carga.
    // O carregador vive em ref para não recriar o efeito a cada render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave, gatilho, automatico]);

  const atualizar = useCallback(() => setGatilho((atual) => atual + 1), []);

  return { dados, erro, carregando, atualizando, atualizar, definir: setDados, ultimaAtualizacao };
}
