"use client";

import { useCallback, useEffect } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { emQuanto, rotulo as rotuloCompetencia } from "@/lib/competencia";
import { contagemRegressiva, moeda, moedaCompacta, numero, percentual, plural, tempoRelativo } from "@/lib/format";
import { estadoDaExecucao, estadoDoComponente, estadoGeral, compararPorGravidade } from "@/lib/estados";
import { useCompetenciaUrl } from "@/lib/usePeriodoUrl";
import { usePolling } from "@/lib/usePolling";
import { useRecurso } from "@/lib/useRecurso";
import { useAgora } from "@/components/shell/ProvedorAgora";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { CartaoAlerta } from "@/components/fiscal/CartaoAlerta";
import { GraficoBarras, GraficoDonut } from "@/components/fiscal/Graficos";
import { LinhaExecucao } from "@/components/fiscal/LinhaExecucao";
import { SeletorCompetencia } from "@/components/fiscal/SeletorCompetencia";
import { Aviso } from "@/components/ui/Aviso";
import { Botao, BotaoLink } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { EsqueletoBloco, EsqueletoLista } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Cnpj, DataHora, ValorMoeda } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import type { AlertaItem, EmitenteTop, ExecucaoImportacao, JanelaProximaConsulta } from "@/lib/types";

/**
 * Painel: responde "está tudo funcionando?" e "preciso resolver algo?" na dobra.
 *
 * Duas decisões de ritmo: enquanto há execução em andamento o polling cai para
 * 5 s (o operador está olhando a máquina trabalhar) e volta a 30 s no repouso;
 * e a recarga nunca apaga o que está na tela — só acende a barra no topo.
 */
