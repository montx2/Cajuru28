"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { PREFIXO_ARMAZENAMENTO } from "@/lib/atalhos";
import { mesAtual, paraAPI } from "@/lib/competencia";
import { PARAM_EMPRESA, PARAM_MES, mesValido, resolverContexto, sementeDaUrl, type SementeContexto } from "@/lib/contexto";
import { PERIODO_VAZIO, intervaloDoMes, type Periodo } from "@/lib/periodo";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import type { Empresa } from "@/lib/types";

const CHAVE_GUARDADO = `${PREFIXO_ARMAZENAMENTO}contexto-global`;

export interface ContextoGlobal {
  /** Empresa do recorte, ou `null` para todas. */
  empresaId: number | null;
  /** Mês de trabalho no formato interno `AAAA-MM` (vazio até `pronto`). */
  mes: string;
  /** O mês na língua da API (`MM/AAAA`). */
  competencia: string | undefined;
  /** O mês como intervalo fechado — o que as telas mandam para a API. */
  periodo: Periodo;
  /** Lista única de empresas: a barra e as telas leem daqui, uma requisição só. */
  empresas: Empresa[];
  carregandoEmpresas: boolean;
  /** Semente resolvida (URL > guardado > padrão) — libera as consultas. */
  pronto: boolean;
  definirEmpresa: (id: number | null) => void;
  definirMes: (mes: string) => void;
}

const Contexto = createContext<ContextoGlobal | null>(null);

/**
 * Fonte única da verdade para empresa + mês em todo o app.
 *
 * - Resolve uma vez ao montar (URL explícita vence o guardado no navegador);
 * - depois, estado e URL andam juntos nos dois sentidos: link com `?mes=09`
 *   aberto de outra tela adota o mês, e mudar na barra reescreve a URL para o
 *   link copiado chegar no mesmo recorte;
 * - persiste no navegador: recarregar ou voltar amanhã mantém o recorte.
 *
 * Não há loop entre os dois efeitos porque cada um só age na divergência: ao
 * adotar, estado iguala a URL; ao espelhar, URL iguala o estado.
 */
export function ProvedorContexto({ children }: { children: ReactNode }) {
  const { parametros, assinatura, definir } = useUrlEstado();
  const [estado, setEstado] = useState<SementeContexto>({ empresaId: null, mes: "" });
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

  // URL explícita vence: chegar com `?mes=`/`?empresa=` (link de outra tela,
  // deep link, voltar do navegador) adota o recorte sem pedir confirmação.
  useEffect(() => {
    if (!pronto) return;
    const semente = sementeDaUrl(parametros.toString());
    if (semente.mes !== undefined && semente.mes !== estado.mes) {
      setEstado((atual) => ({ ...atual, mes: semente.mes as string }));
    }
    if (semente.empresaId !== undefined && semente.empresaId !== estado.empresaId) {
      setEstado((atual) => ({ ...atual, empresaId: semente.empresaId as number | null }));
    }
  }, [assinatura, estado.empresaId, estado.mes, parametros, pronto]);

  // Estado vence de volta: o recorte trabalhado vai para a URL (link
  // compartilhável) e para o guardado (sobrevive ao recarregar).
  useEffect(() => {
    if (!pronto || !mesValido(estado.mes)) return;
    try {
      window.localStorage.setItem(CHAVE_GUARDADO, JSON.stringify(estado));
    } catch {
      /* modo privado ou cota cheia: o recorte segue valendo nesta sessão */
    }
    const mesNaUrl = parametros.get(PARAM_MES);
    const empresaNaUrl = parametros.get(PARAM_EMPRESA);
    const empresaEsperada = estado.empresaId === null ? null : String(estado.empresaId);
    if (mesNaUrl !== estado.mes || empresaNaUrl !== empresaEsperada) {
      definir({ [PARAM_MES]: estado.mes, [PARAM_EMPRESA]: empresaEsperada });
    }
  }, [definir, estado, parametros, pronto]);

  const definirEmpresa = useCallback((id: number | null) => {
    setEstado((atual) => (atual.empresaId === id ? atual : { ...atual, empresaId: id }));
  }, []);

  const definirMes = useCallback((mes: string) => {
    // Teto silencioso: além do mês em andamento não há competência.
    const valido = mesValido(mes) ? mes : mesAtual();
    setEstado((atual) => (atual.mes === valido ? atual : { ...atual, mes: valido }));
  }, []);

  const valor = useMemo<ContextoGlobal>(
    () => ({
      empresaId: estado.empresaId,
      mes: estado.mes,
      competencia: paraAPI(estado.mes || null),
      periodo: estado.mes ? intervaloDoMes(estado.mes) : PERIODO_VAZIO,
      empresas: empresasRecurso.dados ?? [],
      carregandoEmpresas: empresasRecurso.carregando,
      pronto: pronto && estado.mes !== "",
      definirEmpresa,
      definirMes,
    }),
    [definirEmpresa, definirMes, empresasRecurso.carregando, empresasRecurso.dados, estado, pronto]
  );

  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}

export function useContextoGlobal(): ContextoGlobal {
  const valor = useContext(Contexto);
  if (!valor) throw new Error("useContextoGlobal fora do ProvedorContexto");
  return valor;
}
