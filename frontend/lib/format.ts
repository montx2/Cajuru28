/**
 * Formatação pt-BR centralizada.
 *
 * Uma definição só para cada representação: se "R$ 1.234,56" aparecesse escrito
 * à mão em dez telas, uma delas acabaria divergindo — e em documento fiscal
 * divergência de formato vira dúvida sobre o valor. Nenhum `toLocaleString`
 * solto em componente.
 */

const moedaInteira = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const numeroInteiro = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

const dataHoraCompleta = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const dataCurtaFormato = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const mesAnoFormato = new Intl.DateTimeFormat("pt-BR", { month: "2-digit", year: "numeric" });

/** "—" para o que não se aplica. Zero real é "0"; ausente é outra coisa. */
export const AUSENTE = "—";

export function moeda(valor: number | null | undefined): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return AUSENTE;
  return moedaInteira.format(valor);
}

/**
 * Separa símbolo, inteiro e centavos para alinhar pela vírgula: em coluna
 * monetária o olho compara magnitudes quando as vírgulas formam uma linha reta.
 *
 * Não reutiliza `Intl` fatiado por vírgula de propósito: o separador entre "R$"
 * e o número muda conforme a versão da ICU (espaço, espaço não separável ou
 * espaço fino) e quebraria a montagem em produção.
 */
export function moedaPartes(valor: number | null | undefined): { simbolo: string; inteiro: string; decimal: string } {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return { simbolo: "", inteiro: AUSENTE, decimal: "" };
  const [inteiroBruto, decimal] = Math.abs(valor).toFixed(2).split(".");
  const inteiro = numeroInteiro.format(Number(inteiroBruto ?? 0));
  return { simbolo: "R$", inteiro: `${valor < 0 ? "−" : ""}${inteiro}`, decimal: decimal ?? "00" };
}

export function moedaCompacta(valor: number | null | undefined): string {
  const v = valor ?? 0;
  if (Math.abs(v) >= 1_000_000_000) return `R$ ${numero(v / 1_000_000_000, 1)} bi`;
  if (Math.abs(v) >= 1_000_000) return `R$ ${numero(v / 1_000_000, 1)} mi`;
  if (Math.abs(v) >= 10_000) return `R$ ${numero(v / 1_000, 0)} mil`;
  return moeda(v);
}

export function numero(valor: number | null | undefined, decimais = 0): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return AUSENTE;
  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: decimais,
    maximumFractionDigits: decimais,
  }).format(valor);
}

export function percentual(valor: number | null | undefined, decimais = 0): string {
  if (valor === null || valor === undefined || Number.isNaN(valor)) return AUSENTE;
  return `${numero(valor, decimais)}%`;
}

/** Data sem hora: 18/09/2026. Aceita AAAA-MM-DD (interpretado ao meio-dia). */
export function dataCurta(iso: string | null | undefined): string {
  const data = normalizarData(iso);
  return data ? dataCurtaFormato.format(data) : AUSENTE;
}

export function mesAno(iso: string | null | undefined): string {
  const data = normalizarData(iso);
  return data ? mesAnoFormato.format(data) : AUSENTE;
}

/** Camada absoluta do tempo: 18/09/2026 14:32:07 — vai em `title` e tooltip. */
export function dataHora(iso: string | null | undefined): string {
  if (!iso) return AUSENTE;
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? AUSENTE : dataHoraCompleta.format(data);
}

/** Camada absoluta curta: 18/09 14:32 — cabe em coluna de tabela densa. */
export function dataHoraCurta(iso: string | null | undefined): string {
  const data = normalizarData(iso);
  if (!data) return AUSENTE;
  return `${dataCurtaFormato.format(data).slice(0, 5)} ${String(data.getHours()).padStart(2, "0")}:${String(
    data.getMinutes()
  ).padStart(2, "0")}`;
}

export function horaMinuto(iso: string | null | undefined): string {
  const data = normalizarData(iso);
  if (!data) return AUSENTE;
  return `${String(data.getHours()).padStart(2, "0")}:${String(data.getMinutes()).padStart(2, "0")}`;
}

function normalizarData(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  // AAAA-MM-DD puro é data civil: parsear como UTC desloca o dia em -3h no BR.
  const data = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(data.getTime()) ? null : data;
}

/** Camada relativa do tempo: "há 6 min", "em 42 min", "agora". */
export function tempoRelativo(iso: string | null | undefined, agora = Date.now()): string {
  const alvo = normalizarData(iso);
  if (!alvo) return AUSENTE;
  const segundos = Math.round((alvo.getTime() - agora) / 1000);
  if (Math.abs(segundos) < 45) return "agora";
  const texto = duracaoCurta(Math.abs(segundos));
  return segundos > 0 ? `em ${texto}` : `há ${texto}`;
}

