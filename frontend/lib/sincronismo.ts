import { contagemRegressiva } from "./format";

/** Texto do campo de próxima execução, consistente com a chave global de automação. */
export function rotuloProximaVarredura(
  automatica: boolean,
  tick: string | null,
  agora: number
): string {
  if (!automatica) return "não programada";
  if (!tick) return "—";
  return contagemRegressiva(tick, agora) ?? "—";
}
