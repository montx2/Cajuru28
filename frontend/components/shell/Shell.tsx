"use client";

import { useState, type ReactNode } from "react";
import { usePreferencia } from "@/lib/usePreferencia";
import { ProvedorAgora } from "./ProvedorAgora";
import { ProvedorAlertas } from "./ProvedorAlertas";
import { ProvedorComandos } from "./ProvedorComandos";
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
                    <Header aoAbrirMenu={() => setMenuAberto(true)} />
                    <main id="conteudo" tabIndex={-1} className="min-w-0 flex-1 px-4 py-5 sm:px-6 lg:px-8">
                      <div className="mx-auto w-full max-w-conteudo">{children}</div>
                    </main>
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
