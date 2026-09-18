"use client";

import { mesAtual, mesesAnteriores, ultimosMeses } from "@/lib/competencia";
import {
  intervaloDoMes,
  mesDoIntervalo,
  type Periodo,
} from "@/lib/periodo";

/**
 * Seletor de período — **as duas datas**, sempre.
 *
 * Por que deixou de ser só um `<input type="month">`: o mês fechado resolve o
 * caso comum ("as notas de agosto") e não resolve o resto — conferir uma
 * quinzena, fechar do dia 1 ao dia 20, refazer um intervalo específico. Pior:
 * como o mês era opcional, a tela abria sem filtro nenhum e despejava o acervo
 * inteiro.
 *
 * Então aqui o período é um par de datas obrigatório, com os atalhos de mês
 * por cima: clicar em "08/2026" preenche 01/08/2026 a 31/08/2026 nos dois
 * campos, que continuam editáveis. O que vai para a API é sempre o intervalo —
 * uma forma só, sem ambiguidade entre "mês" e "datas".
 */
export function PeriodoPicker({
  valor,
  aoMudar,
  idPrefixo = "periodo",
}: {
  valor: Periodo;
  aoMudar: (valor: Periodo) => void;
  idPrefixo?: string;
}) {
  const mesSelecionado = mesDoIntervalo(valor);
  const atalhos = ultimosMeses(3);

  function aplicarMes(mes: string) {
    aoMudar(intervaloDoMes(mes));
  }

  return (
    <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
      <label className="text-xs uppercase text-ink-muted" htmlFor={`${idPrefixo}-inicio`}>
        De
        <input
          id={`${idPrefixo}-inicio`}
          type="date"
          value={valor.inicio}
          max={valor.fim || undefined}
          onChange={(e) => aoMudar({ ...valor, inicio: e.target.value })}
          className="input mt-1 block"
          required
        />
      </label>
      <label className="text-xs uppercase text-ink-muted" htmlFor={`${idPrefixo}-fim`}>
        Até
        <input
          id={`${idPrefixo}-fim`}
          type="date"
          value={valor.fim}
          min={valor.inicio || undefined}
          onChange={(e) => aoMudar({ ...valor, fim: e.target.value })}
          className="input mt-1 block"
          required
        />
      </label>

      <div className="flex items-center gap-1 pb-1">
        <button
          type="button"
          onClick={() => aplicarMes(mesesAnteriores(mesSelecionado || mesAtual(), 1))}
          className="btn-icon h-9 w-9"
          title="Mês anterior inteiro"
          aria-label="Mês anterior inteiro"
        >
          ‹
        </button>
        {atalhos.map((mes) => (
          <button
            key={mes}
            type="button"
            onClick={() => aplicarMes(mes)}
            className={
              mesSelecionado === mes
                ? "rounded-lg bg-accent-soft px-2 py-1 font-mono text-xs font-semibold text-accent-deep"
                : "rounded-lg px-2 py-1 font-mono text-xs text-ink-muted hover:bg-surface hover:text-ink"
            }
            title={`Mês inteiro: ${mes.split("-").reverse().join("/")}`}
          >
            {mes.split("-").reverse().join("/")}
          </button>
        ))}
      </div>
    </div>
  );
}
