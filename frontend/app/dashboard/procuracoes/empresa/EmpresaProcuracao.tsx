"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { dataCurta, numero } from "@/lib/format";
import { estadoDaAutorizacao, estadoDoJobProcuracao, estadoDoPrazoAceite } from "@/lib/estados";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { useRecurso } from "@/lib/useRecurso";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina } from "@/components/ui/Cartao";
import { Dado } from "@/components/ui/Dado";
import { Cnpj, DataHora } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { useToast } from "@/components/ui/Toast";
import { PainelJob } from "../PainelJob";

/**
 * Ficha de uma empresa no módulo de procurações.
 *
 * Responde, numa tela só: em que situação está a autorização, qual é o prazo,
 * quais serviços foram concedidos, qual certificado está disponível para ela e
 * onde cada tentativa parou.
 */
export function EmpresaProcuracao() {
  const parametros = useSearchParams();
  const empresaId = Number(parametros.get("id") || 0);
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();

  const [jobAberto, setJobAberto] = useState<number | null>(null);
  const [processando, setProcessando] = useState(false);

  const detalhe = useRecurso(
    () => (empresaId ? api.detalheProcuracao(empresaId) : Promise.resolve(null)),
    [empresaId]
  );

  const criar = useCallback(async () => {
    setProcessando(true);
    try {
      const job = await api.criarJobProcuracao(empresaId);
      avisar({ tom: "ok", titulo: `Processo #${job.id} criado` });
      detalhe.atualizar();
      setJobAberto(job.id);
    } catch (erro) {
      avisar({ tom: "erro", titulo: "Não foi possível criar", descricao: mensagemDoErro(erro) });
    } finally {
      setProcessando(false);
    }
  }, [avisar, detalhe, empresaId]);

  if (!empresaId) {
    return (
      <Aviso tom="erro" titulo="Empresa não informada">
        Volte para <Link href="/dashboard/procuracoes" className="underline underline-offset-4">Procurações</Link> e escolha uma empresa.
      </Aviso>
    );
  }

  const dados = detalhe.dados;
  const linha = dados?.empresa;
  const jobAtivo = dados?.jobs.find(
    (job) => !["concluido", "cancelado", "falhou"].includes(job.status)
  );
  const prazo = estadoDoPrazoAceite(linha?.dias_para_aceite ?? null);

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo={linha?.razao_social ?? "Empresa"}
        descricao={
          linha ? (
            <span className="flex flex-wrap items-center gap-2">
              <Cnpj valor={linha.documento} />
              <IndicadorEstado {...estadoDaAutorizacao(linha.situacao)} />
              {prazo ? <IndicadorEstado {...prazo} /> : null}
            </span>
          ) : (
            "Autorização de acesso da Receita Federal"
          )
        }
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="sutil" onClick={detalhe.atualizar} carregando={detalhe.atualizando} iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}>
              Atualizar
            </Botao>
            {jobAtivo ? (
              <Botao variante="primaria" onClick={() => setJobAberto(jobAtivo.id)} iconeEsquerda={<Icone nome="alvo" className="h-4 w-4" />}>
                Abrir processo #{jobAtivo.id}
              </Botao>
            ) : (
              <Botao
                variante="primaria"
                carregando={processando}
                disabled={somenteLeitura}
                title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : "Coloca esta empresa na fila"}
                onClick={criar}
                iconeEsquerda={<Icone nome="fila" className="h-4 w-4" />}
              >
                Preparar autorização
              </Botao>
            )}
          </div>
        }
      />

      {detalhe.erro ? <Aviso tom="erro" titulo="Não foi possível carregar">{mensagemDoErro(detalhe.erro)}</Aviso> : null}

      {linha ? (
        <section className="rounded-cartao border border-traco bg-superficie p-4">
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Dado rotulo="Validade" valor={linha.data_validade ? dataCurta(linha.data_validade) : "—"} destaque />
            <Dado
              rotulo="Dias restantes"
              valor={linha.dias_para_vencer !== null ? numero(linha.dias_para_vencer) : "—"}
              tom={(linha.dias_para_vencer ?? 999) < 0 ? "erro" : (linha.dias_para_vencer ?? 999) <= 30 ? "espera" : undefined}
              destaque
            />
            <Dado rotulo="Protocolo" valor={linha.protocolo ?? "—"} mono />
            <Dado rotulo="Serviços" valor={linha.servicos > 0 ? `${numero(linha.servicos)} concedidos` : "todos"} />
            <Dado rotulo="Origem do dado" valor={linha.origem_dado ?? "—"} />
            <Dado
              rotulo="Sincronizado"
              valor={linha.sincronizado_em ? <DataHora iso={linha.sincronizado_em} /> : "nunca"}
            />
            <Dado
              rotulo="Prazo do aceite"
              valor={linha.prazo_aceite_ate ? dataCurta(linha.prazo_aceite_ate) : "—"}
              tom={(linha.dias_para_aceite ?? 99) <= 3 ? "erro" : undefined}
            />
            <Dado
              rotulo="A1 na frota"
              valor={linha.certificado_disponivel ? "disponível" : "ausente"}
              tom={linha.certificado_disponivel ? "ok" : "erro"}
            />
          </dl>
        </section>
      ) : null}

      {dados && dados.certificados.length > 0 ? (
        <section className="rounded-cartao border border-traco bg-superficie p-4">
          <h2 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Certificados desta empresa</h2>
          <ul className="mt-2 space-y-2">
            {dados.certificados.map((certificado) => (
              <li key={certificado.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-traco pb-2 last:border-0 last:pb-0">
                <div className="min-w-0">
                  <p className="truncate text-sm text-tinta">{certificado.titular_nome ?? certificado.documento}</p>
                  <p className="truncate font-mono text-2xs text-tinta-fraca">
                    {certificado.thumbprint.slice(0, 24)}… · estação {certificado.agente_id}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="nums text-xs text-tinta-suave">
                    {certificado.valido_ate ? dataCurta(certificado.valido_ate) : "—"}
                  </span>
                  <IndicadorEstado
                    tom={certificado.situacao === "disponivel" ? "ok" : "erro"}
                    rotulo={certificado.situacao}
                    icone="certificado"
                  />
                </div>
              </li>
            ))}
          </ul>
          {dados.certificados.length > 1 ? (
            <p className="mt-2 text-xs text-tinta-suave">
              Mais de um certificado vigente para o mesmo CNPJ: o sistema <strong>não escolhe sozinho</strong>. O processo para como intervenção
              manual até alguém fixar qual deve ser usado.
            </p>
          ) : null}
        </section>
      ) : null}

      {dados && dados.permissoes.length > 0 ? (
        <section className="rounded-cartao border border-traco bg-superficie p-4">
          <h2 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Serviços concedidos</h2>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {dados.permissoes.map((permissao) => (
              <li key={permissao.codigo} className="rounded-controle border border-borda-controle px-2 py-0.5 text-xs text-tinta-suave">
                {permissao.rotulo || permissao.codigo}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {dados && dados.jobs.length > 0 ? (
        <section className="rounded-cartao border border-traco bg-superficie p-4">
          <h2 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Processos</h2>
          <ul className="mt-2 space-y-2">
            {dados.jobs.map((job) => (
              <li key={job.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-traco pb-2 last:border-0 last:pb-0">
                <button
                  type="button"
                  onClick={() => setJobAberto(job.id)}
                  className="flex min-w-0 items-center gap-2 text-left underline-offset-4 hover:underline"
                >
                  <span className="nums text-xs text-tinta-fraca">#{job.id}</span>
                  <IndicadorEstado {...estadoDoJobProcuracao(job.status)} />
                </button>
                <span className="text-xs text-tinta-suave">
                  {job.codigo_erro ? <span className="text-erro">{job.codigo_erro} · </span> : null}
                  <DataHora iso={job.criado_em} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <PainelJob jobId={jobAberto} aoFechar={() => setJobAberto(null)} aoMudar={detalhe.atualizar} />
    </div>
  );
}
