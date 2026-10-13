"use client";

import { BarraProgresso } from "@/components/ui/Progresso";
import { ROTULO_TIPO, type EstadoTermometro, type TermometroResposta } from "@/lib/types";
import { contagem, numero } from "@/lib/format";
import type { Tom } from "@/lib/estados";

const ESTADO: Record<EstadoTermometro, { rotulo: string; tom: Tom; texto: string }> = {
  sem_historico: { rotulo: "sem histórico", tom: "neutro", texto: "text-tinta-suave" },
  abaixo: { rotulo: "abaixo do ritmo", tom: "espera", texto: "text-espera" },
  no_ritmo: { rotulo: "no ritmo", tom: "ok", texto: "text-ok" },
  acima: { rotulo: "acima do esperado", tom: "info", texto: "text-info" },
};

/**
 * Termômetro de fechamento: quantas notas o mês já tem contra quantas ele
 * deveria ter (mediana do histórico, proporcional ao dia corrido). O contador
 * descobre que falta nota antes de fechar o mês — não depois.
 */
export function Termometro({ dados }: { dados: TermometroResposta | null }) {
  if (!dados) return null;
  const itens = dados.tipos.filter((item) => item.estado !== "sem_historico" || item.capturadas > 0);
  if (itens.length === 0) return null;
  return (
    <div
      aria-label={`Termômetro da competência ${dados.competencia}`}
      className="grid gap-x-6 gap-y-2 rounded-cartao border border-traco bg-superficie px-3.5 py-3 sm:grid-cols-3"
    >
      {itens.map((item) => {
        const estado = ESTADO[item.estado];
        const rotulo = ROTULO_TIPO[item.tipo as keyof typeof ROTULO_TIPO] ?? item.tipo.toUpperCase();
        return (
          <div key={item.tipo} className="min-w-0">
            <p className="nums text-sm text-tinta">
              <span className="font-medium">{rotulo}</span>
              {" "}{numero(item.capturadas)}{" "}
              <span className="text-tinta-suave">
                de {item.estado === "sem_historico" ? "—" : `${numero(item.esperadas_min)}–${numero(item.esperadas_max)}`}
              </span>
              {" "}· <span className={`font-medium ${estado.texto}`}>{estado.rotulo}</span>
            </p>
            {item.estado !== "sem_historico" ? (
              <BarraProgresso
                valor={item.capturadas}
                maximo={Math.max(item.esperadas_max, item.capturadas, 1)}
                tom={estado.tom}
                rotulo={`${rotulo}: ${contagem(item.capturadas, "nota capturada", "notas capturadas")} de ${numero(item.esperadas_min)} a ${numero(item.esperadas_max)} esperadas`}
                className="mt-1"
              />
            ) : (
              <p className="mt-0.5 text-xs text-tinta-fraca">Sem meses anteriores para comparar.</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
