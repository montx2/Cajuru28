import Link from "next/link";
import { cn } from "@/lib/cn";
import { Icone } from "./Icone";

export interface Migalha {
  rotulo: string;
  href?: string;
}

/** Trilha de navegação real (`nav` + `ol`), com a página atual marcada. */
export function Migalhas({ itens, className }: { itens: Migalha[]; className?: string }) {
  if (itens.length === 0) return null;
  return (
    <nav aria-label="Você está aqui" className={cn("mb-2", className)}>
      <ol className="flex flex-wrap items-center gap-1 text-xs text-tinta-suave">
        {itens.map((item, indice) => {
          const ultimo = indice === itens.length - 1;
          return (
            <li key={`${item.rotulo}-${indice}`} className="flex items-center gap-1">
              {item.href && !ultimo ? (
                <Link href={item.href} className="rounded-badge px-1 py-0.5 underline-offset-4 hover:text-tinta hover:underline">
                  {item.rotulo}
                </Link>
              ) : (
                <span aria-current={ultimo ? "page" : undefined} className={cn("px-1 py-0.5", ultimo && "font-medium text-tinta-forte")}>
                  {item.rotulo}
                </span>
              )}
              {!ultimo ? <Icone nome="chevron-direita" className="h-3 w-3 text-tinta-fraca" /> : null}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
