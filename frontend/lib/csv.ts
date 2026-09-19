/**
 * CSV gerado no navegador (exportar o que está na tela, sem ida ao servidor).
 *
 * Separador `;` e BOM UTF-8: é o que o Excel pt-BR abre sem transformar
 * "1.234,56" em data e sem quebrar acento.
 */

function escapar(valor: string | number | null | undefined): string {
  if (valor === null || valor === undefined) return "";
  const texto = String(valor);
  return /[";\n\r]/.test(texto) ? `"${texto.replace(/"/g, '""')}"` : texto;
}

export function gerarCsv(cabecalho: string[], linhas: Array<Array<string | number | null | undefined>>): string {
  const corpo = [cabecalho, ...linhas].map((linha) => linha.map(escapar).join(";")).join("\r\n");
  return `\uFEFF${corpo}\r\n`;
}

export function baixarArquivoLocal(conteudo: string | Blob, nomeArquivo: string, tipo = "text/csv;charset=utf-8"): void {
  const blob = typeof conteudo === "string" ? new Blob([conteudo], { type: tipo }) : conteudo;
  const url = URL.createObjectURL(blob);
  const ancora = document.createElement("a");
  ancora.href = url;
  ancora.download = nomeArquivo;
  ancora.click();
  // Sem `revokeObjectURL` o blob fica preso ao documento até o reload.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
