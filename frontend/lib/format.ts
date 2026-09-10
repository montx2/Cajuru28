/**
 * Formatação pt-BR centralizada: moeda, datas, relativos e clipboard.
 * Uma única definição evita "R$ 1.234,56" numa tela e "1234.56" noutra.
 */

export function moeda(valor: number | null | undefined): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
    valor ?? 0
  );
}

export function moedaCompacta(valor: number | null | undefined): string {
  const v = valor ?? 0;
  if (Math.abs(v) >= 1_000_000)
    return `R$ ${(v / 1_000_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mi`;
  if (Math.abs(v) >= 1_000)
    return `R$ ${(v / 1_000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mil`;
  return moeda(v);
}

export function numero(valor: number | null | undefined): string {
  return (valor ?? 0).toLocaleString("pt-BR");
}

export function dataCurta(iso: string | null | undefined): string {
  if (!iso) return "—";
  const data = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(data.getTime()) ? "—" : data.toLocaleDateString("pt-BR");
}

export function mesAno(iso: string | null | undefined): string {
  if (!iso) return "—";
  const data = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  if (Number.isNaN(data.getTime())) return "—";
  return data.toLocaleDateString("pt-BR", { month: "2-digit", year: "numeric" });
}

export function dataHora(iso: string | null | undefined): string {
  if (!iso) return "—";
  const data = new Date(iso);
  return Number.isNaN(data.getTime()) ? "—" : data.toLocaleString("pt-BR");
}

/** "há 5 min", "há 2 h", "há 3 dias", "em 40 min" — o feed de atividades. */
export function tempoRelativo(iso: string | null | undefined, agora = Date.now()): string {
  if (!iso) return "—";
  const alvo = new Date(iso).getTime();
  if (Number.isNaN(alvo)) return "—";
  const diff = Math.round((alvo - agora) / 1000);
  const futuro = diff > 0;
  const abs = Math.abs(diff);
  const un = (v: number, s: string) => `${v} ${s}${v === 1 ? "" : "s"}`;
  let texto: string;
  if (abs < 60) texto = "agora mesmo";
  else if (abs < 3600) texto = un(Math.round(abs / 60), "min");
  else if (abs < 86400) texto = un(Math.round(abs / 3600), "h");
  else if (abs < 86400 * 30) texto = un(Math.round(abs / 86400), "dia");
  else return dataCurta(iso);
  if (texto === "agora mesmo") return texto;
  return futuro ? `em ${texto}` : `há ${texto}`;
}

export function saudacao(): string {
  const hora = new Date().getHours();
  if (hora < 6) return "Boa madrugada";
  if (hora < 12) return "Bom dia";
  if (hora < 18) return "Boa tarde";
  return "Boa noite";
}

export function iniciais(nome: string | null | undefined): string {
  const partes = (nome || "?").trim().split(/\s+/);
  if (partes.length === 1) return partes[0].slice(0, 2).toUpperCase();
  return (partes[0][0] + partes[partes.length - 1][0]).toUpperCase();
}

export function formatarCnpjCpf(valor: string | null | undefined): string {
  const digitos = (valor || "").replace(/\D/g, "");
  if (digitos.length === 14) {
    return digitos.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, "$1.$2.$3/$4-$5");
  }
  if (digitos.length === 11) {
    return digitos.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
  }
  return valor || "—";
}

export async function copiarTexto(texto: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(texto);
    return true;
  } catch {
    try {
      const area = document.createElement("textarea");
      area.value = texto;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      document.body.removeChild(area);
      return true;
    } catch {
      return false;
    }
  }
}
