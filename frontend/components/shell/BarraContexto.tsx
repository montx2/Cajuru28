"use client";

import { useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { formatarCnpjCpf } from "@/lib/format";
import { mesAtual, mesesAnteriores } from "@/lib/competencia";
import { useUrlEstado } from "@/lib/urlEstado";
import { useContextoGlobal } from "./ProvedorContexto";
import { Combobox, type OpcaoCombobox } from "@/components/ui/Combobox";
import { BotaoIcone } from "@/components/ui/BotaoIcone";
import { Icone } from "@/components/ui/Icone";
import { SeletorMes } from "@/components/fiscal/SeletorMes";

function mesSeguinte(mes: string): string {
  const [ano, numero] = mes.split("-").map(Number);
  const data = new Date(ano, numero, 1);
  return `${data.getFullYear()}-${String(data.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * Barra de contexto global: a empresa e o mês que valem para o sistema
 * inteiro, sempre visíveis e a um clique — o recorte "trava" até o operador
 * mudar aqui (persiste no navegador e viaja na URL).
 *
 * Faixa própria, grudada no cabeçalho e com tom distinto do conteúdo: filtro
 * global não pode se parecer com filtro da tela, senão ninguém sabe o escopo
 * do que está vendo. Na ficha da empresa o seletor vira navegação ("ver outra
 * empresa") em vez de filtro — filtrar a ficha por outra empresa seria
 * contradição.
 */
export function BarraContexto() {
  const contexto = useContextoGlobal();
  const caminho = usePathname();
  const router = useRouter();
  const { ler } = useUrlEstado();

  const naFicha = caminho === "/dashboard/empresa";
  const fichaId = naFicha ? ler("id") : "";

  const opcoesEmpresa = useMemo<OpcaoCombobox[]>(() => {
    const opcoes: OpcaoCombobox[] = [
      { valor: "", rotulo: naFicha ? "Ver todas (lista de empresas)" : "Todas as empresas" },
      ...contexto.empresas.map((item) => ({
        valor: String(item.id),
        rotulo: item.razao_social,
        descricao: `${formatarCnpjCpf(item.cnpj_cpf)} · ${item.uf}`,
        termosBusca: item.cnpj_cpf,
      })),
    ];
    // Deep link com empresa fora da lista (inativa, removida): mostra o número
    // em vez de fingir "todas".
    const idForaDaLista = !naFicha && contexto.empresaId !== null && !contexto.empresas.some((item) => item.id === contexto.empresaId);
    if (idForaDaLista) opcoes.push({ valor: String(contexto.empresaId), rotulo: `Empresa #${contexto.empresaId}` });
    return opcoes;
  }, [contexto.empresaId, contexto.empresas, naFicha]);

  const valorEmpresa = naFicha ? fichaId : contexto.empresaId === null ? "" : String(contexto.empresaId);

  function aoMudarEmpresa(valor: string) {
    if (naFicha) {
      router.push(valor ? `/dashboard/empresa?id=${valor}` : "/dashboard/empresas");
      return;
    }
    contexto.definirEmpresa(valor === "" ? null : Number(valor));
  }

  const mes = contexto.mes || mesAtual();
  const noTeto = mes >= mesAtual();

  // Sem blur/transparência de propósito: o diálogo do mês é `fixed` e um filtro
  // no ancestral o prenderia à barra em vez da viewport.
  return (
    <div className="nao-imprimir sticky top-[var(--altura-cabecalho)] z-20 border-b border-acento-borda bg-acento-tenue">
      <div className="mx-auto flex w-full max-w-conteudo flex-wrap items-end gap-x-3 gap-y-2 px-4 py-2 sm:px-6 lg:px-8">
        <div
          className="min-w-52 flex-1 basis-64"
          title={
            naFicha
              ? "Ver a ficha de outra empresa"
              : "Empresa do recorte global: vale para Documentos, Execuções e Atenção até você mudar aqui."
          }
        >
          <Combobox
            rotulo="Empresa"
            placeholder={naFicha ? "Abrir empresa…" : "Todas as empresas"}
            valor={valorEmpresa}
            aoMudar={aoMudarEmpresa}
            opcoes={opcoesEmpresa}
            carregando={contexto.carregandoEmpresas}
            vazio="Nenhuma empresa encontrada pelo nome ou CNPJ."
          />
        </div>
        <div
          className="flex items-end gap-1"
          title="Mês do recorte global: vale para Painel, Documentos, Fechamento e Empresas até você mudar aqui."
        >
          <BotaoIcone
            rotulo="Mês anterior"
            dica="Mês anterior"
            ladoDica="topo"
            icone={<Icone nome="chevron-esquerda" className="h-4 w-4" />}
            onClick={() => contexto.definirMes(mesesAnteriores(mes, 1))}
            className="mb-0.5"
          />
          <SeletorMes rotulo="Mês" value={mes} max={mesAtual()} onChange={contexto.definirMes} className="w-40 sm:w-44" />
          <BotaoIcone
            rotulo="Próximo mês"
            dica={noTeto ? "Este é o mês mais recente disponível" : "Próximo mês"}
            ladoDica="topo"
            icone={<Icone nome="chevron-direita" className="h-4 w-4" />}
            onClick={() => contexto.definirMes(mesSeguinte(mes))}
            disabled={noTeto}
            className="mb-0.5"
          />
        </div>
      </div>
    </div>
  );
}
