"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { PREFIXO_ARMAZENAMENTO } from "@/lib/atalhos";
import { mesAtual, paraAPI } from "@/lib/competencia";
import { PARAM_MES, mesValido, resolverContexto, sementeDaUrl, type SementeContexto } from "@/lib/contexto";
import { PERIODO_VAZIO, intervaloDoMes, type Periodo } from "@/lib/periodo";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import type { Empresa } from "@/lib/types";

const CHAVE_GUARDADO = `${PREFIXO_ARMAZENAMENTO}contexto-global`;

export interface ContextoGlobal {
  /** Mês de trabalho no formato interno `AAAA-MM` (vazio até `pronto`). */
  mes: string;
  /** O mês na língua da API (`MM/AAAA`). */
  competencia: string | undefined;
  /** O mês como intervalo fechado — o que as telas mandam para a API. */
  periodo: Periodo;
  /** Lista única de empresas, para os filtros de tela: uma requisição só. */
  empresas: Empresa[];
  carregandoEmpresas: boolean;
  /** Semente resolvida (URL > guardado > padrão) — libera as consultas. */
  pronto: boolean;
  definirMes: (mes: string) => void;
}

const Contexto = createContext<ContextoGlobal | null>(null);

/**
 * Fonte única da verdade da **competência** (o mês de trabalho) em todo o app.
 *
 * - resolve uma vez ao montar: URL explícita vence o guardado no navegador;
 * - adota `?mes=` quando a URL muda depois (link de outra tela, botão voltar);
 * - grava o mês na URL e no navegador **apenas quando o operador escolhe** —
 *   nada de espelhar estado de volta para a URL a cada render.
 *
 * Essa última linha é o conserto do bug mais caro da barra antiga: o provedor
 * reescrevia `?empresa=`/`?mes=` enquanto as telas reescreviam os mesmos
 * parâmetros com outra intenção. Duas fontes escrevendo a mesma URL, cada uma
 * desfazendo a outra, produzem exatamente o que o operador descreveu — a tela
 * piscando e os números trocando sem parar. Aqui quem escreve é uma ação, e o
 * efeito apenas lê.
 */
export function ProvedorContexto({ children }: { children: ReactNode }) {
  const { parametros, assinatura, definir } = useUrlEstado();
  const [estado, setEstado] = useState<SementeContexto>({ mes: "" });
  const [pronto, setPronto] = useState(false);
  const montado = useRef(false);

  const empresasRecurso = useRecurso(() => api.listarEmpresas(), []);

  useEffect(() => {
    if (montado.current) return;
    montado.current = true;
    let bruto: string | null = null;
    try {
      bruto = window.localStorage.getItem(CHAVE_GUARDADO);
    } catch {
      bruto = null;
    }
    setEstado(resolverContexto(parametros.toString(), bruto));
    setPronto(true);
    // Semente única: `parametros` aqui é o da montagem.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // URL explícita vence: chegar com `?mes=` (link de outra tela, deep link,
  // voltar do navegador) adota o recorte. Só lê — nunca reescreve a URL.
  useEffect(() => {
    if (!pronto) return;
    const semente = sementeDaUrl(assinatura);
    if (semente.mes !== undefined) {
      setEstado((atual) => (atual.mes === semente.mes ? atual : { mes: semente.mes as string }));
    }
  }, [assinatura, pronto]);

  // Persistência é efeito colateral de estado, não de URL: sobrevive a
  // recarregar sem disputar com quem manda na barra de endereço.
  useEffect(() => {
    if (!mesValido(estado.mes)) return;
    try {
      window.localStorage.setItem(CHAVE_GUARDADO, JSON.stringify(estado));
    } catch {
      /* modo privado ou cota cheia: a competência segue valendo nesta sessão */
    }
  }, [estado]);

  const definirMes = useCallback(
    (mes: string) => {
      // Teto silencioso: além do mês em andamento não há competência.
      const valido = mesValido(mes) ? mes : mesAtual();
      setEstado((atual) => (atual.mes === valido ? atual : { mes: valido }));
      definir({ [PARAM_MES]: valido });
    },
    [definir]
  );

  const valor = useMemo<ContextoGlobal>(
    () => ({
      mes: estado.mes,
      competencia: paraAPI(estado.mes || null),
      periodo: estado.mes ? intervaloDoMes(estado.mes) : PERIODO_VAZIO,
      empresas: empresasRecurso.dados ?? [],
      carregandoEmpresas: empresasRecurso.carregando,
      pronto: pronto && estado.mes !== "",
      definirMes,
    }),
    [definirMes, empresasRecurso.carregando, empresasRecurso.dados, estado.mes, pronto]
  );

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useContextoGlobal(): ContextoGlobal {
  const valor = useContext(Contexto);
  if (!valor) throw new Error("useContextoGlobal fora do ProvedorContexto");
  return valor;
}