export function Painel() {
  const { mes, competencia, aoMudar, pronto } = useCompetenciaUrl();
  const agora = useAgora();

  const painel = useRecurso(() => api.painelOperacional(), []);
  const central = useRecurso(() => api.centralExecucoes(8), []);
  const alertas = useRecurso(() => api.alertas(), []);
  const evolucao = useRecurso(() => api.evolucao(12), []);
  const kpis = useRecurso(() => api.kpis(competencia), [competencia], { automatico: pronto });
  const porTipo = useRecurso(() => api.porTipo(competencia), [competencia], { automatico: pronto });
  const emitentes = useRecurso(() => api.topEmitentes(competencia, 8), [competencia], { automatico: pronto });

  const emAndamento = painel.dados?.execucoes.em_andamento ?? 0;
  const atualizando =
    painel.atualizando || central.atualizando || alertas.atualizando || kpis.atualizando || evolucao.atualizando || porTipo.atualizando;
  useSinalizarAtualizacao(atualizando);

  const recarregar = useCallback(() => {
    painel.atualizar();
    central.atualizar();
    alertas.atualizar();
  }, [alertas, central, painel]);

  // Execução em andamento = 5 s; repouso = 30 s. Menos que isso só gasta cota.
  usePolling(recarregar, emAndamento > 0 ? 5_000 : 30_000);

  useEffect(() => {
    const titulo = painel.dados ? `Painel · ${painel.dados.status_geral === "operando" ? "tudo em dia" : `${painel.dados.alertas.criticos + painel.dados.alertas.atencao} pendências`}` : "Painel · Fluxa";
    if (typeof document !== "undefined") document.title = titulo;
  }, [painel.dados]);

  if (painel.carregando) {
    return (
      <div className="space-y-6" aria-busy="true">
        <EsqueletoBloco linhas={2} />
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
          {Array.from({ length: 5 }, (_, indice) => (
            <div key={indice} className="rounded-cartao border border-traco bg-superficie p-3.5">
              <EsqueletoBloco linhas={2} />
            </div>
          ))}
        </div>
        <EsqueletoLista itens={4} linhas={3} />
      </div>
    );
  }

  if (painel.erro || !painel.dados) {
    return (
      <EstadoErro
        erro={painel.erro ?? new Error("Painel indisponível")}
        aoTentarNovamente={recarregar}
        contexto="carregar o painel operacional"
      />
    );
  }

  const geral = estadoGeral(painel.dados.status_geral);
  const documentos = painel.dados.documentos;
  const execucoes = painel.dados.execucoes;
  const certificados = painel.dados.certificados;
  const empresas = painel.dados.empresas;
  const indicadores = kpis.dados;
  const pendencias = painel.dados.alertas.criticos + painel.dados.alertas.atencao;

  const itens: KpiProps[] = [
    {
      rotulo: `Documentos em ${rotuloCompetencia(mes || null)}`,
      valor: numero(indicadores?.documentos_mes ?? documentos.mes),
      contexto: indicadores
        ? `${numero(indicadores.documentos_mes_anterior)} no mês anterior`
        : `${numero(documentos.hoje)} hoje · ${numero(documentos.total)} no acervo`,
      variacao: indicadores ? { valor: indicadores.variacao_pct, base: "vs. mês anterior" } : undefined,
      href: `/dashboard/documentos?mes=${mes}`,
      carregando: pronto && kpis.carregando,
      dica: "Documentos fiscais capturados com data de emissão dentro da competência.",
    },
    {
      rotulo: "Valor no mês",
      valor: moeda(indicadores?.valor_mes ?? documentos.valor_mes),
      contexto: `${numero(indicadores?.canceladas_mes ?? 0)} canceladas`,
      carregando: pronto && kpis.carregando,
      href: `/dashboard/relatorios?mes=${mes}`,
      dica: "Somatório do valor total dos documentos da competência, já descontando canceladas.",
    },
    {
      rotulo: "Sem XML completo",
      valor: numero(indicadores?.sem_xml_completo ?? documentos.aguardando_xml_completo),
      tom: (indicadores?.sem_xml_completo ?? documentos.aguardando_xml_completo) > 0 ? "espera" : "ok",
      contexto: "vieram só como resumo",
      href: "/dashboard/documentos?leiaute=resumo",
      dica: "Documentos recebidos em resumo (resNFe). O XML completo é buscado pela chave de acesso.",
    },
    {
      rotulo: "Sincronismo em dia",
      valor: `${numero(empresas.em_dia)}/${numero(empresas.ativas)}`,
      tom: empresas.com_erro_24h > 0 ? "erro" : empresas.aguardando_janela > 0 ? "espera" : "ok",
      contexto:
        execucoes.em_andamento > 0
          ? `${numero(execucoes.em_andamento)} ${plural(execucoes.em_andamento, "execução", "execuções")} agora`
          : execucoes.aguardando > 0
            ? `${numero(execucoes.aguardando)} aguardando janela`
            : "nenhuma execução agora",
      href: "/dashboard/execucoes",
      dica: "Empresas com captura automática em dia sobre as empresas ativas.",
    },
    {
      rotulo: "Certificados",
      valor: certificados.vencidos > 0 ? numero(certificados.vencidos) : numero(certificados.validos),
      tom: certificados.vencidos > 0 ? "erro" : certificados.vencendo > 0 ? "espera" : "ok",
      contexto:
        certificados.vencidos > 0
          ? `${plural(certificados.vencidos, "vencido", "vencidos")} · ${numero(certificados.vencendo)} vencendo`
          : `${numero(certificados.vencendo)} vencendo em 30 dias`,
      href: "/dashboard/certificados",
      dica: "Certificados A1 válidos. Vencido interrompe a captura da empresa.",
    },
  ];

  return (
    <div className="space-y-6">
      <CabecalhoPagina
        titulo="Painel"
        descricao={
          <>
            {geral.resumo}
            {painel.ultimaAtualizacao ? (
              <span className="nums ml-2 text-tinta-fraca">· atualizado {tempoRelativo(new Date(painel.ultimaAtualizacao).toISOString(), agora)}</span>
            ) : null}
          </>
        }
        acima={
          <Aviso
            tom={geral.tom}
            titulo={geral.titulo}
            icone={geral.icone}
            acao={
              pendencias > 0 ? (
                <Link href="/dashboard/atencao" className="text-sm font-medium underline-offset-4 hover:underline">
                  Ver {numero(pendencias)} {plural(pendencias, "item", "itens")}
                </Link>
              ) : undefined
            }
          >
            {painel.dados.mensagem ||
              (geral.tom === "ok"
                ? `Última varredura automática ${documentos.competencia ? `na competência ${rotuloCompetencia(documentos.competencia)}` : "concluída"}.`
                : `Certificados vencidos: ${numero(certificados.vencidos)} · empresas sem certificado: ${numero(empresas.sem_certificado)} · execuções com erro em 24 h: ${numero(execucoes.erros_24h)}.`)}
          </Aviso>
        }
        acoes={
          <BotaoLink variante="primaria" href="/dashboard/importacoes" iconeEsquerda={<Icone nome="importacao" className="h-4 w-4" />}>
            Disparar importação
          </BotaoLink>
        }
      />

      <div className="flex flex-wrap items-end justify-between gap-3">
        <SeletorCompetencia mes={mes} aoMudar={aoMudar} descricao="KPIs e gráficos desta competência" />
        <Botao variante="sutil" tamanho="sm" onClick={recarregar} carregando={atualizando} iconeEsquerda={<Icone nome="atualizar" className="h-3.5 w-3.5" />}>
          Atualizar
        </Botao>
      </div>

      <GradeKpis itens={itens} colunas={5} />

      <div className="grid gap-4 xl:grid-cols-3">
        <Cartao titulo="Evolução dos últimos 12 meses" descricao="Documentos capturados por mês de emissão" className="xl:col-span-2">
          {evolucao.carregando ? (
            <EsqueletoBloco linhas={4} />
          ) : evolucao.erro ? (
            <EstadoErro erro={evolucao.erro} aoTentarNovamente={evolucao.atualizar} contexto="carregar a evolução mensal" />
          ) : evolucao.dados && evolucao.dados.length > 0 ? (
            <GraficoBarras
              titulo="Documentos por mês"
              descricao="Total de documentos capturados nos últimos 12 meses"
              dados={evolucao.dados.map((ponto) => ({ rotulo: ponto.rotulo, valor: ponto.total, titulo: `${ponto.rotulo}: ${numero(ponto.total)} documentos · ${moeda(ponto.valor)}` }))}
            />
          ) : (
            <EstadoVazio inline titulo="Sem histórico ainda" instrucao="A evolução aparece assim que a primeira captura fechar um mês." />
          )}
        </Cartao>

        <Cartao titulo="Documentos por tipo" descricao={mes ? rotuloCompetencia(mes) : undefined}>
          {porTipo.carregando ? (
            <EsqueletoBloco linhas={4} />
          ) : porTipo.erro ? (
            <EstadoErro erro={porTipo.erro} aoTentarNovamente={porTipo.atualizar} contexto="carregar a divisão por tipo" />
          ) : porTipo.dados && porTipo.dados.length > 0 ? (
            <GraficoDonut
              titulo="Participação por tipo de documento"
              descricao="NFS-e, NF-e e CT-e na competência selecionada"
              centro={numero(porTipo.dados.reduce((soma, fatia) => soma + fatia.total, 0))}
              dados={porTipo.dados.map((fatia, indice) => ({
                rotulo: fatia.rotulo,
                valor: fatia.total,
                cor: (["acento", "info", "neutro"] as const)[indice % 3],
              }))}
            />
          ) : (
            <EstadoVazio inline titulo="Nenhum documento nesta competência" instrucao="Escolha outro mês ou dispare a importação." icone="documento" />
          )}
        </Cartao>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Cartao
          titulo="Precisa da sua atenção"
          descricao={pendencias > 0 ? `${numero(pendencias)} ${plural(pendencias, "item", "itens")} em aberto, do mais grave para o menos grave` : "Nada em aberto"}
          acoes={
            <Link href="/dashboard/atencao" className="text-xs font-medium text-acento underline-offset-4 hover:underline">
              Ver todos
            </Link>
          }
        >
          {alertas.carregando ? (
            <EsqueletoLista itens={3} linhas={2} />
          ) : alertas.erro ? (
            <EstadoErro erro={alertas.erro} aoTentarNovamente={alertas.atualizar} contexto="carregar os alertas" />
          ) : alertas.dados && alertas.dados.itens.length > 0 ? (
            <ul className="space-y-2">
              {[...alertas.dados.itens]
                .sort(compararPorGravidade)
                .slice(0, 5)
                .map((alerta: AlertaItem) => (
                  <li key={alerta.id}>
                    <CartaoAlerta alerta={alerta} compacta />
                  </li>
                ))}
            </ul>
          ) : (
            <EstadoVazio inline titulo="Operação em dia" instrucao="Nenhum item exige decisão agora. O painel avisa assim que algo aparecer." icone="verificar-circulo" />
          )}
        </Cartao>

        <Cartao
          titulo="Execuções agora"
          descricao={
            execucoes.em_andamento > 0
              ? `${numero(execucoes.em_andamento)} em andamento · média de ${execucoes.duracao_media_minutos !== null ? numero(execucoes.duracao_media_minutos, 1) : "—"} min`
              : "Nenhuma execução em andamento"
          }
          acoes={
            <Link href="/dashboard/execucoes" className="text-xs font-medium text-acento underline-offset-4 hover:underline">
              Central de execuções
            </Link>
          }
        >
          {central.carregando ? (
            <EsqueletoLista itens={3} linhas={2} />
          ) : central.erro ? (
            <EstadoErro erro={central.erro} aoTentarNovamente={central.atualizar} contexto="carregar as execuções" />
          ) : central.dados && central.dados.agora.length > 0 ? (
            <ul className="divide-y divide-traco rounded-cartao border border-traco bg-superficie">
              {central.dados.agora.slice(0, 4).map((execucao) => (
                <LinhaExecucao key={execucao.execucao_id} execucao={execucao} />
              ))}
            </ul>
          ) : central.dados && central.dados.proximas.length > 0 ? (
            <ProximasJanelas janelas={central.dados.proximas} agora={agora} />
          ) : (
            <EstadoVazio inline titulo="Nada rodando" instrucao="A próxima varredura automática aparece aqui quando começar." icone="execucao" />
          )}

          {central.dados && central.dados.recentes.length > 0 ? (
            <div className="mt-4 border-t border-traco pt-3">
              <p className="mb-2 text-xs font-medium uppercase tracking-[.04em] text-tinta-suave">Últimas execuções</p>
              <ul className="space-y-2.5">
                {central.dados.recentes.slice(0, 4).map((execucao) => (
                  <LinhaExecucaoResumo key={execucao.id} execucao={execucao} />
                ))}
              </ul>
            </div>
          ) : null}
        </Cartao>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Cartao titulo="Maiores emitentes" descricao={mes ? `${rotuloCompetencia(mes)} · documentos tomados` : undefined} className="xl:col-span-2">
          {emitentes.carregando ? (
            <EsqueletoLista itens={5} linhas={1} />
          ) : emitentes.erro ? (
            <EstadoErro erro={emitentes.erro} aoTentarNovamente={emitentes.atualizar} contexto="carregar os maiores emitentes" />
          ) : emitentes.dados && emitentes.dados.length > 0 ? (
            <ListaEmitentes emitentes={emitentes.dados} />
          ) : (
            <EstadoVazio inline titulo="Sem emitentes nesta competência" instrucao="O ranking aparece com os primeiros documentos tomados do mês." icone="grafico-barras" />
          )}
        </Cartao>

        <Cartao
          titulo="Componentes"
          descricao="Infraestrutura que sustenta a captura"
          acoes={
            <Link href="/dashboard/saude" className="text-xs font-medium text-acento underline-offset-4 hover:underline">
              Saúde do sistema
            </Link>
          }
        >
          <ul className="space-y-2.5">
            {painel.dados.componentes.map((componente) => {
              const estado = estadoDoComponente(componente.status);
              return (
                <li key={componente.nome} className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-tinta">{componente.nome}</p>
                    <p className="truncate text-xs text-tinta-suave" title={componente.detalhe}>
                      {componente.detalhe}
                    </p>
                  </div>
                  <IndicadorEstado {...estado} variante="texto" className="flex-none" />
                </li>
              );
            })}
          </ul>

          <div className="mt-4 space-y-2 border-t border-traco pt-3 text-xs text-tinta-suave">
            <p className="flex items-center justify-between gap-2">
              <span>Últimas {plural(painel.dados.ultimas_sincronizacoes.length, "sincronização", "sincronizações")}</span>
              <span className="nums">{numero(painel.dados.ultimas_sincronizacoes.length)}</span>
            </p>
            {painel.dados.ultimas_sincronizacoes.slice(0, 3).map((sincronizacao) => (
              <p key={`${sincronizacao.empresa_id}-${sincronizacao.tipo}`} className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate">{sincronizacao.razao_social}</span>
                <DataHora iso={sincronizacao.finalizado_em ?? sincronizacao.iniciado_em} className="nums flex-none text-tinta-fraca" />
              </p>
            ))}
          </div>
        </Cartao>
      </div>
    </div>
  );
}

