"use client";

import { cn } from "@/lib/cn";
import { mesAtual, mesesAnteriores, rotulo as rotuloCompetencia, ultimosMeses } from "@/lib/competencia";
import { BotaoIcone } from "@/components/ui/BotaoIcone";
import { SeletorMes } from "@/components/ui/SeletorData";
import { Icone } from "@/components/ui/Icone";

export interface SeletorCompetenciaProps {
  /** Formato interno AAAA-MM; a API fala MM/AAAA e a tradução vive em lib/competencia. */
  mes: string;
  aoMudar: (mes: string) => void;
  className?: string;
  rotulo?: string;
  /** Últimos N meses como atalho — o fechamento quase sempre olha para trás. */
  atalhos?: number;
  descricao?: string;
}

/** Competência sempre MM/AAAA na superfície, com navegação ‹ ›. */
export function SeletorCompetencia({ mes, aoMudar, className, rotulo = "Competência", atalhos = 6, descricao }: SeletorCompetenciaProps) {
  const atual = mes || mesAtual();
  const ehOMesAtual = atual === mesAtual();
  const anoSeguinte = () => {
    const [ano, mesNumero] = atual.split("-").map(Number);
    const data = new Date(ano ?? new Date().getFullYear(), (mesNumero ?? 1) - 1 + 1, 1);
    return `${data.getFullYear()}-${String(data.getMonth() + 1).padStart(2, "0")}`;
  };

  return (
    <div className={cn("min-w-0", className)}>
      <div className="flex flex-wrap items-end gap-2">
        <BotaoIcone
          rotulo="Competência anterior"
          dica="Mês anterior"
          icone={<Icone nome="chevron-esquerda" className="h-4 w-4" />}
          onClick={() => aoMudar(mesesAnteriores(atual, 1))}
          className="mb-0.5"
        />
        <SeletorMes
          className="w-44"
          rotulo={rotulo}
          value={atual}
          max={mesAtual()}
          descricao={descricao}
          onChange={(evento) => aoMudar(evento.target.value)}
        />
        <BotaoIcone
          rotulo="Próxima competência"
          dica={ehOMesAtual ? "Esta é a competência mais recente disponível" : "Próximo mês"}
          icone={<Icone nome="chevron-direita" className="h-4 w-4" />}
          onClick={() => aoMudar(anoSeguinte())}
          disabled={ehOMesAtual}
          className="mb-0.5"
        />
      </div>
      {atalhos > 0 ? (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-tinta-suave">Atalhos</span>
          {ultimosMeses(atalhos).map((opcao) => (
            <button
              key={opcao}
              type="button"
              onClick={() => aoMudar(opcao)}
              aria-pressed={opcao === atual}
              className={cn(
                "nums h-7 rounded-badge border px-2 text-xs transition-colors duration-120",
                opcao === atual
                  ? "border-acento-borda bg-acento-tenue font-medium text-acento-escuro"
                  : "border-traco bg-superficie text-tinta-suave hover:border-traco-forte hover:text-tinta"
              )}
            >
              {rotuloCompetencia(opcao)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
