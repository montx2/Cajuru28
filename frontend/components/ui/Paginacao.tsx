import { cn } from "@/lib/cn";
import { numero } from "@/lib/format";
import { Botao } from "./Botao";
import { Icone } from "./Icone";

export interface PaginacaoProps {
  total: number;
  /** Quantidade já exibida na tela (offset + tamanho da página). */
  exibidos: number;
  aoCarregarMais?: () => void;
  aoAnterior?: () => void;
  aoProximo?: () => void;
  carregando?: boolean;
  /** Tamanho do passo — aparece no rótulo para o operador saber o que vem. */
  passo?: number;
  className?: string;
  complemento?: React.ReactNode;
}

/**
 * "Mostrando X de Y" antes de qualquer botão: em acervo grande o operador
 * precisa saber se o que ele vê é a página ou o conjunto inteiro.
 */
export function Paginacao({ total, exibidos, aoCarregarMais, aoAnterior, aoProximo, carregando, passo = 500, className, complemento }: PaginacaoProps) {
  const temMais = exibidos < total;
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-3 border-t border-traco px-3 py-2.5 text-xs text-tinta-suave", className)}>
      <p className="nums" role="status" aria-live="polite">
        {total === 0 ? (
          "Nenhum registro"
        ) : (
          <>
            Mostrando <span className="font-medium text-tinta-forte">{numero(Math.min(exibidos, total))}</span> de{" "}
            <span className="font-medium text-tinta-forte">{numero(total)}</span>
          </>
        )}
        {complemento}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {aoAnterior ? (
          <Botao tamanho="sm" variante="sutil" onClick={aoAnterior} disabled={carregando} iconeEsquerda={<Icone nome="chevron-esquerda" className="h-3.5 w-3.5" />}>
            Anterior
          </Botao>
        ) : null}
        {aoCarregarMais && temMais ? (
          <Botao tamanho="sm" variante="secundaria" onClick={aoCarregarMais} carregando={carregando}>
            Carregar mais {passo ? numero(passo) : ""}
          </Botao>
        ) : null}
        {aoProximo ? (
          <Botao tamanho="sm" variante="sutil" onClick={aoProximo} disabled={!temMais || carregando} iconeDireita={<Icone nome="chevron-direita" className="h-3.5 w-3.5" />}>
            Próxima
          </Botao>
        ) : null}
      </div>
    </div>
  );
}