/** Segundos → "42 min", "3 h 10 min", "12 s". Usado em contagem regressiva. */
export function duracaoCurta(segundos: number): string {
  if (!Number.isFinite(segundos) || segundos < 0) return AUSENTE;
  if (segundos < 60) return `${Math.round(segundos)} s`;
  if (segundos < 3600) return `${Math.round(segundos / 60)} min`;
  const horas = Math.floor(segundos / 3600);
  const minutos = Math.round((segundos % 3600) / 60);
  if (horas < 24) return minutos ? `${horas} h ${minutos} min` : `${horas} h`;
  const dias = Math.floor(horas / 24);
  return dias === 1 ? "1 dia" : `${dias} dias`;
}

/**
 * Contagem regressiva até um instante: "libera em 42 min".
 * Devolve `null` quando o prazo já passou — quem chama decide o rótulo
 * ("liberado"), porque a frase certa depende do contexto.
 */
export function contagemRegressiva(iso: string | null | undefined, agora = Date.now()): string | null {
  if (!iso) return null;
  const segundos = Math.round((new Date(iso).getTime() - agora) / 1000);
  if (Number.isNaN(segundos) || segundos <= 0) return null;
  return `em ${duracaoCurta(segundos)}`;
}

export function tempoDecorrido(iso: string | null | undefined, ate: string | null | undefined = null, agora = Date.now()): string {
  const inicio = normalizarData(iso);
  if (!inicio) return AUSENTE;
  const fim = normalizarData(ate) ?? new Date(agora);
  return duracaoCurta(Math.max(0, (fim.getTime() - inicio.getTime()) / 1000));
}

export function diasEntre(inicioIso: string, fimIso: string): number {
  const a = normalizarData(inicioIso)?.getTime() ?? 0;
  const b = normalizarData(fimIso)?.getTime() ?? 0;
  return Math.round((b - a) / 86_400_000);
}

/** CNPJ 00.000.000/0000-00 e CPF 000.000.000-00. Sem dígitos, devolve "—". */
export function formatarCnpjCpf(valor: string | null | undefined): string {
  const digitos = somenteDigitos(valor);
  if (digitos.length === 14) return digitos.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, "$1.$2.$3/$4-$5");
  if (digitos.length === 11) return digitos.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
  return valor?.trim() || AUSENTE;
}

export function somenteDigitos(valor: string | null | undefined): string {
  return (valor ?? "").replace(/\D/g, "");
}

/** Chave de acesso de 44 dígitos em grupos de 4 — legível e conferível. */
export function chaveEmGrupos(chave: string | null | undefined, grupo = 4): string {
  const digitos = somenteDigitos(chave);
  if (!digitos) return AUSENTE;
  return digitos.replace(new RegExp(`(.{${grupo}})`, "g"), "$1 ").trim();
}

/** NSU e demais cursores: 8 dígitos à esquerda para alinhar em coluna. */
export function nsuFormatado(nsu: string | null | undefined): string {
  const digitos = somenteDigitos(nsu);
  return digitos ? digitos.padStart(8, "0") : AUSENTE;
}

export function bytesParaTexto(quantidade: number | null | undefined): string {
  if (quantidade === null || quantidade === undefined || Number.isNaN(quantidade)) return AUSENTE;
  if (quantidade < 1024) return `${quantidade} B`;
  if (quantidade < 1024 * 1024) return `${numero(quantidade / 1024)} KB`;
  if (quantidade < 1024 * 1024 * 1024) return `${numero(quantidade / 1024 / 1024, 1)} MB`;
  return `${numero(quantidade / 1024 / 1024 / 1024, 2)} GB`;
}

export function iniciais(nome: string | null | undefined): string {
  const partes = (nome ?? "").trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase();
}

/** Plural certo em frase curta: "1 documento" / "12 documentos". */
export function plural(quantidade: number, singular: string, plurals?: string): string {
  return `${numero(quantidade)} ${quantidade === 1 ? singular : (plurals ?? `${singular}s`)}`;
}

export async function copiarTexto(texto: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texto);
      return true;
    }
  } catch {
    /* cai no método legado: contextos sem Clipboard API (http sem TLS) */
  }
  try {
    const area = document.createElement("textarea");
    area.value = texto;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(area);
    return ok;
  } catch {
    return false;
  }
}
