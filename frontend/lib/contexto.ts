import { mesAtual } from "./competencia";

/**
 * Competência global: o mês de trabalho que vale para o sistema inteiro até o
 * operador mudar no cabeçalho.
 *
 * Três regras moram neste arquivo (puro, sem React, para ser testável):
 *  1. o mês nunca passa do mês em andamento — competência futura não existe;
 *  2. a URL explícita (`?mes=`) vence o guardado — é assim que um link
 *     compartilhado abre no mesmo recorte em outro navegador;
 *  3. sem URL e sem guardado, o padrão é o mês corrente.
 *
 * **Empresa não mora aqui.** Recorte por empresa é filtro da tela que precisa
 * dele — `?empresa=` em Documentos, Execuções e Atenção, `?empresa_ids=` na
 * Importação. Enquanto o mesmo parâmetro `empresa` servia à barra fixa e às
 * telas ao mesmo tempo, cada uma escrevia o campo com uma intenção diferente,
 * o valor voltava pelo espelho da URL e a tela ficava piscando e trocando os
 * números sozinha. Um parâmetro, um dono.
 */

export const PARAM_MES = "mes";

export interface SementeContexto {
  /** Formato interno `AAAA-MM`. */
  mes: string;
}

const MES_RE = /^\d{4}-\d{2}$/;

/** `AAAA-MM` bem formado e não futuro. Comparação de string funciona porque o formato é ordenável. */
export function mesValido(mes: string): boolean {
  return MES_RE.test(mes) && mes <= mesAtual();
}

/** Lê `?mes=` cru; o provedor decide contra o guardado e o padrão. */
export function sementeDaUrl(busca: string): { mes?: string } {
  const parametros = new URLSearchParams(busca.startsWith("?") ? busca.slice(1) : busca);
  const semente: { mes?: string } = {};
  const mes = parametros.get(PARAM_MES) ?? "";
  if (mes !== "" && mesValido(mes)) semente.mes = mes;
  return semente;
}

/** Guardado no navegador (`JSON`): tolera tudo que não parseia — volta ao padrão. */
export function lerGuardado(bruto: string | null): Partial<SementeContexto> {
  if (!bruto) return {};
  try {
    const dados = JSON.parse(bruto) as { mes?: unknown; empresaId?: unknown };
    // `empresaId` é lixo de versões anteriores: era da empresa global, que não
    // existe mais. Ignorar mantém quem já usava o sistema sem migração.
    return typeof dados.mes === "string" && mesValido(dados.mes) ? { mes: dados.mes } : {};
  } catch {
    return {};
  }
}

/** Resolve na ordem: URL explícita > guardado > padrão. */
export function resolverContexto(busca: string, brutoGuardado: string | null): SementeContexto {
  const daUrl = sementeDaUrl(busca);
  const guardado = lerGuardado(brutoGuardado);
  return { mes: daUrl.mes ?? guardado.mes ?? mesAtual() };
}
