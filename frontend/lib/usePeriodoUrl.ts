"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { mesAtual, paraAPI } from "./competencia";
import { PERIODO_VAZIO, intervaloDoMes, periodoPadrao, periodoValido, type Periodo } from "./periodo";
import { useUrlEstado } from "./urlEstado";

export interface PeriodoUrl {
  periodo: Periodo;
  aoMudar: (periodo: Periodo) => void;
  /** O período já está resolvido (URL ou padrão aplicado) — libera a consulta. */
  pronto: boolean;
}

/**
 * Período vivido na URL (`?data_inicio=&data_fim=`).
 *
 * Sem período a API responde 422, então o padrão (mês corrente) é aplicado e
 * escrito na URL — o link copiado de uma tela já chega filtrado. A aplicação
 * acontece depois da montagem: `new Date()` no servidor (UTC) e no navegador
 * (fuso do operador) discordam na virada do mês, e isso viraria erro de
 * hidratação.
 *
 * Também aceita `?mes=AAAA-MM` (o atalho que o Painel e os Relatórios usam
 * nos links de "ver documentos deste mês"): sem isso, quem clicava em
 * "Documentos em agosto/2026" caía na tela de Documentos com `mes` ignorado
 * e `data_inicio`/`data_fim` ausentes — o padrão então virava o mês corrente
 * (ex.: janeiro), mostrando um período completamente diferente do pedido.
 */
export function usePeriodoUrl(padrao: () => Periodo = periodoPadrao): PeriodoUrl {
  const { parametros, assinatura, definir } = useUrlEstado();
  const [montado, setMontado] = useState(false);

  useEffect(() => {
    setMontado(true);
  }, []);

  const daUrl = useMemo<Periodo | null>(() => {
    const inicio = parametros.get("data_inicio") ?? "";
    const fim = parametros.get("data_fim") ?? "";
    if (inicio && fim) return { inicio, fim };

    // Atalho de link (`?mes=AAAA-MM` ou `?competencia=AAAA-MM`): mesmo mês
    // que a competência pedida, sem exigir que quem gera o link monte
    // data_inicio/data_fim manualmente.
    const mes = parametros.get("mes") ?? parametros.get("competencia") ?? "";
    if (/^\d{4}-\d{2}$/.test(mes)) {
      const intervalo = intervaloDoMes(mes);
      if (periodoValido(intervalo)) return intervalo;
    }
    return null;
  }, [assinatura, parametros]);

  useEffect(() => {
    if (!montado || daUrl) return;
    const inicial = padrao();
    definir({ data_inicio: inicial.inicio, data_fim: inicial.fim });
  }, [daUrl, definir, montado, padrao]);

  // O atalho `mes`/`competencia` vira data_inicio/data_fim explícitos na URL
  // assim que resolvido — evita os dois formatos convivendo e divergindo.
  useEffect(() => {
    if (!montado || !daUrl) return;
    const temMes = parametros.get("mes") || parametros.get("competencia");
    const temIntervalo = parametros.get("data_inicio") && parametros.get("data_fim");
    if (temMes && !temIntervalo) {
      definir({ data_inicio: daUrl.inicio, data_fim: daUrl.fim, mes: null, competencia: null });
    }
  }, [daUrl, definir, montado, parametros]);

  const aoMudar = useCallback(
    (proximo: Periodo) => definir({ data_inicio: proximo.inicio, data_fim: proximo.fim, mes: null, competencia: null, pagina: null }),
    [definir]
  );

  const periodo = daUrl ?? (montado ? padrao() : PERIODO_VAZIO);
  return { periodo, aoMudar, pronto: periodoValido(periodo) };
}

export interface CompetenciaUrl {
  /** Formato interno `AAAA-MM` (o `<input type="month">` fala a mesma língua). */
  mes: string;
  /** Formato da API: `MM/AAAA`. */
  competencia: string | undefined;
  aoMudar: (mes: string) => void;
  pronto: boolean;
}

/** Competência vivida na URL (`?mes=AAAA-MM`), com tradução para `MM/AAAA`. */
export function useCompetenciaUrl(): CompetenciaUrl {
  const { parametros, assinatura, definir } = useUrlEstado();
  const [montado, setMontado] = useState(false);

  useEffect(() => {
    setMontado(true);
  }, []);

  const daUrl = useMemo(() => {
    const valor = parametros.get("mes") ?? "";
    return /^\d{4}-\d{2}$/.test(valor) ? valor : "";
  }, [assinatura, parametros]);

  useEffect(() => {
    if (montado && !daUrl) definir({ mes: mesAtual() });
  }, [daUrl, definir, montado]);

  const mes = daUrl || (montado ? mesAtual() : "");
  return {
    mes,
    competencia: paraAPI(mes || null),
    aoMudar: useCallback((proximo: string) => definir({ mes: proximo, pagina: null }), [definir]),
    pronto: mes !== "",
  };
}
