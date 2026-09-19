"use client";

import { useTema, type Tema } from "@/lib/tema";
import { MenuSuspenso } from "@/components/ui/MenuSuspenso";
import type { NomeIcone } from "@/components/ui/Icone";

const OPCOES: Array<{ valor: Tema; rotulo: string; icone: NomeIcone }> = [
  { valor: "claro", rotulo: "Claro", icone: "sol" },
  { valor: "escuro", rotulo: "Escuro", icone: "lua" },
  { valor: "sistema", rotulo: "Seguir o sistema", icone: "monitor" },
];

/** Tema claro e escuro são calibrados separadamente — não é a paleta invertida. */
export function SeletorTema() {
  const { tema, definir } = useTema();
  const atual = OPCOES.find((opcao) => opcao.valor === tema) ?? OPCOES[2];

  return (
    <MenuSuspenso
      rotulo="Tema da interface"
      dica={`Tema: ${atual.rotulo}`}
      icone={atual.icone}
      largura="w-56"
      itens={OPCOES.map((opcao) => ({
        id: opcao.valor,
        rotulo: opcao.rotulo,
        icone: opcao.icone,
        selecionado: opcao.valor === tema,
        aoClicar: () => definir(opcao.valor),
      }))}
    >
      <p className="px-3 pb-1 pt-1.5 text-2xs font-medium uppercase tracking-[.04em] text-tinta-fraca">Aparência</p>
    </MenuSuspenso>
  );
}
