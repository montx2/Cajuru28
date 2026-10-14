import { mesAtual } from "./competencia";

/**
 * Contexto global de trabalho: a empresa e o mês que valem para o sistema
 * inteiro até o operador mudar na barra de contexto.
 *
 * Três regras moram neste arquivo (puro, sem React, para ser testável):
 *  1. o mês nunca passa do mês em andamento — competência futura não existe;
 *  2. a URL explícita (`?empresa=&mes=`) vence o guardado — é assim que um
 *     link compartilhado abre no mesmo recorte em outro navegador;
 *  3. sem URL e sem guardado, o padrão é "todas as empresas, mês corrente".
 */

export const PARAM_EMPRESA = "empresa";
export const PARAM_MES = "mes";

export interface SementeContexto {
  empresaId: number | null;
  mes: string;
}

const MES_RE = /^\d{4}-\d{2}$/;

/** `AAAA-MM` bem formado e não futuro. Comparação de string funciona porque o formato é ordenável. */
export function mesValido(mes: string): boolean {
  return MES_RE.test(mes) && mes <= mesAtual();
}

function empresaValida(valor: string | null): number | null {
  if (valor === null || valor === "") return null;
  const id = Number(valor);
  return Number.isInteger(id) && id > 0 ? id : null;
}

/** Lê `?empresa=&mes=` crus; o provedor decide contra o guardado e o padrão. */
export function sementeDaUrl(busca: string): { empresaId?: number | null; mes?: string } {
  const parametros = new URLSearchParams(busca.startsWith("?") ? busca.slice(1) : busca);
  const semente: { empresaId?: number | null; mes?: string } = {};
  if (parametros.has(PARAM_EMPRESA)) semente.empresaId = empresaValida(parametros.get(PARAM_EMPRESA));
  const mes = parametros.get(PARAM_MES) ?? "";
  if (mes !== "" && mesValido(mes)) semente.mes = mes;
  return semente;
}

/** Guardado no navegador (`JSON`): tolera tudo que não Parsear — volta ao padrão. */
export function lerGuardado(bruto: string | null): Partial<SementeContexto> {
  if (!bruto) return {};
  try {
    const dados = JSON.parse(bruto) as Partial<SementeContexto>;
    const saida: Partial<SementeContexto> = {};
    if (typeof dados.empresaId === "number" && Number.isInteger(dados.empresaId) && dados.empresaId > 0) {
      saida.empresaId = dados.empresaId;
    }
    if (typeof dados.mes === "string" && mesValido(dados.mes)) saida.mes = dados.mes;
    return saida;
  } catch {
    return {};
  }
}

/** Resolve na ordem: URL explícita > guardado > padrão. */
export function resolverContexto(busca: string, brutoGuardado: string | null): SementeContexto {
  const daUrl = sementeDaUrl(busca);
  const guardado = lerGuardado(brutoGuardado);
  return {
    empresaId: daUrl.empresaId ?? guardado.empresaId ?? null,
    mes: daUrl.mes ?? guardado.mes ?? mesAtual(),
  };
}
