"use client";

import { api } from "@/lib/api";
import { useRecurso } from "@/lib/useRecurso";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { EsqueletoBloco } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Icone, type NomeIcone } from "@/components/ui/Icone";
import { Modal } from "@/components/ui/Modal";
import { contagem } from "@/lib/format";
import type { AchadoPenteFino, PenteFinoResposta, SeveridadeAchado } from "@/lib/types";

const SEVERIDADE: Record<SeveridadeAchado, { rotulo: string; tom: "erro" | "espera" | "neutro"; icone: NomeIcone }> = {
  alta: { rotulo: "Trava o fechamento", tom: "erro", icone: "negar" },
  media: { rotulo: "Conferir antes de fechar", tom: "espera", icone: "ampulheta" },
  baixa: { rotulo: "Só registrar", tom: "neutro", icone: "info" },
};

const ACAO_DO_ACHADO: Record<AchadoPenteFino["codigo"], string> = {
  salto_sequencia: "Abrir nota vizinha",
  emitente_estreante: "Abrir nota",
  valor_anomalo: "Abrir nota",
  horario_atipico: "Abrir nota",
  sem_xml: "Abrir nota",
  erro_596: "Abrir nota",
  emitente_sumido: "Ver emitente",
  cancelada_no_mes: "Abrir nota",
};

export interface ModalPenteFinoProps {
  aberto: boolean;
  aoFechar: () => void;
  /** Competência no formato MM/AAAA. */
  competencia: string;
  empresaId?: number;
  aoAbrirDocumento: (id: number) => void;
  aoBuscarXmls?: () => void;
}

/**
 * Auditoria de 1 clique da competência. O modal busca sozinho ao abrir: é
 * leitura pura contra o histórico, não gasta cota da SEFAZ.
 */
export function ModalPenteFino({ aberto, aoFechar, competencia, empresaId, aoAbrirDocumento, aoBuscarXmls }: ModalPenteFinoProps) {
  const auditoria = useRecurso(() => api.penteFino(competencia, empresaId), [aberto, competencia, empresaId], {
    automatico: aberto,
  });

  return (
    <Modal
      aberto={aberto}
      aoFechar={aoFechar}
      titulo={`Pente-fino · ${competencia}`}
      descricao="O mês cruzado contra o histórico: o que falta, o que destoa e se dá para fechar."
      largura="larga"
    >
      {!aberto ? null : auditoria.carregando ? (
        <EsqueletoBloco linhas={8} />
      ) : auditoria.erro ? (
        <EstadoErro erro={auditoria.erro} aoTentarNovamente={auditoria.atualizar} contexto="auditar a competência" />
      ) : auditoria.dados ? (
        <ConteudoPenteFino dados={auditoria.dados} aoAbrirDocumento={aoAbrirDocumento} aoBuscarXmls={aoBuscarXmls} />
      ) : null}
    </Modal>
  );
}

function ConteudoPenteFino({
  dados,
  aoAbrirDocumento,
  aoBuscarXmls,
}: {
  dados: PenteFinoResposta;
  aoAbrirDocumento: (id: number) => void;
  aoBuscarXmls?: () => void;
}) {
  const grupos: SeveridadeAchado[] = ["alta", "media", "baixa"];
  const temSemXml = dados.achados.some((achado) => achado.codigo === "sem_xml" || achado.codigo === "erro_596");
  return (
    <div className="space-y-4">
      <Aviso
        tom={dados.pronta_para_fechar ? "ok" : dados.achados.some((a) => a.severidade === "alta") ? "erro" : "espera"}
        titulo={dados.pronta_para_fechar ? "Pronta para fechar" : `${contagem(dados.achados.length, "achado", "achados")} neste mês`}
        acao={
          !dados.pronta_para_fechar && temSemXml && aoBuscarXmls ? (
            <Botao tamanho="sm" variante="secundaria" onClick={aoBuscarXmls}>
              Buscar XMLs completos
            </Botao>
          ) : undefined
        }
      >
        {dados.pronta_para_fechar
          ? `${contagem(dados.total_documentos, "nota auditada", "notas auditadas")} — nada pendente, nada estranho.`
          : "Confira os grupos abaixo. Abrir a nota leva ao detalhe com a ação certa."}
      </Aviso>

      <ol aria-label="Checklist de fechamento" className="grid gap-2 sm:grid-cols-2">
        {dados.checklist.map((item) => (
          <li
            key={item.codigo}
            className="flex items-start gap-2 rounded-controle border border-traco bg-fundo-afundado px-3 py-2"
          >
            <Icone
              nome={item.ok ? "verificar-circulo" : "negar"}
              className={`mt-0.5 h-4 w-4 flex-none ${item.ok ? "text-ok" : "text-erro"}`}
            />
            <span className="min-w-0 text-sm leading-5">
              <span className="block font-medium text-tinta">{item.rotulo}</span>
              <span className="block text-xs text-tinta-suave">{item.detalhe}</span>
            </span>
          </li>
        ))}
      </ol>

      {grupos.map((severidade) => {
        const achados = dados.achados.filter((achado) => achado.severidade === severidade);
        if (achados.length === 0) return null;
        const grupo = SEVERIDADE[severidade];
        return (
          <section key={severidade} aria-label={grupo.rotulo}>
            <div className="mb-1.5 flex items-center gap-2">
              <Etiqueta tom={grupo.tom}>{grupo.rotulo}</Etiqueta>
              <span className="nums text-xs text-tinta-suave">{contagem(achados.length, "achado", "achados")}</span>
            </div>
            <ul className="space-y-2">
              {achados.map((achado, indice) => (
                <li key={`${achado.codigo}-${indice}`} className="rounded-controle border border-traco px-3 py-2">
                  <p className="text-sm font-medium text-tinta">{achado.titulo}</p>
                  <p className="mt-0.5 text-sm leading-5 text-tinta-suave">{achado.detalhe}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
                    {achado.empresa_razao ? (
                      <span className="text-xs text-tinta-fraca">{achado.empresa_razao}</span>
                    ) : null}
                    {achado.documento_id !== null ? (
                      <Botao
                        variante="link"
                        tamanho="sm"
                        onClick={() => achado.documento_id !== null && aoAbrirDocumento(achado.documento_id)}
                      >
                        {ACAO_DO_ACHADO[achado.codigo]} →
                      </Botao>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
