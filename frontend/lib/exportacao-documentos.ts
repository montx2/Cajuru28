import type { FiltrosDocumentos, FiltrosExportacao } from "@/lib/api";

/**
 * Constrói o pedido de download de uma seleção explícita do acervo.
 *
 * A seleção é a intenção mais específica do operador: se uma nota cancelada
 * recebeu marcação na tabela, ela não pode desaparecer por causa de um filtro
 * genérico de canceladas. Arquivos que não são a nota fiscal inteira (por
 * exemplo, o evento de cancelamento que existe em acervos legados) seguem em
 * `Fluxa/_sem-xml-completo/`, nunca misturados às notas importáveis.
 */
function filtrosDaSelecao(filtros: FiltrosDocumentos): FiltrosExportacao {
  return {
    ...filtros,
    incluir_canceladas: true,
    incluir_incompletos: true,
  };
}

export function filtrosParaBaixarSelecao(
  filtros: FiltrosDocumentos,
  documentoIds: readonly number[]
): FiltrosExportacao {
  return { ...filtrosDaSelecao(filtros), documento_ids: documentoIds.join(",") };
}

/** A seleção de todas as N linhas usa o próprio filtro, sem perder canceladas. */
export function filtrosParaBaixarTudoDoFiltro(filtros: FiltrosDocumentos): FiltrosExportacao {
  return filtrosDaSelecao(filtros);
}
