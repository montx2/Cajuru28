"use client";

import { useCallback, useState } from "react";
import { api, urlDaApi } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { dataCurta } from "@/lib/format";
import { estadoDoJobProcuracao, fraseDoCodigoErro, nomeDoAtor } from "@/lib/estados";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { useRecurso } from "@/lib/useRecurso";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { Area, Entrada } from "@/components/ui/Campo";
import { Dado } from "@/components/ui/Dado";
import { Cnpj, DataHora } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Painel } from "@/components/ui/Painel";
import { useToast } from "@/components/ui/Toast";
import type { PassoRoteiro } from "@/lib/types";

interface Props {
  jobId: number | null;
  aoFechar: () => void;
  aoMudar: () => void;
}

/**
 * Detalhe operacional de um processo de autorização.
 *
 * Três coisas convivem aqui, nesta ordem de importância:
 *
 * 1. **o que fazer agora** — o roteiro da fase atual, com a página oficial;
 * 2. **o registro do resultado** — protocolo ou texto que o portal devolveu.
 *    Sem um dos dois a API recusa concluir a fase, e é proposital: "cliquei em
 *    assinar" não é prova de que a Receita registrou a assinatura;
 * 3. **a trilha** — cada transição, quem fez, quando e com qual código.
 */
export function PainelJob({ jobId, aoFechar, aoMudar }: Props) {
  const { usuario, somenteLeitura } = useSessao();
  const { avisar } = useToast();
  const [protocolo, setProtocolo] = useState("");
  const [confirmacao, setConfirmacao] = useState("");
  const [enviando, setEnviando] = useState(false);

  const job = useRecurso(() => (jobId ? api.jobProcuracao(jobId) : Promise.resolve(null)), [jobId]);
  const estacoes = useRecurso(
    () => (jobId ? api.agentesProcuracao() : Promise.resolve([])),
    [jobId]
  );
  const dados = job.dados;

  const executar = useCallback(
    async (acao: () => Promise<unknown>, titulo: string) => {
      setEnviando(true);
      try {
        await acao();
        avisar({ tom: "ok", titulo });
        job.atualizar();
        aoMudar();
        setProtocolo("");
        setConfirmacao("");
      } catch (erro) {
        avisar({ tom: "erro", titulo: "A ação não foi concluída", descricao: mensagemDoErro(erro) });
      } finally {
        setEnviando(false);
      }
    },
    [aoMudar, avisar, job]
  );

  if (!jobId) return null;

  const fase = dados?.fase ?? "outorga";
  const emIntervencao = dados?.status === "intervencao_manual";
  // Em intervenção manual os formulários seguem liberados: o operador pode
  // decidir fazer o ato no portal por conta própria e registrar aqui o que a
  // Receita devolveu (IN RFB 2.320/2026: nada de marco sem confirmação real).
  const podeRegistrarOutorga =
    dados?.status === "aguardando_assinatura" ||
    dados?.status === "preenchendo" ||
    (emIntervencao && fase === "outorga");
  const podeRegistrarAceite =
    dados?.status === "aguardando_validacao" || dados?.status === "validando" || (emIntervencao && fase === "aceite");
  const terminal = dados?.status === "concluido" || dados?.status === "cancelado" || dados?.status === "falhou";
  const esperandoEstacao = dados?.status === "pendente" || dados?.status === "aguardando_agente";
  /** Sem estação viva, "aguardando estação" é promessa que não se cumpre. */
  const semEstacaoUtil = (estacoes.dados ?? []).every(
    (item) => !item.ativo || item.situacao === "revogado" || item.situacao === "offline"
  );

  return (
    <Painel
      aberto={Boolean(jobId)}
      aoFechar={aoFechar}
      titulo={dados ? `Processo #${dados.id}` : "Processo"}
      contexto={
        dados ? (
          <span className="flex flex-wrap items-center gap-2">
            <span className="truncate">{dados.empresa_nome}</span>
            <Cnpj valor={dados.empresa_documento} />
            <IndicadorEstado {...estadoDoJobProcuracao(dados.status)} />
          </span>
        ) : null
      }
      acoes={
        dados && !terminal ? (
          <div className="flex flex-wrap items-center gap-2">
            {emIntervencao ? (
              <Botao
                variante="sutil"
                tamanho="sm"
                disabled={somenteLeitura || enviando}
                title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : "Retoma do ponto exato em que parou"}
                onClick={() => executar(() => api.retomarJobProcuracao(dados.id), "Processo retomado")}
              >
                Retomar
              </Botao>
            ) : (
              <Botao
                variante="sutil"
                tamanho="sm"
                disabled={somenteLeitura || enviando}
                onClick={() =>
                  executar(
                    () => api.intervencaoJobProcuracao(dados.id, "Assumido manualmente pelo operador."),
                    "Processo marcado para intervenção"
                  )
                }
              >
                Assumir
              </Botao>
            )}
            <Botao
              variante="perigo"
              tamanho="sm"
              disabled={somenteLeitura || enviando}
              onClick={() => executar(() => api.cancelarJobProcuracao(dados.id, "Cancelado pelo operador."), "Processo cancelado")}
            >
              Cancelar
            </Botao>
          </div>
        ) : dados && terminal ? (
          <Botao
            variante="sutil"
            tamanho="sm"
            disabled={somenteLeitura || enviando}
            title="Cria um processo novo; este fica no histórico"
            onClick={() => executar(() => api.reprocessarJobProcuracao(dados.id), "Novo processo criado")}
          >
            Reprocessar
          </Botao>
        ) : null
      }
    >
      {job.carregando ? <p className="text-sm text-tinta-suave">Carregando…</p> : null}
      {job.erro ? <Aviso tom="erro" titulo="Não foi possível carregar o processo">{mensagemDoErro(job.erro)}</Aviso> : null}

      {dados ? (
        <div className="space-y-5">
          {dados.mensagem_erro ? (
            <Aviso
              tom={dados.codigo_erro === "PORTAL_ALTERADO" ? "erro" : "espera"}
              icone="alerta"
              titulo={fraseDoCodigoErro(dados.codigo_erro) || "Processo interrompido"}
            >
              {dados.mensagem_erro}
              {dados.codigo_erro ? (
                <span className="mt-1 block font-mono text-2xs text-tinta-fraca">código: {dados.codigo_erro}</span>
              ) : null}
              {dados.codigo_erro === "PORTAL_ALTERADO" ? (
                <span className="mt-1 block text-xs">
                  O adaptador do portal precisa de manutenção. Nenhum job é retomado às cegas — ver docs/PROCURACOES_RFB.md.
                </span>
              ) : null}
            </Aviso>
          ) : null}

          {esperandoEstacao && semEstacaoUtil ? (
            <Aviso tom="espera" icone="trabalhador" titulo="Este processo espera uma estação — e nenhuma está de pé">
              O passo a passo no portal roda num computador com o Cajuru Agent instalado. Duas saídas, escolha uma:
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                <li>
                  instalar o Agent em uma máquina que fica ligada — veja{" "}
                  <a href="/dashboard/procuracoes/estacoes" className="text-acento underline-offset-4 hover:underline">
                    Estações
                  </a>
                  ;
                </li>
                <li>
                  fazer a outorga direto no portal da Receita e registrar aqui o resultado — use{" "}
                  <span className="font-medium">Assumir</span> e depois informe o protocolo que a Receita devolver.
                </li>
              </ul>
            </Aviso>
          ) : null}

          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Dado rotulo="Fase" valor={fase === "outorga" ? "Outorga (cliente)" : "Aceite (contabilidade)"} />
            <Dado rotulo="Etapa" valor={dados.etapa_atual ?? "—"} />
            <Dado rotulo="Modo" valor={dados.modo === "assistido" ? "Assistido" : dados.modo} />
            <Dado rotulo="Outorgado" valor={<Cnpj valor={dados.outorgado_documento} />} />
            <Dado rotulo="Vigência até" valor={dados.vigencia_ate ? dataCurta(dados.vigencia_ate) : "—"} />
            <Dado rotulo="Serviços" valor={dados.escopo_servicos === "ALL" ? "Todos" : `${dados.servicos.length} selecionados`} />
            <Dado rotulo="Tentativas" valor={String(dados.tentativas)} />
            <Dado rotulo="Protocolo" valor={dados.protocolo ?? "—"} mono />
            <Dado
              rotulo="Certificado"
              valor={dados.certificado_thumbprint ? `${dados.certificado_thumbprint.slice(0, 16)}…` : "—"}
              mono
              dica={dados.certificado_thumbprint ?? undefined}
            />
          </dl>

          {!terminal && dados.roteiro.length > 0 ? (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">
                Roteiro — {fase === "outorga" ? "certificado do cliente" : "certificado da contabilidade"}
              </h3>
              <ol className="space-y-2">
                {dados.roteiro.map((passo: PassoRoteiro, indice: number) => {
                  const atual = passo.etapa === dados.etapa_atual;
                  return (
                    <li
                      key={passo.etapa}
                      className={
                        atual
                          ? "rounded-controle border border-acento bg-acento-tenue p-3"
                          : "rounded-controle border border-borda-controle p-3"
                      }
                    >
                      <div className="flex items-start gap-2">
                        <span className="nums mt-0.5 text-xs text-tinta-fraca">{indice + 1}</span>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-tinta">{passo.titulo}</p>
                          <p className="mt-0.5 text-xs leading-5 text-tinta-suave">{passo.instrucao}</p>
                          {passo.url ? (
                            <a
                              href={passo.url}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="mt-1 inline-flex items-center gap-1 text-xs text-acento underline-offset-4 hover:underline"
                            >
                              <Icone nome="externo" className="h-3.5 w-3.5" />
                              Abrir página oficial
                            </a>
                          ) : null}
                          {passo.confirmacao ? (
                            <p className="mt-1 text-2xs text-tinta-fraca">Confirme: {passo.confirmacao}</p>
                          ) : null}
                        </div>
                        <span className="shrink-0 text-2xs uppercase tracking-[.04em] text-tinta-fraca">
                          {passo.executor === "sistema" ? "sistema" : "você"}
                        </span>
                      </div>
                    </li>
                  );
                })}
              </ol>
            </section>
          ) : null}

          {(podeRegistrarOutorga || podeRegistrarAceite) && !somenteLeitura ? (
            <section className="rounded-controle border border-borda-controle p-3">
              <h3 className="text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">
                {podeRegistrarOutorga ? "Registrar a outorga" : "Registrar o aceite"}
              </h3>
              <p className="mt-1 text-xs leading-5 text-tinta-suave">
                {emIntervencao
                  ? "Fez o ato direto no portal da Receita? Informe aqui o que a Receita devolveu — o processo segue do ponto em que está."
                  : "Informe o que o portal devolveu."}{" "}
                Sem protocolo nem texto de confirmação o registro é recusado — é o que impede marcar como
                concluído algo que a Receita não registrou.
              </p>
              <div className="mt-3 space-y-2">
                {podeRegistrarOutorga ? (
                  <Entrada
                    rotulo="Protocolo"
                    placeholder="Ex.: 2026.0009887766"
                    value={protocolo}
                    onChange={(evento) => setProtocolo(evento.target.value)}
                  />
                ) : null}
                <Area
                  rotulo="Texto de confirmação do portal"
                  placeholder={
                    podeRegistrarOutorga
                      ? "Cole a mensagem exibida (ex.: 'Autorização registrada. Situação: Em Análise.')"
                      : "Cole a mensagem exibida (ex.: 'Autorização validada. Situação: Ativa.')"
                  }
                  rows={3}
                  value={confirmacao}
                  onChange={(evento) => setConfirmacao(evento.target.value)}
                />
                <Botao
                  variante="primaria"
                  tamanho="sm"
                  carregando={enviando}
                  disabled={!protocolo.trim() && !confirmacao.trim()}
                  onClick={() =>
                    executar(
                      () =>
                        podeRegistrarOutorga
                          ? api.registrarOutorga(dados.id, {
                              protocolo: protocolo.trim(),
                              confirmacao_portal: confirmacao.trim(),
                            })
                          : api.registrarAceite(dados.id, { confirmacao_portal: confirmacao.trim() }),
                      podeRegistrarOutorga ? "Outorga registrada" : "Autorização ativa"
                    )
                  }
                >
                  {podeRegistrarOutorga ? "Registrar outorga" : "Registrar aceite"}
                </Botao>
              </div>
            </section>
          ) : null}

          {dados.evidencias.length > 0 ? (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">Evidências</h3>
              <ul className="space-y-1">
                {dados.evidencias.map((item) => (
                  <li key={item.id} className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate text-tinta-suave">
                      {item.etapa ?? "—"} · {item.tipo}
                    </span>
                    <a
                      href={urlDaApi(`/procuracoes/jobs/${dados.id}/evidencias/${item.id}`)}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="shrink-0 text-acento underline-offset-4 hover:underline"
                    >
                      abrir
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[.04em] text-tinta-fraca">
              Trilha do processo
            </h3>
            <ol className="space-y-2 border-l border-borda-controle pl-3">
              {dados.eventos.map((evento) => {
                const anterior = evento.status_anterior
                  ? estadoDoJobProcuracao(evento.status_anterior).rotulo
                  : null;
                const novo = evento.status_novo
                  ? estadoDoJobProcuracao(evento.status_novo).rotulo
                  : evento.tipo;
                // A frase do catálogo traduz o código; a mensagem do evento já
                // costuma ser a explicação gravada na hora — não repetir.
                const frase = fraseDoCodigoErro(evento.codigo_erro);
                const mostrarFrase = frase && frase !== evento.mensagem;
                return (
                  <li key={evento.id} className="relative text-xs">
                    <span className="absolute -left-[17px] top-1.5 h-1.5 w-1.5 rounded-full bg-borda-controle" />
                    <p className="text-tinta">
                      {anterior ? (
                        <>
                          <span className="text-tinta-fraca">{anterior}</span>
                          {" → "}
                        </>
                      ) : null}
                      <span className="font-medium">{novo}</span>
                      {evento.codigo_erro ? (
                        <span className="ml-1 font-mono text-2xs text-tinta-fraca">({evento.codigo_erro})</span>
                      ) : null}
                    </p>
                    {mostrarFrase ? <p className="mt-0.5 text-tinta-suave">{frase}</p> : null}
                    {evento.mensagem ? <p className="mt-0.5 text-tinta-suave">{evento.mensagem}</p> : null}
                    <p className="mt-0.5 text-tinta-fraca">
                      <DataHora iso={evento.quando} /> · {nomeDoAtor(evento, usuario?.id ?? null)}
                    </p>
                  </li>
                );
              })}
            </ol>
          </section>
        </div>
      ) : null}
    </Painel>
  );
}
