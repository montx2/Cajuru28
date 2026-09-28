/**
 * Seleção de pasta de certificados (input `webkitdirectory`).
 *
 * O navegador entrega TODOS os arquivos da pasta escolhida — inclusive os de
 * subpastas. O que interessa é só o A1 (.pfx/.p12); o resto (PDFs, planilhas,
 * atalhos) é contado como ignorado e nunca enviado: certificado é ativo
 * crítico, nada sai da máquina do operador sem ser explicitamente um.
 *
 * A pasta também costuma guardar o certificado antigo e o atualizado do mesmo
 * CNPJ. Aqui fica só a versão mais recente de cada CNPJ (data no nome do
 * arquivo primeiro; data de modificação como desempate) — e a troca é
 * devolvida para a tela contar, nunca silenciosa.
 */

/** Espelha `_LIMITE_ARQUIVOS` do contrato (`api/routers/empresas.py`). */
export const LIMITE_CERTIFICADOS_POR_LOTE = 500;

export const EXTENSOES_CERTIFICADO = [".pfx", ".p12"] as const;

export interface SubstituicaoDeVersao {
  /** CNPJ encontrado no nome dos arquivos (com dígitos verificadores válidos). */
  cnpj: string;
  /** A versão que segue no lote — a mais recente da pasta. */
  mantido: File;
  /** Versões deixadas de fora por serem mais antigas. */
  descartados: File[];
}

export interface SelecaoDaPasta {
  /** Apenas os A1 encontrados, um por CNPJ, na ordem em que o navegador listou. */
  certificados: File[];
  /** Quantos arquivos da pasta ficaram de fora por não serem certificado. */
  ignorados: number;
  /** Quantos arquivos ficaram de fora por haver versão mais recente do mesmo CNPJ. */
  substituidos: number;
  /** O detalhe de cada troca, para a tela mostrar o que ficou e o que saiu. */
  substituicoes: SubstituicaoDeVersao[];
}

/**
 * Último CNPJ com dígitos verificadores válidos no nome do arquivo — o mesmo
 * critério de `cnpj_de_nome_arquivo` do backend para casar a senha da
 * planilha. Sem CNPJ válido devolve "" (o arquivo segue no lote; quem valida
 * o conteúdo mesmo é o backend).
 */
export function cnpjDoNome(nomeArquivo: string): string {
  const semExtensao = nomeArquivo.replace(/\.[^.]+$/, "");
  const achados = semExtensao.match(/(?<!\d)\d{14}(?!\d)/g) ?? [];
  const validos = achados.filter((candidato) => cnpjValido(candidato));
  return validos[validos.length - 1] ?? "";
}

function cnpjValido(valor: string): boolean {
  if (/^(\d)\1{13}$/.test(valor)) return false;
  const digitos = valor.split("").map(Number);
  const dv = (base: number[]) => {
    let soma = 0;
    let peso = base.length - 7;
    for (let i = 0; i < base.length; i++) {
      soma += base[i] * peso;
      peso = peso === 2 ? 9 : peso - 1;
    }
    const resto = soma % 11;
    return resto < 2 ? 0 : 11 - resto;
  };
  const [primeiro, segundo] = [digitos[12], digitos[13]];
  return dv(digitos.slice(0, 12)) === primeiro && dv(digitos.slice(0, 13)) === segundo;
}

/**
 * Data declarada no nome (ex.: `empresa_2027-03.pfx`, `x20260212.p12`) como
 * número AAAAMMDD para comparação. Procura só fora dos dígitos de CNPJ, para
 * não confundir "20" de dentro do número com ano. Sem data → 0.
 */
function dataNoNome(nomeArquivo: string): number {
  const semCnpj = nomeArquivo.replace(/\.[^.]+$/, "").replace(/\d{14,}/g, "#");
  let maior = 0;
  for (const achado of semCnpj.matchAll(/(?<!\d)(20\d{2})(?:[-._]?(\d{2}))?(?:[-._]?(\d{2}))?(?!\d)/g)) {
    const [, ano, mes, dia] = achado;
    const numero = Number(ano + (mes ?? "00") + (dia ?? "00"));
    if (numero > maior) maior = numero;
  }
  return maior;
}

/** A mais recente de duas versões: data do nome primeiro, modificação depois. */
function maisRecente(arquivo: File, outro: File, indice: number, indiceOutro: number): File {
  const dataA = dataNoNome(arquivo.name);
  const dataB = dataNoNome(outro.name);
  if (dataA !== dataB) return dataA > dataB ? arquivo : outro;
  if (arquivo.lastModified !== outro.lastModified) {
    return arquivo.lastModified > outro.lastModified ? arquivo : outro;
  }
  // Empate total: fica a que a pasta listou por último.
  return indice > indiceOutro ? arquivo : outro;
}

export function certificadosDaPasta(arquivos: FileList | File[]): SelecaoDaPasta {
  const escolhidos: Array<{ arquivo: File; ordem: number }> = [];
  const grupos = new Map<string, Array<{ arquivo: File; ordem: number }>>();
  let ignorados = 0;
  let ordem = 0;

  for (const arquivo of Array.from(arquivos)) {
    const nome = arquivo.name.toLowerCase();
    const posicao = ordem++;
    if (!EXTENSOES_CERTIFICADO.some((extensao) => nome.endsWith(extensao))) {
      ignorados += 1;
      continue;
    }
    const cnpj = cnpjDoNome(arquivo.name);
    const item = { arquivo, ordem: posicao };
    if (cnpj) {
      const grupo = grupos.get(cnpj);
      if (grupo) grupo.push(item);
      else grupos.set(cnpj, [item]);
    } else {
      // Sem CNPJ no nome não há como saber se é versão: segue como está.
      escolhidos.push(item);
    }
  }

  const substituicoes: SubstituicaoDeVersao[] = [];
  for (const [cnpj, versoes] of grupos) {
    let mantido = versoes[0];
    for (let i = 1; i < versoes.length; i++) {
      const vencedor = maisRecente(versoes[i].arquivo, mantido.arquivo, versoes[i].ordem, mantido.ordem);
      if (vencedor === versoes[i].arquivo) mantido = versoes[i];
    }
    escolhidos.push(mantido);
    if (versoes.length > 1) {
      substituicoes.push({
        cnpj,
        mantido: mantido.arquivo,
        descartados: versoes.filter((v) => v !== mantido).map((v) => v.arquivo),
      });
    }
  }

  // Ordem de aparição na pasta, para a prévia bater com o que o operador vê.
  return {
    certificados: escolhidos.sort((a, b) => a.ordem - b.ordem).map((item) => item.arquivo),
    ignorados,
    substituidos: substituicoes.reduce((total, troca) => total + troca.descartados.length, 0),
    substituicoes,
  };
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