function ProximasJanelas({ janelas, agora }: { janelas: JanelaProximaConsulta[]; agora: number }) {
  return (
    <div>
      <EstadoVazio inline titulo="Nada em andamento" instrucao="Estas são as próximas consultas agendadas." icone="ampulheta" />
      <ul className="mt-2 space-y-1.5">
        {janelas.slice(0, 4).map((janela) => (
          <li key={`${janela.empresa_id}-${janela.tipo}`} className="flex items-center justify-between gap-3 rounded-controle border border-traco bg-superficie px-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm text-tinta">{janela.razao_social}</p>
              <p className="truncate text-xs text-tinta-suave">
                {janela.tipo.toUpperCase()} · {janela.bloqueada ? "janela SEFAZ" : `${numero(janela.pendencia)} pendentes`}
              </p>
            </div>
            <span className={cn("nums flex-none text-xs", janela.bloqueada ? "text-espera" : "text-tinta-suave")}>
              {contagemRegressiva(janela.proxima_consulta_em, agora) ?? emQuanto(janela.proxima_consulta_em, agora) ?? "—"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ListaEmitentes({ emitentes }: { emitentes: EmitenteTop[] }) {
  const maximo = Math.max(...emitentes.map((emitente) => emitente.total), 1);
  return (
    <table className="w-full text-sm">
      <caption className="sr-only">Maiores emitentes do período, por quantidade de documentos</caption>
      <thead>
        <tr className="border-b border-traco text-left text-2xs uppercase tracking-[.04em] text-tinta-suave">
          <th scope="col" className="py-2 font-medium">
            Emitente
          </th>
          <th scope="col" className="w-40 py-2 text-right font-medium">
            Documentos
          </th>
          <th scope="col" className="w-32 py-2 text-right font-medium">
            Valor
          </th>
        </tr>
      </thead>
      <tbody>
        {emitentes.map((emitente, indice) => (
          <tr key={`${emitente.documento ?? indice}-${emitente.nome ?? indice}`} className="border-b border-traco last:border-0">
            <th scope="row" className="max-w-0 py-2 pr-3 text-left font-normal">
              <span className="block truncate text-tinta">{emitente.nome ?? "Emitente sem nome"}</span>
              {emitente.documento ? <Cnpj valor={emitente.documento} className="text-xs text-tinta-suave" copiar={false} /> : null}
            </th>
            <td className="py-2 text-right">
              <span className="nums block text-tinta-forte">{numero(emitente.total)}</span>
              <span aria-hidden="true" className="mt-1 block h-1 overflow-hidden rounded-full bg-traco">
                <span className="block h-full rounded-full bg-acento" style={{ width: `${Math.round((emitente.total / maximo) * 100)}%` }} />
              </span>
            </td>
            <td className="nums py-2 text-right text-tinta">
              <ValorMoeda valor={emitente.valor} semSimbolo titulo={moeda(emitente.valor)} />
              <span className="sr-only">{moeda(emitente.valor)}</span>
            </td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="text-xs text-tinta-suave">
          <td colSpan={3} className="pt-2">
            Somatório dos {plural(emitentes.length, "emitente", "emitentes")} com mais documentos · {moedaCompacta(emitentes.reduce((soma, item) => soma + item.valor, 0))} ·{" "}
            {percentual(100, 0)} da amostra exibida
          </td>
        </tr>
      </tfoot>
    </table>
  );
}

function LinhaExecucaoResumo({ execucao }: { execucao: ExecucaoImportacao }) {
  const estado = estadoDaExecucao(execucao.status);
  return (
    <li className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="truncate text-sm text-tinta">{execucao.empresa_razao_social ?? `Empresa #${execucao.empresa_id}`}</p>
        <p className="nums truncate text-xs text-tinta-suave">
          {execucao.tipo.toUpperCase()} · {numero(execucao.documentos_importados)} importados · <DataHora iso={execucao.iniciado_em} />
        </p>
      </div>
      <IndicadorEstado {...estado} variante="texto" className="flex-none" titulo={execucao.mensagem_erro ?? execucao.aviso ?? undefined} />
    </li>
  );
}
