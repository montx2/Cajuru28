"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import { numero } from "@/lib/format";
import { GRUPOS, rotasDoMenu } from "@/lib/rotas";
import { Dica } from "@/components/ui/Dica";
import { Icone } from "@/components/ui/Icone";
import { LogoFluxa } from "@/components/ui/LogoFluxa";
import { useSessao } from "./ProvedorSessao";
import { useContagemAlertas } from "./ProvedorAlertas";

export interface SidebarProps {
  /** Off-canvas abaixo de 1024 px. */
  aberta: boolean;
  aoFechar: () => void;
  colapsada: boolean;
  aoAlternarColapso: () => void;
}

/**
 * Barra lateral grafite de 240 px, colapsável para 56 px.
 *
 * O item ativo é marcado por barra de 2 px + fundo sutil + peso 500 — não por
 * cor berrante: em oito horas de uso, cor gritando no menu vira ruído. O badge
 * de atenção só fica vermelho quando existe crítico; âmbar para o resto.
 */
export function Sidebar({ aberta, aoFechar, colapsada, aoAlternarColapso }: SidebarProps) {
  const caminho = usePathname();
  const { papel } = useSessao();
  const { contagem } = useContagemAlertas();
  const rotas = rotasDoMenu(papel);

  const conteudo = (
    <div className={cn("vidro-grafite flex h-full flex-col text-sobre-grafite", colapsada ? "w-14" : "w-60")}>
      <div className={cn("flex h-14 flex-none items-center gap-2 border-b border-grafite-traco px-3", colapsada && "justify-center px-0")}>
        <span aria-hidden="true" className="flex h-7 w-7 flex-none items-center justify-center rounded-controle border border-grafite-traco bg-grafite-alta text-acento">
          <LogoFluxa className="h-4 w-4" />
        </span>
        {colapsada ? null : (
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold tracking-tight text-sobre-grafite">Fluxa</span>
            <span className="block truncate text-2xs text-sobre-grafite/60">Operação fiscal</span>
          </span>
        )}
        {colapsada ? null : (
          <button
            type="button"
            onClick={aoFechar}
            aria-label="Fechar menu"
            className="-mr-1 flex h-9 w-9 flex-none items-center justify-center rounded-controle text-sobre-grafite/70 transition-colors duration-120 hover:bg-grafite-hover hover:text-sobre-grafite lg:hidden"
          >
            <Icone nome="fechar" className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav aria-label="Principal" className="rolagem-fina min-h-0 flex-1 overflow-y-auto px-2 py-3">
        {GRUPOS.map((grupo) => {
          const itens = rotas.filter((rota) => rota.grupo === grupo);
          if (itens.length === 0) return null;
          return (
            <div key={grupo} className="mb-4 last:mb-0">
              {colapsada ? (
                <div aria-hidden="true" className="mx-2 mb-2 border-t border-grafite-traco" />
              ) : (
                <p className="mb-1 px-3 text-2xs font-medium uppercase tracking-[.04em] text-sobre-grafite/55">{grupo}</p>
              )}
              <ul>
                {itens.map((rota) => {
                  const ativo = caminho === rota.caminho || (rota.pai ? false : caminho.startsWith(`${rota.caminho}/`));
                  const badge = rota.caminho === "/dashboard/atencao" ? contagem : null;
                  const tomBadge = badge && badge.criticos > 0 ? "bg-erro text-white" : badge && badge.atencao > 0 ? "bg-espera text-grafite" : "bg-grafite-hover text-sobre-grafite";
                  const item = (
                    <Link
                      href={rota.caminho}
                      onClick={aoFechar}
                      aria-current={ativo ? "page" : undefined}
                      title={colapsada ? undefined : `${rota.titulo}${rota.tecla ? ` (g ${rota.tecla})` : ""}`}
                      className={cn(
                        "relative mb-0.5 flex min-h-10 items-center gap-3 rounded-controle text-sm transition-colors duration-120",
                        colapsada ? "justify-center px-0" : "px-3",
                        ativo ? "bg-grafite-hover font-medium text-sobre-grafite" : "font-normal text-sobre-grafite/70 hover:bg-grafite-hover/60 hover:text-sobre-grafite"
                      )}
                    >
                      {ativo ? <span aria-hidden="true" className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-acento" /> : null}
                      <Icone nome={rota.icone} className="h-[18px] w-[18px] flex-none" />
                      {colapsada ? (
                        <span className="sr-only">{rota.titulo}</span>
                      ) : (
                        <>
                          <span className="min-w-0 flex-1 truncate">{rota.titulo}</span>
                          {badge && badge.total > 0 ? (
                            <span className={cn("nums flex-none rounded-badge px-1.5 py-0.5 text-2xs font-medium", tomBadge)}>
                              {numero(badge.total)}
                            </span>
                          ) : null}
                        </>
                      )}
                      {badge && badge.criticos > 0 && colapsada ? (
                        <span aria-hidden="true" className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-erro" />
                      ) : null}
                    </Link>
                  );
                  return (
                    <li key={rota.caminho}>
                      {colapsada ? (
                        <Dica texto={rota.titulo} lado="direita" className="w-full">
                          {item}
                        </Dica>
                      ) : (
                        item
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className={cn("hidden flex-none border-t border-grafite-traco p-2 lg:block", colapsada && "flex justify-center")}>
        <button
          type="button"
          onClick={aoAlternarColapso}
          aria-expanded={!colapsada}
          className={cn(
            "flex min-h-10 items-center gap-3 rounded-controle px-3 text-sm text-sobre-grafite/70 transition-colors duration-120 hover:bg-grafite-hover hover:text-sobre-grafite",
            colapsada && "justify-center px-0"
          )}
        >
          <Icone nome={colapsada ? "chevron-direita" : "chevron-esquerda"} className="h-4 w-4 flex-none" />
          {colapsada ? <span className="sr-only">Expandir menu</span> : <span>Recolher menu</span>}
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop: fixa, sem sobrepor conteúdo. */}
      <aside className="nao-imprimir sticky top-0 hidden h-screen flex-none lg:block">{conteudo}</aside>

      {/* Abaixo de 1024 px: off-canvas com overlay e foco devolvido ao abrir. */}
      <div className={cn("nao-imprimir fixed inset-0 z-overlay lg:hidden", aberta ? "block" : "hidden")}>
        <div aria-hidden="true" className="absolute inset-0 bg-grafite/60 animate-entrar" onClick={aoFechar} />
        <div className="absolute inset-y-0 left-0 h-full animate-deslizar">{conteudo}</div>
      </div>
    </>
  );
}
