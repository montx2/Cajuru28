import type { ReactNode } from "react";
import Link from "next/link";
import type { Tom } from "@/lib/estados";
import { cn } from "@/lib/cn";

export interface DadoProps {
  /** Nome do campo, em caixa alta discreta — é o `<dt>`. */
  rotulo: string;
  valor: ReactNode;
  /** Valor em mono tabular: CNPJ, chave, NSU, competência. */
  mono?: boolean;
  /** Número-chave: sobe para 16 px e ganha peso 600. */
  destaque?: boolean;
  /** Tom semântico do valor. Ausente = tinta normal. */
  tom?: Tom;
  /** Complemento curto depois do valor ("em dia", "de 120"). */
  contexto?: string;
  /** Texto longo quebra em vez de ser truncado (mensagem de erro, motivo). */
  quebrar?: boolean;
  /** Ocupa duas colunas do `<dl>` (três a partir de `sm`). */
  largo?: boolean;
  /** Meta dentro de linha de lista: rótulo sem caixa alta e valor em 12 px. */
  compacto?: boolean;
  /** Valor é link interno (ex.: empresa dona do documento). */
  href?: string;
  /** Texto longo em duas linhas antes de cortar, em vez de uma. */
  linhas?: 1 | 2;
  /** `title` explícito; sem ele, valor em string vira title automaticamente. */
  dica?: string;
  className?: string;
}

const COR_TOM: Record<Tom, string> = {
  ok: "text-ok",
  espera: "text-espera",
  erro: "text-erro",
  info: "text-info",
  neutro: "text-tinta-suave",
  acento: "text-acento",
};

/**
 * Par rótulo/valor de uma lista de descrição (`<dl>`).
 *
 * Existia sete vezes no produto, com três nomes (`Dado`, `DadoLote`, `Campo`) e
 * três tratamentos de tom diferentes para o mesmo caso — o operador via a mesma
 * informação com peso e cor distintos conforme a tela. Um único componente: o
 * `<dl>` continua sendo montado pela tela, que é quem sabe quantas colunas cabem.
 */
export function Dado({ rotulo, valor, mono, destaque, tom, contexto, quebrar, largo, compacto, href, linhas = 1, dica, className }: DadoProps) {
  return (
    <div className={cn("min-w-0", largo && "col-span-2 sm:col-span-3", className)}>
      <dt className={cn("text-2xs text-tinta-fraca", !compacto && "uppercase tracking-[.04em]")}>{rotulo}</dt>
      <dd
        className={cn(
          "mt-0.5 nums",
          destaque ? "text-base font-semibold" : compacto ? "text-xs" : "text-sm",
          mono && (destaque ? "font-mono" : "font-mono text-xs"),
          linhas === 2 ? "line-clamp-2 text-xs leading-5" : quebrar ? "break-words" : "truncate",
          tom ? COR_TOM[tom] : destaque ? "text-tinta-forte" : "text-tinta",
        )}
        title={dica ?? (typeof valor === "string" ? valor : undefined)}
      >
        {href ? (
          <Link href={href} className="text-acento underline-offset-4 hover:underline">
            {valor}
          </Link>
        ) : (
          valor
        )}
        {contexto ? <span className="ml-1 text-xs font-normal text-tinta-suave">{contexto}</span> : null}
      </dd>
    </div>
  );
}
