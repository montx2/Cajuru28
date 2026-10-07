import type { FiltrosDocumentos, FiltrosExportacao } from "@/lib/api";

/**
 * Seleções de XML do acervo não levam documentos cancelados.
 *
 * O filtro é enviado tanto para IDs explicitamente marcados quanto para
 * "todas as N" linhas. Assim, uma nota que foi cancelada depois de aparecer
 * na tabela também não entra no pacote por uma corrida de atualização.
 */
function filtrosDaSelecao(filtros: FiltrosDocumentos): FiltrosExportacao {
  return { ...filtros, incluir_canceladas: false };
}

export function filtrosParaBaixarSelecao(
  filtros: FiltrosDocumentos,
  documentoIds: readonly number[]
): FiltrosExportacao {
  return { ...filtrosDaSelecao(filtros), documento_ids: documentoIds.join(",") };
}

/** A seleção de todas as N linhas usa o filtro inteiro, sem as canceladas. */
export function filtrosParaBaixarTudoDoFiltro(filtros: FiltrosDocumentos): FiltrosExportacao {
  return filtrosDaSelecao(filtros);
}
