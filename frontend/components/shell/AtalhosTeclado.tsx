"use client";

import { ATALHOS, type GrupoAtalho } from "@/lib/atalhos";
import { Modal } from "@/components/ui/Modal";
import { useTeclaModificadora } from "@/lib/useTeclaModificadora";

const GRUPOS: GrupoAtalho[] = ["Navegação", "Camadas", "Tabelas", "Tela"];

/** Mapa de atalhos (`?`): tudo que o teclado faz, num lugar só. */
export function AtalhosTeclado({ aberto, aoFechar }: { aberto: boolean; aoFechar: () => void }) {
  const { simbolo } = useTeclaModificadora();

  return (
    <Modal
      aberto={aberto}
      aoFechar={aoFechar}
      titulo="Atalhos de teclado"
      descricao="Tudo aqui funciona sem mouse. `g` seguido de uma letra navega; as demais teclas valem com o foco fora de campos de texto."
      largura="media"
    >
      <div className="space-y-5">
        {GRUPOS.map((grupo) => {
          const atalhos = ATALHOS.filter((atalho) => atalho.grupo === grupo);
          if (atalhos.length === 0) return null;
          return (
            <section key={grupo}>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">{grupo}</h3>
              <table className="w-full text-sm">
                <caption className="sr-only">Atalhos do grupo {grupo}</caption>
                <tbody>
                  {atalhos.map((atalho) => (
                    <tr key={`${grupo}-${atalho.rotulo}`} className="border-b border-traco last:border-0">
                      <th scope="row" className="py-2 pr-4 text-left font-normal text-tinta">
                        {atalho.rotulo}
                      </th>
                      <td className="w-40 py-2 text-right">
                        {atalho.teclas.map((tecla, indice) => (
                          <span key={tecla} className="inline-flex items-center gap-1">
                            {indice > 0 ? <span className="text-xs text-tinta-fraca">+</span> : null}
                            <kbd className="rounded-badge border border-borda-controle bg-fundo-afundado px-1.5 py-0.5 font-mono text-xs text-tinta">
                              {tecla === "Ctrl" ? simbolo : tecla}
                            </kbd>
                          </span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          );
        })}
      </div>
    </Modal>
  );
}
