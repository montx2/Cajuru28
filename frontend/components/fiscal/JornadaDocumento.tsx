"use client";

import { useAgora } from "@/components/shell/ProvedorAgora";
import { Aviso } from "@/components/ui/Aviso";
import { DataHora } from "@/components/ui/Formatadores";
import { Icone, type NomeIcone } from "@/components/ui/Icone";
import { cn } from "@/lib/cn";
import { jornadaDoDocumento, janelaDeCancelamento, type EtapaJornada } from "@/lib/estados";
import { contagemRegressiva, dataHora } from "@/lib/format";
import type { DocumentoDetalhe } from "@/lib/types";

const MARCA: Record<EtapaJornada["estado"], { icone: NomeIcone; classe: string }> = {
  feita: { icone: "verificar-circulo", classe: "text-ok" },
  pendente: { icone: "ampulheta", classe: "text-espera" },
  falha: { icone: "negar", classe: "text-erro" },
};

/**
 * Linha do tempo da nota: emissão → captura → ciência → XML (→ cancelamento).
 * Nenhum concorrente mostra isto porque todos tratam a nota como linha de
 * tabela; aqui ela tem uma história — e a história diz se dá para escriturar.
 */
export function JornadaDocumento({ documento }: { documento: DocumentoDetalhe }) {
  const etapas = jornadaDoDocumento(documento);
  const agora = useAgora();
  const cancelada = documento.status === "cancelada";
  const janela = cancelada ? null : janelaDeCancelamento(documento.data_emissao, agora);
  const limiteIso = janela ? new Date(janela.ate).toISOString() : null;

  return (
    <div className="space-y-3">
      {janela?.aberta ? (
        <Aviso tom="espera" compacto titulo={`Pode ser cancelada ${contagemRegressiva(limiteIso, agora) ?? ""}`}>
          A janela de 24 h fecha em {dataHora(limiteIso)}. Escriturar agora é arriscado — a nota ainda pode sumir.
        </Aviso>
      ) : null}
      <ol className="space-y-0">
        {etapas.map((etapa, indice) => {
          const marca = MARCA[etapa.estado];
          const ultima = indice === etapas.length - 1;
          return (
            <li key={etapa.codigo} className="relative flex gap-2.5 pb-3 last:pb-0">
              {!ultima ? (
                <span aria-hidden="true" className="absolute left-[7px] top-5 h-[calc(100%-1.25rem)] w-px bg-traco" />
              ) : null}
              <Icone nome={marca.icone} className={cn("mt-0.5 h-4 w-4 flex-none", marca.classe)} />
              <div className="min-w-0 flex-1 text-sm leading-5">
                <p className="text-tinta">
                  <span className="font-medium">{etapa.rotulo}</span>
                  {etapa.quando ? (
                    <span className="text-tinta-suave">
                      {" "}· <DataHora iso={etapa.quando} />
                    </span>
                  ) : null}
                </p>
                {etapa.detalhe ? <p className="text-xs text-tinta-suave">{etapa.detalhe}</p> : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
