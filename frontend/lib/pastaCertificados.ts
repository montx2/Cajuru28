/**
 * Seleção de pasta de certificados (input `webkitdirectory`).
 *
 * O navegador entrega TODOS os arquivos da pasta escolhida — inclusive os de
 * subpastas. O que interessa é só o A1 (.pfx/.p12); o resto (PDFs, planilhas,
 * atalhos) é contado como ignorado e nunca enviado: certificado é ativo
 * crítico, nada sai da máquina do operador sem ser explicitamente um.
 */

/** Espelha `_LIMITE_ARQUIVOS` do contrato (`api/routers/empresas.py`). */
export const LIMITE_CERTIFICADOS_POR_LOTE = 200;

export const EXTENSOES_CERTIFICADO = [".pfx", ".p12"] as const;

export interface SelecaoDaPasta {
  /** Apenas os A1 encontrados, na ordem em que o navegador listou. */
  certificados: File[];
  /** Quantos arquivos da pasta ficaram de fora por não serem certificado. */
  ignorados: number;
}

export function certificadosDaPasta(arquivos: FileList | File[]): SelecaoDaPasta {
  const certificados: File[] = [];
  let ignorados = 0;
  for (const arquivo of Array.from(arquivos)) {
    const nome = arquivo.name.toLowerCase();
    if (EXTENSOES_CERTIFICADO.some((extensao) => nome.endsWith(extensao))) {
      certificados.push(arquivo);
    } else {
      ignorados += 1;
    }
  }
  return { certificados, ignorados };
}

/**
 * Atributos não padronizados do seletor de pasta. `webkitdirectory` é o
 * atributo que Chrome, Edge e Safari honram; `directory` é o nome histórico.
 * Firefox ignora os dois e abre o seletor de arquivos — por isso o seletor
 * individual continua existindo ao lado, como caminho garantido.
 */
export const ATRIBUTOS_SELETOR_DE_PASTA = {
  webkitdirectory: "",
  directory: "",
} as unknown as React.InputHTMLAttributes<HTMLInputElement>;
