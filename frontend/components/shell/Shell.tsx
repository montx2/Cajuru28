"use client";

import { useState, type ReactNode } from "react";
import { usePreferencia } from "@/lib/usePreferencia";
import { ProvedorAgora } from "./ProvedorAgora";
import { ProvedorAlertas } from "./ProvedorAlertas";
import { ProvedorComandos } from "./ProvedorComandos";
import { ProvedorContexto } from "./ProvedorContexto";
import { ProvedorProgresso } from "./BarraAtualizacao";
import { ProvedorSessao } from "./ProvedorSessao";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";
import { ProvedorToast } from "@/components/ui/Toast";

/**
 * Composição do workspace: provedores de sessão, alertas, tema, relógio e
 * comandos por fora; sidebar + header + conteúdo por dentro.
 *
 * A ordem importa. `ProvedorComandos` lê o papel de `ProvedorSessao` para
 * decidir se `g u` (Equipe) existe para quem não é admin — por isso vem depois.
 * `ProvedorContexto` fica por dentro e envolve cabeçalho + conteúdo: a
 * competência é mostrada no cabeçalho e consumida pelas telas.
 */
export function Shell({ children }: { children: ReactNode }) {
  const [menuAberto, setMenuAberto] = useState(false);
  const [colapsada, setColapsada] = usePreferencia<boolean>("menu-colapsado", false);

  return (
    <ProvedorSessao>
      <ProvedorAlertas>
        <ProvedorToast>
          <ProvedorAgora>
            <ProvedorProgresso>
              <ProvedorComandos>
                <div className="flex min-h-screen bg-fundo">
                  <a
                    href="#conteudo"
                    className="sr-only rounded-controle bg-acento px-3 py-2 text-sm font-medium text-acento-contraste focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-pulo"
                  >
                    Pular para o conteúdo
                  </a>

                  <Sidebar
                    aberta={menuAberto}
                    aoFechar={() => setMenuAberto(false)}
                    colapsada={colapsada}
                    aoAlternarColapso={() => setColapsada((atual) => !atual)}
                  />

                  <div className="flex min-w-0 flex-1 flex-col">
                    {/* A competência vive no cabeçalho, então o provedor precisa
                        envolver o `Header` — e não só o conteúdo. */}
                    <ProvedorContexto>
                      <Header aoAbrirMenu={() => setMenuAberto(true)} />
                      <main id="conteudo" tabIndex={-1} className="min-w-0 flex-1 px-4 py-6 outline-none sm:px-6 sm:py-8 lg:px-8">
                        <div className="mx-auto w-full max-w-conteudo">{children}</div>
                      </main>
                    </ProvedorContexto>
                  </div>
                </div>
              </ProvedorComandos>
            </ProvedorProgresso>
          </ProvedorAgora>
        </ProvedorToast>
      </ProvedorAlertas>
    </ProvedorSessao>
  );
}
