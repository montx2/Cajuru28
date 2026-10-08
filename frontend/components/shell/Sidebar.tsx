"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { cn } from "@/lib/cn";
import { numero } from "@/lib/format";
import { GRUPOS, rotaDoCaminho, rotasDoMenu } from "@/lib/rotas";
import { useFocoPreso } from "@/lib/useFocoPreso";
import { Dica } from "@/components/ui/Dica";
import { Icone } from "@/components/ui/Icone";
import { MarcaFluxa } from "@/components/ui/MarcaFluxa";
import { useSessao } from "./ProvedorSessao";
import { useContagemAlertas } from "./ProvedorAlertas";

export interface SidebarProps {
  aberta: boolean;
  aoFechar: () => void;
  colapsada: boolean;
  aoAlternarColapso: () => void;
}

function ConteudoSidebar({ colapsada, aoFechar, aoAlternarColapso }: Omit<SidebarProps, "aberta">) {
  const caminho = usePathname();
  const { papel, usuario } = useSessao();
  const { contagem } = useContagemAlertas();
  const rotas = rotasDoMenu(papel);
  const rotaAtual = rotaDoCaminho(caminho);

  return (
    <div className={cn("vidro-grafite lateral-produto flex h-full flex-col text-sobre-grafite", colapsada && "lateral-colapsada")}>
      <div className={cn("flex h-[72px] flex-none items-center justify-between gap-2 px-5", colapsada && "justify-center px-0")}>
        <Link href="/dashboard" onClick={aoFechar} aria-label="Fluxa — painel operacional" className="flex min-w-0 items-center gap-3 rounded-controle">
          <MarcaFluxa comNome={!colapsada} className="flex-none" />
        </Link>
        {!colapsada ? (
          <button type="button" onClick={aoFechar} aria-label="Fechar menu" className="flex h-10 w-10 flex-none items-center justify-center rounded-controle text-sobre-grafite/70 hover:bg-grafite-hover lg:hidden">
            <Icone nome="fechar" className="h-5 w-5" />
          </button>
        ) : null}
      </div>

      {!colapsada ? (
        <div className="mx-4 mb-2 flex items-center gap-2.5 rounded-lg border border-grafite-traco bg-grafite-alta px-3 py-3">
          <Icone nome="empresa" className="h-4 w-4 flex-none text-sobre-grafite/60" />
          <div className="min-w-0">
            <p className="truncate text-xs font-medium">{usuario?.escritorio_nome || "Meu escritório"}</p>
            <p className="mt-0.5 text-xs text-sobre-grafite/60">Operação fiscal</p>
          </div>
        </div>
      ) : null}

      <nav aria-label="Principal" className="rolagem-fina min-h-0 flex-1 overflow-y-auto px-3 py-4">
        {GRUPOS.map((grupo) => {
          const itens = rotas.filter((rota) => rota.grupo === grupo);
          if (!itens.length) return null;
          return (
            <div key={grupo} className="mb-5 last:mb-0">
              {colapsada ? <div aria-hidden="true" className="mx-3 mb-3 border-t border-grafite-traco" /> : <p className="mb-2 px-3 text-xs font-medium tracking-[.05em] text-sobre-grafite/55">{grupo}</p>}
              <ul className="space-y-1">
                {itens.map((rota) => {
                  // /dashboard não é prefixo ativo de todas as outras telas.
                  const ativo = caminho === rota.caminho || rotaAtual?.pai === rota.caminho || (rota.caminho !== "/dashboard" && caminho.startsWith(`${rota.caminho}/`));
                  const badge = rota.caminho === "/dashboard/atencao" ? contagem : null;
                  const rotulo = rota.caminho === "/dashboard/atencao" ? "Atenção" : rota.titulo;
                  const tomBadge = badge && badge.criticos > 0 ? "bg-erro-tenue text-erro" : badge && badge.atencao > 0 ? "bg-espera-tenue text-espera" : "bg-grafite-hover text-sobre-grafite";
                  const item = (
                    <Link
                      href={rota.caminho}
                      onClick={aoFechar}
                      aria-current={ativo ? "page" : undefined}
                      title={colapsada ? undefined : `${rota.titulo}${rota.tecla ? ` (g ${rota.tecla})` : ""}`}
                      className={cn("flex min-h-10 items-center gap-3 rounded-controle text-sm transition-colors duration-150", colapsada ? "justify-center px-0" : "px-3", ativo ? "item-navegacao-ativo font-medium" : "text-sobre-grafite/70 hover:bg-grafite-hover/60 hover:text-sobre-grafite")}
                    >
                      <Icone nome={rota.icone} className="h-[18px] w-[18px] flex-none" />
                      {colapsada ? <span className="sr-only">{rota.titulo}</span> : (
                        <>
                          <span className="min-w-0 flex-1 truncate">{rotulo}</span>
                          {badge && badge.total > 0 ? <span className={cn("nums flex-none rounded-badge px-2 py-0.5 text-xs font-medium", tomBadge)}>{numero(badge.total)}</span> : null}
                        </>
                      )}
                    </Link>
                  );
                  return <li key={rota.caminho}>{colapsada ? <Dica texto={rota.titulo} lado="direita" className="w-full">{item}</Dica> : item}</li>;
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className="mx-3 hidden flex-none border-t border-grafite-traco py-3 lg:block">
        <button type="button" onClick={aoAlternarColapso} aria-expanded={!colapsada} aria-label={colapsada ? "Expandir menu" : "Recolher menu"} className={cn("flex min-h-10 w-full items-center gap-3 rounded-controle text-xs text-sobre-grafite/60 transition-colors hover:bg-grafite-hover hover:text-sobre-grafite", colapsada ? "justify-center" : "px-3")}>
          <Icone nome={colapsada ? "chevron-direita" : "chevron-esquerda"} className="h-4 w-4 flex-none" />
          {!colapsada ? <span>Recolher menu</span> : null}
        </button>
      </div>
    </div>
  );
}

export function Sidebar({ aberta, aoFechar, colapsada, aoAlternarColapso }: SidebarProps) {
  const focoMobile = useFocoPreso<HTMLDivElement>({ ativo: aberta, aoFechar });
  useEffect(() => {
    const desktop = window.matchMedia("(min-width: 1024px)");
    function aoRedimensionar() { if (desktop.matches) aoFechar(); }
    desktop.addEventListener("change", aoRedimensionar);
    return () => desktop.removeEventListener("change", aoRedimensionar);
  }, [aoFechar]);

  return (
    <>
      <aside className="nao-imprimir sticky top-0 hidden h-dvh flex-none lg:block">
        <ConteudoSidebar colapsada={colapsada} aoFechar={aoFechar} aoAlternarColapso={aoAlternarColapso} />
      </aside>
      {aberta ? (
        <div className="nao-imprimir fixed inset-0 z-overlay lg:hidden">
          <div aria-hidden="true" className="absolute inset-0 bg-grafite/70 animate-entrar" onClick={aoFechar} />
          <div ref={focoMobile} role="dialog" aria-modal="true" aria-label="Menu de navegação" className="absolute inset-y-0 left-0 h-full animate-deslizar">
            {/* Preferência de colapso vale só no desktop, nunca no menu mobile. */}
            <ConteudoSidebar colapsada={false} aoFechar={aoFechar} aoAlternarColapso={aoAlternarColapso} />
          </div>
        </div>
      ) : null}
    </>
  );
}
