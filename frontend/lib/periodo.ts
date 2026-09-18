/**
 * Período = o intervalo de datas que o operador pediu.
 *
 * Uma regra só para o app inteiro, porque o filtro precisa significar a mesma
 * coisa na tela de Documentos, na de Importações e em tudo que baixa arquivo.
 * O formato interno é o do `<input type="date">` (AAAA-MM-DD), que é também o
 * que a API aceita — sem conversão pelo caminho, sem "01/08" virar 1 de agosto
 * em uma tela e 8 de janeiro em outra.
 */

import { mesAtual } from "./competencia";

export interface Periodo {
  /** AAAA-MM-DD */
  inicio: string;
  /** AAAA-MM-DD */
  fim: string;
}

export const PERIODO_VAZIO: Periodo = { inicio: "", fim: "" };

/** O período está completo e coerente? É o que libera a busca/importação. */
export function periodoValido(periodo: Periodo): boolean {
  if (!periodo.inicio || !periodo.fim) return false;
  return periodo.inicio <= periodo.fim;
}

/** Por que o período não serve — a frase que aparece embaixo do campo. */
export function erroDoPeriodo(periodo: Periodo): string | null {
  if (!periodo.inicio && !periodo.fim) {
    return "Informe o período: data inicial e data final (ex.: 01/08/2026 a 31/08/2026).";
  }
  if (!periodo.inicio) return "Falta a data inicial do período.";
  if (!periodo.fim) return "Falta a data final do período.";
  if (periodo.inicio > periodo.fim) {
    return "A data inicial é depois da data final — inverta as duas.";
  }
  return null;
}

/** "2026-08" → 01/08/2026 a 31/08/2026 (último dia real, bissexto incluso). */
export function intervaloDoMes(mes: string): Periodo {
  const [ano, mesNumero] = mes.split("-").map(Number);
  if (!ano || !mesNumero) return PERIODO_VAZIO;
  // Dia 0 do mês seguinte = último dia deste mês. Resolve 28/29/30/31 sem tabela.
  const ultimoDia = new Date(ano, mesNumero, 0).getDate();
  const doisDigitos = String(mesNumero).padStart(2, "0");
  return {
    inicio: `${ano}-${doisDigitos}-01`,
    fim: `${ano}-${doisDigitos}-${String(ultimoDia).padStart(2, "0")}`,
  };
}

/** O intervalo é exatamente um mês fechado? Devolve "AAAA-MM"; senão, "". */
export function mesDoIntervalo(periodo: Periodo): string {
  if (!periodoValido(periodo)) return "";
  const mes = periodo.inicio.slice(0, 7);
  const equivalente = intervaloDoMes(mes);
  return equivalente.inicio === periodo.inicio && equivalente.fim === periodo.fim ? mes : "";
}

/** O mês corrente inteiro — o padrão com que as telas abrem. */
export function periodoPadrao(): Periodo {
  return intervaloDoMes(mesAtual());
}

/** 2026-08-05 → 05/08/2026 (para títulos e nomes de arquivo). */
export function dataBR(iso: string): string {
  if (!iso) return "";
  return iso.split("-").reverse().join("/");
}

/** Rótulo do período: "08/2026" quando é o mês fechado, senão "05/08 a 12/08". */
export function rotuloPeriodo(periodo: Periodo): string {
  if (!periodoValido(periodo)) return "período não informado";
  const mes = mesDoIntervalo(periodo);
  if (mes) return mes.split("-").reverse().join("/");
  return `${dataBR(periodo.inicio)} a ${dataBR(periodo.fim)}`;
}

/** Pedaço de nome de arquivo, sem barras: "01-08-2026_a_31-08-2026". */
export function sufixoArquivo(periodo: Periodo): string {
  const mes = mesDoIntervalo(periodo);
  if (mes) return mes.split("-").reverse().join("-");
  return `${periodo.inicio}_a_${periodo.fim}`;
}

/** Os parâmetros que vão para a API — sempre as duas datas, nunca a competência. */
export function paraFiltro(periodo: Periodo): { data_inicio: string; data_fim: string } {
  return { data_inicio: periodo.inicio, data_fim: periodo.fim };
}

/**
 * Lê o período da URL (`?data_inicio=&data_fim=`, ou `?competencia=AAAA-MM`
 * que as telas antigas ainda mandam) e cai no mês atual quando não há nada.
 */
export function periodoDaURL(params: URLSearchParams): Periodo {
  const inicio = params.get("data_inicio") ?? "";
  const fim = params.get("data_fim") ?? "";
  if (inicio && fim) return { inicio, fim };
  const competencia = params.get("competencia");
  if (competencia && /^\d{4}-\d{2}$/.test(competencia)) return intervaloDoMes(competencia);
  return periodoPadrao();
}
