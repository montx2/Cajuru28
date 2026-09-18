import { cn } from "@/lib/cn";
type Tom = "ok" | "espera" | "erro" | "info" | "neutro";
const classes: Record<Tom, string> = { ok: "text-ok bg-ok-tenue", espera: "text-espera bg-espera-tenue", erro: "text-erro bg-erro-tenue", info: "text-info bg-info-tenue", neutro: "text-neutro bg-neutro-tenue" };
const simbolos: Record<Tom, string> = { ok: "✓", espera: "◷", erro: "×", info: "i", neutro: "•" };
/** Estado nunca depende apenas de cor: símbolo e texto viajam juntos. */
export function IndicadorEstado({ tom, rotulo, className }: { tom: Tom; rotulo: string; className?: string }) {
  return <span className={cn("inline-flex min-h-6 items-center gap-1.5 rounded-sm px-2 text-xs font-medium", classes[tom], className)}><span aria-hidden="true">{simbolos[tom]}</span>{rotulo}</span>;
}
