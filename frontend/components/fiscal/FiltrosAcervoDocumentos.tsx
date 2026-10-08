"use client";

import { Abas } from "@/components/ui/Abas";
import { Botao } from "@/components/ui/Botao";
import type { DirecaoDocumento, TipoDocumentoFiscal } from "@/lib/types";

const TIPOS_DOCUMENTO = [
  { valor: "todos", rotulo: "Todos os tipos" },
  { valor: "nfe", rotulo: "NF-e" },
  { valor: "nfse", rotulo: "NFS-e · serviço" },
  { valor: "cte", rotulo: "CT-e" },
] as const;

const DIRECOES_DOCUMENTO = [
  { valor: "todas", rotulo: "Todas" },
  { valor: "tomada", rotulo: "Entrada / tomada", motivo: "Notas recebidas pela empresa; na NFS-e, são serviços tomados." },
  { valor: "prestada", rotulo: "Saída / prestada", motivo: "Notas emitidas pela empresa; na NFS-e, são serviços prestados." },
] as const;

export interface FiltrosAcervoDocumentosProps {
  tipo: TipoDocumentoFiscal | null;
  direcao: DirecaoDocumento | null;
  aoMudarTipo: (tipo: TipoDocumentoFiscal | null) => void;
  aoMudarDirecao: (direcao: DirecaoDocumento | null) => void;
  filtroAtivo: boolean;
  aoLimpar: () => void;
}

/** Filtros fiscais mais usados, sempre visíveis e combináveis entre si. */
export function FiltrosAcervoDocumentos({ tipo, direcao, aoMudarTipo, aoMudarDirecao, filtroAtivo, aoLimpar }: FiltrosAcervoDocumentosProps) {
  return (
    <section className="min-w-0 border-t border-traco pt-3" aria-label="Filtros por tipo e operação">
      <div className="grid min-w-0 gap-3 xl:grid-cols-2 xl:gap-4">
        <div className="min-w-0">
          <p className="mb-1.5 text-xs font-medium text-tinta-suave">Tipo de documento</p>
          <Abas
            abas={TIPOS_DOCUMENTO.map((opcao) => ({ ...opcao }))}
            valor={tipo ?? "todos"}
            aoMudar={(valor) => aoMudarTipo(valor === "todos" ? null : (valor as TipoDocumentoFiscal))}
            idBase="filtro-acervo-tipo"
            rotulo="Tipo de documento"
            modo="filtros"
            className="w-full"
          />
        </div>

        <div className="min-w-0">
          <p className="mb-1.5 text-xs font-medium text-tinta-suave">Operação</p>
          <Abas
            abas={DIRECOES_DOCUMENTO.map((opcao) => ({ ...opcao }))}
            valor={direcao ?? "todas"}
            aoMudar={(valor) => aoMudarDirecao(valor === "todas" ? null : (valor as DirecaoDocumento))}
            idBase="filtro-acervo-direcao"
            rotulo="Operação do documento"
            modo="filtros"
            className="w-full"
          />
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-2">
        <p className="max-w-leitura text-xs leading-5 text-tinta-suave">
          Combine NFS-e com <span className="font-medium text-tinta">Entrada / tomada</span> para serviços tomados ou com{" "}
          <span className="font-medium text-tinta">Saída / prestada</span> para serviços prestados.
        </p>
        {filtroAtivo ? (
          <Botao variante="link" tamanho="sm" className="flex-none" onClick={aoLimpar}>
            Limpar todos os filtros
          </Botao>
        ) : null}
      </div>
    </section>
  );
}
