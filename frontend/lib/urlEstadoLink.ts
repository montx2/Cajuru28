/**
 * Monta links de navegação que partem do estado atual da URL sem descartar
 * filtros que o operador já escolheu (período, empresa, busca etc.).
 */
export function hrefComEstado(
  caminho: string,
  estadoAtual: string | URLSearchParams,
  mudancas: Record<string, string | number | boolean | null | undefined> = {},
  remover: string[] = []
): string {
  const parametros = new URLSearchParams(typeof estadoAtual === "string" ? estadoAtual : estadoAtual.toString());

  for (const chave of remover) parametros.delete(chave);

  for (const [chave, valor] of Object.entries(mudancas)) {
    if (valor === null || valor === undefined || valor === "" || valor === false) {
      parametros.delete(chave);
    } else {
      parametros.set(chave, String(valor));
    }
  }

  const consulta = parametros.toString();
  return consulta ? `${caminho}?${consulta}` : caminho;
}
