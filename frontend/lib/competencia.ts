/**
 * Competência = o mês que o contador pede.
 *
 * A API aceita `MM/AAAA`; o `<input type="month">` do navegador fala
 * `AAAA-MM`. Estas duas funções são a única tradução entre os dois formatos no
 * app inteiro — foi assim que "esquecer o mês" deixou de ser possível.
 */

export function paraAPI(valor: string | null): string | undefined {
  if (!valor) return undefined;
  const [ano, mes] = valor.split("-");
  if (!ano || !mes) return undefined;
  return `${mes}/${ano}`;
}

export function daAPI(valor?: string | null): string {
  if (!valor) return "";
  const [mes, ano] = valor.split("/");
  if (ano && mes) return `${ano}-${mes.padStart(2, "0")}`;
  return "";
}

export function rotulo(valor: string | null): string {
  if (!valor) return "todos os períodos";
  const [ano, mes] = valor.split("-");
  const nome = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
  ][Number(mes) - 1];
  return `${nome ?? mes}/${ano}`;
}

export function mesesAnteriores(valor: string, quantos = 1): string {
  const [ano, mes] = valor.split("-").map(Number);
  const data = new Date(ano, mes - 1 - quantos, 1);
  return `${data.getFullYear()}-${String(data.getMonth() + 1).padStart(2, "0")}`;
}

export function mesAtual(): string {
  const agora = new Date();
  return `${agora.getFullYear()}-${String(agora.getMonth() + 1).padStart(2, "0")}`;
}

/** Últimos N meses, do mais recente para o mais antigo (o atalho da tela). */
export function ultimosMeses(n: number): string[] {
  const atual = mesAtual();
  return Array.from({ length: n }, (_, i) => mesesAnteriores(atual, i));
}

/** Conta regressiva legível: "libera em 43 min" — o que o operador quer saber. */
export function emQuanto(instanteISO: string | null | undefined, agora = Date.now()): string | null {
  if (!instanteISO) return null;
  const segundos = Math.round((new Date(instanteISO).getTime() - agora) / 1000);
  if (Number.isNaN(segundos) || segundos <= 0) return null;
  if (segundos < 90) return `em ${segundos}s`;
  if (segundos < 90 * 60) return `em ${Math.round(segundos / 60)} min`;
  return `em ${Math.round(segundos / 3600)} h`;
}

export function horaLocal(iso: string | null | undefined): string {
  if (!iso) return "—";
  const data = new Date(iso);
  return Number.isNaN(data.getTime())
    ? "—"
    : data.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function bytesParaTexto(quantidade: number): string {
  if (quantidade < 1024) return `${quantidade} B`;
  if (quantidade < 1024 * 1024) return `${(quantidade / 1024).toFixed(0)} KB`;
  return `${(quantidade / 1024 / 1024).toFixed(1)} MB`;
}
