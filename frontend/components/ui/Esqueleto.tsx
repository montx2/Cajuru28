import { cn } from "@/lib/cn";

/**
 * Esqueleto com a geometria do conteúdo real. Skeleton genérico causa salto de
 * layout e ensina o operador a desconfiar da tela; por isso cada variante abaixo
 * reproduz colunas e linhas do que vai aparecer.
 */

export function Esqueleto({ className = "h-4 w-full" }: { className?: string }) {
  return <div aria-hidden="true" className={cn("esqueleto", className)} />;
}

export interface EsqueletoTabelaProps {
  /** Larguras das colunas reais, em classes Tailwind (`w-24`, `flex-1`…). */
  colunas: string[];
  linhas?: number;
  /** Altura de linha da tabela que vai substituir (compacta = 40 px). */
  alturaLinha?: string;
}

export function EsqueletoTabela({ colunas, linhas = 8, alturaLinha = "h-11" }: EsqueletoTabelaProps) {
  return (
    <div aria-hidden="true" className="w-full">
      <div className={cn("flex items-center gap-3 border-b border-traco bg-fundo-afundado px-3", alturaLinha === "h-10" ? "h-10" : "h-10")}>
        {colunas.map((largura, indice) => (
          <Esqueleto key={`cabecalho-${indice}`} className={cn("h-3", largura)} />
        ))}
      </div>
      {Array.from({ length: linhas }, (_, linha) => (
        <div key={`linha-${linha}`} className={cn("flex items-center gap-3 border-b border-traco px-3 last:border-0", alturaLinha)}>
          {colunas.map((largura, indice) => (
            <Esqueleto key={`celula-${linha}-${indice}`} className={cn("h-3.5", largura)} />
          ))}
        </div>
      ))}
    </div>
  );
}

export function EsqueletoLista({ itens = 5, linhas = 2 }: { itens?: number; linhas?: number }) {
  return (
    <ul aria-hidden="true" className="divide-y divide-traco">
      {Array.from({ length: itens }, (_, indice) => (
        <li key={indice} className="flex gap-3 px-1 py-3">
          <Esqueleto className="h-9 w-9 flex-none rounded-controle" />
          <div className="flex-1 space-y-2">
            {Array.from({ length: linhas }, (_, linha) => (
              <Esqueleto key={linha} className={cn("h-3.5", linha === 0 ? "w-2/5" : "w-4/5")} />
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function EsqueletoBloco({ linhas = 3, className }: { linhas?: number; className?: string }) {
  return (
    <div aria-hidden="true" className={cn("space-y-2", className)}>
      {Array.from({ length: linhas }, (_, indice) => (
        <Esqueleto key={indice} className={cn("h-3.5", indice === linhas - 1 ? "w-3/5" : "w-full")} />
      ))}
    </div>
  );
}

/** Número de KPI: reserva o espaço exato do valor para não empurrar o rótulo. */
export function EsqueletoNumero({ className = "h-8 w-24" }: { className?: string }) {
  return <Esqueleto className={className} />;
}
