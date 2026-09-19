"use client";

import { useState } from "react";
import Link from "next/link";
import { cn } from "@/lib/cn";
import { dataHora, numero, tempoDecorrido, tempoRelativo } from "@/lib/format";
import { estadoDaExecucao } from "@/lib/estados";
import type { ExecucaoAoVivo } from "@/lib/types";
import { ROTULO_TIPO, type TipoDocumentoFiscal } from "@/lib/types";
import { Dado } from "@/components/ui/Dado";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { useAgora } from "@/components/shell/ProvedorAgora";

export interface LinhaExecucaoProps {
  execucao: ExecucaoAoVivo;
  className?: string;
  /** Leva a Importações com empresa, tipo e período já preenchidos. */
  aoReprocessar?: (execucao: ExecucaoAoVivo) => void;
}

/**
 * Resumo primeiro, detalhe técnico só por clique.
 *
 * O operador quer "consultando NFe da Empresa X há 4 min"; `execucao_id`,
 * último NSU e o motivo cru da espera ficam atrás de um `<details>` — úteis
 * para diagnosticar, inúteis para decidir.
 */
export function LinhaExecucao({ execucao, className, aoReprocessar }: LinhaExecucaoProps) {
  const agora = useAgora();
  const [aberto, setAberto] = useState(false);
  const estado = estadoDaExecucao(execucao.status);
  const tipo = ROTULO_TIPO[(execucao.tipo as TipoDocumentoFiscal) ?? "nfe"] ?? execucao.tipo;

  const resumo =
    execucao.status === "em_andamento"
      ? `consultando · ${numero(execucao.documentos_importados)} documentos · desde ${tempoRelativo(execucao.iniciado_em, agora)}`
      : execucao.aguardando_ate
        ? `retoma ${tempoRelativo(execucao.aguardando_ate, agora)}`
        : execucao.mensagem_erro
          ? execucao.mensagem_erro
          : (execucao.aviso ?? estado.rotulo);

  return (
    <li className={cn("border-b border-traco last:border-0", className)}>
      <div className="flex flex-wrap items-start gap-3 px-3 py-2.5">
        <IndicadorEstado {...estado} variante="texto" className="w-44 flex-none" titulo={dataHora(execucao.iniciado_em)} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-tinta-forte" title={execucao.razao_social}>
            {execucao.razao_social}
            <span className="ml-2 text-xs font-normal text-tinta-suave">{tipo}</span>
          </p>
          <p
            className="mt-0.5 truncate text-xs text-tinta-suave"
            title={`${resumo} · duração até agora: ${tempoDecorrido(execucao.iniciado_em, null, agora)}`}
          >
            {resumo}
          </p>
        </div>
        <div className="flex flex-none items-center gap-1">
          {aoReprocessar && execucao.status === "erro" ? (
            <Link
              href={`/dashboard/importacoes?empresa_id=${execucao.empresa_id}&tipo=${execucao.tipo}`}
              onClick={() => aoReprocessar(execucao)}
              className="inline-flex h-8 items-center gap-1.5 rounded-controle border border-borda-controle bg-superficie px-2.5 text-xs font-medium text-tinta transition-colors duration-120 hover:bg-fundo-afundado"
            >
              <Icone nome="atualizar" className="h-3.5 w-3.5" />
              Reprocessar
            </Link>
          ) : null}
          <button
            type="button"
            onClick={() => setAberto((atual) => !atual)}
            aria-expanded={aberto}
            className="inline-flex h-8 items-center gap-1.5 rounded-controle px-2 text-xs font-medium text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta"
          >
            <Icone nome={aberto ? "chevron-cima" : "chevron-baixo"} className="h-3.5 w-3.5" />
            Detalhe
          </button>
        </div>
      </div>

      {aberto ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 border-t border-traco bg-fundo-afundado px-3 py-2.5 text-xs sm:grid-cols-3">
          <Dado quebrar rotulo="Execução" valor={`#${numero(execucao.execucao_id)}`} />
          <Dado quebrar rotulo="Início" valor={dataHora(execucao.iniciado_em)} />
          <Dado quebrar rotulo="Duração" valor={tempoDecorrido(execucao.iniciado_em, null, agora)} />
          <Dado quebrar rotulo="Último NSU" valor={execucao.ultimo_nsu ? numero(Number(execucao.ultimo_nsu)) : "—"} mono />
          <Dado quebrar rotulo="Documentos" valor={numero(execucao.documentos_importados)} />
          <Dado quebrar rotulo="Retoma em" valor={execucao.aguardando_ate ? dataHora(execucao.aguardando_ate) : "—"} />
          {execucao.motivo_espera ? <Dado quebrar rotulo="Motivo da espera" valor={execucao.motivo_espera} largo /> : null}
          {execucao.aviso ? <Dado quebrar rotulo="Aviso" valor={execucao.aviso} largo /> : null}
          {execucao.mensagem_erro ? <Dado quebrar rotulo="Erro" valor={execucao.mensagem_erro} largo tom="erro" /> : null}
        </dl>
      ) : null}
    </li>
  );
}

