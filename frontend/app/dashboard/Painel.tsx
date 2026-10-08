"use client";

import { useCallback, useEffect } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { emQuanto, mesesAnteriores, rotulo as rotuloCompetencia } from "@/lib/competencia";
import { contagem, contagemRegressiva, moeda, moedaCompacta, numero, percentual, plural, tempoRelativo } from "@/lib/format";
import { estadoGeral, compararPorGravidade } from "@/lib/estados";
import { useCompetenciaUrl } from "@/lib/usePeriodoUrl";
import { usePolling } from "@/lib/usePolling";
import { useRecurso } from "@/lib/useRecurso";
import { useAgora } from "@/components/shell/ProvedorAgora";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { CartaoAlerta } from "@/components/fiscal/CartaoAlerta";
import { GraficoBarras, GraficoDonut } from "@/components/fiscal/Graficos";
import { LinhaExecucao } from "@/components/fiscal/LinhaExecucao";
import { SeletorCompetencia } from "@/components/fiscal/SeletorCompetencia";
import { BotaoIcone } from "@/components/ui/BotaoIcone";
import { BotaoLink } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { EsqueletoBloco, EsqueletoLista } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Cnpj, ValorMoeda } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import type { AlertaItem, EmitenteTop, JanelaProximaConsulta } from "@/lib/types";

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
  const backups = useRecurso(() => api.backups(), []);

  const emAndamento = painel.dados?.execucoes.em_andamento ?? 0;
  const atualizando =
    painel.atualizando || central.atualizando || alertas.atualizando || kpis.atualizando || evolucao.atualizando || porTipo.atualizando || backups.atualizando;
  useSinalizarAtualizacao(atualizando);

  const recarregar = useCallback(() => {
    painel.atualizar();
    central.atualizar();
    alertas.atualizar();
    backups.atualizar();
  }, [alertas, backups, central, painel]);

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
  const alertasPendentes = (alertas.dados?.itens ?? []).filter((alerta) => alerta.nivel !== "info");

  const pontoAtual = evolucao.dados?.find((ponto) => ponto.mes === mes);
  const pontoAnterior = evolucao.dados?.find((ponto) => ponto.mes === mesesAnteriores(mes));
  const itens: KpiProps[] = [
    {
      rotulo: `Documentos em ${rotuloCompetencia(mes || null)}`,
      icone: "documento",
      valor: numero(indicadores?.documentos_mes ?? pontoAtual?.total ?? documentos.mes),
      contexto: `${numero(indicadores?.documentos_mes_anterior ?? pontoAnterior?.total ?? 0)} no mês anterior`,
      variacao: {
        valor: indicadores?.variacao_pct ?? variacaoEntre(pontoAtual?.total, pontoAnterior?.total),
        base: "vs. mês anterior",
      },
      href: `/dashboard/documentos?mes=${mes}`,
      carregando: pronto && (kpis.carregando || evolucao.carregando),
      dica: "Documentos fiscais capturados dentro da competência.",
      destaque: true,
    },
    {
      rotulo: "Valor dos documentos",
      icone: "moeda",
      valor: moeda(indicadores?.valor_mes ?? pontoAtual?.valor ?? documentos.valor_mes),
      contexto: `${moeda(pontoAnterior?.valor ?? 0)} no mês anterior`,
      variacao: { valor: variacaoEntre(pontoAtual?.valor, pontoAnterior?.valor), base: "vs. mês anterior" },
      carregando: pronto && (kpis.carregando || evolucao.carregando),
      href: `/dashboard/relatorios?mes=${mes}`,
      dica: "Somatório dos documentos normais da competência, sem os cancelados.",
    },
    {
      rotulo: "NFS-e (nota de serviço)",
      icone: "fechamento",
      valor: numero(pontoAtual?.nfse ?? 0),
      contexto: `${numero(pontoAnterior?.nfse ?? 0)} no mês anterior`,
      variacao: { valor: variacaoEntre(pontoAtual?.nfse, pontoAnterior?.nfse), base: "vs. mês anterior" },
      carregando: pronto && evolucao.carregando,
      href: `/dashboard/documentos?mes=${mes}&tipo=nfse`,
      dica: "Notas de serviço capturadas na competência.",
    },
  ];

  const componentesOk = painel.dados.componentes.filter((componente) => componente.status === "ok").length;
  const infraTom = painel.dados.componentes.some((componente) => componente.status === "erro")
    ? "erro"
    : painel.dados.componentes.some((componente) => componente.status === "atencao")
      ? "espera"
      : "ok";
  const ultimoBackup = backups.dados?.saude.ultimo_ok_em;

  return (
    <div className="space-y-6">
      <CabecalhoPagina
        kicker="Visão geral"
        titulo="Painel operacional"
        descricao="Sua operação fiscal em um só lugar. Acompanhe o que importa e resolva o que precisa de você."
        acoes={
          <>
            <BotaoIcone rotulo="Atualizar painel" dica="Atualizar painel" icone={<Icone nome="atualizar" className="h-4 w-4" />} onClick={recarregar} carregando={atualizando} />
            {pendencias > 0 ? (
              <BotaoLink variante="primaria" href="/dashboard/atencao" iconeDireita={<Icone nome="seta-direita" className="h-4 w-4" />}>
                Ver {contagem(pendencias, "pendência", "pendências")}
              </BotaoLink>
            ) : null}
          </>
        }
      />

      <section aria-label="Resumo da operação" className="painel-status overflow-hidden rounded-cartao border border-traco">
        <div className="flex flex-col gap-6 p-5 sm:p-6 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0 flex-1">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <Etiqueta tom={geral.tom} ponto>{geral.rotulo}</Etiqueta>
              <span className="text-xs text-tinta-suave">{new Date(agora).toLocaleDateString("pt-BR", { day: "2-digit", month: "long", year: "numeric" })}</span>
            </div>
            <h2 className="text-lg font-semibold tracking-tight">{geral.titulo}</h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-tinta-suave">{painel.dados.mensagem || geral.resumo}</p>
          </div>
          <div className="w-full max-w-sm rounded-lg border border-traco bg-fundo/40 p-4 xl:w-72">
            <div className="flex items-center gap-2 text-xs text-tinta-suave">
              <Icone nome="sincronizar" className="h-4 w-4" /> Sincronizadas hoje
            </div>
            <p className="nums mt-2 text-xl font-semibold tracking-tight text-tinta-forte">
              {numero(empresas.sincronizadas_hoje)} <span className="text-base font-normal text-tinta-suave">de {contagem(empresas.habilitadas_sincronizacao, "empresa", "empresas")}</span>
            </p>
            <div
              role="progressbar"
              aria-label="Empresas sincronizadas hoje"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={empresas.habilitadas_sincronizacao > 0 ? Math.min(100, Math.round(empresas.sincronizadas_hoje / empresas.habilitadas_sincronizacao * 100)) : 0}
              className="mt-3 h-1.5 overflow-hidden rounded-full bg-traco"
            >
              <div className="h-full rounded-full bg-acento" style={{ width: `${empresas.habilitadas_sincronizacao > 0 ? Math.min(100, empresas.sincronizadas_hoje / empresas.habilitadas_sincronizacao * 100) : 0}%` }} />
            </div>
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-px border-t border-traco bg-traco lg:grid-cols-4">
          {[
            { rotulo: "Empresas ativas", valor: empresas.ativas, icone: "empresa" as const, href: "/dashboard/empresas" },
            { rotulo: "Documentos hoje", valor: documentos.hoje, icone: "documento" as const, href: "/dashboard/documentos" },
            { rotulo: "Capturas concluídas hoje", valor: execucoes.concluidas_hoje, icone: "verificar-circulo" as const, href: "/dashboard/execucoes" },
            { rotulo: "Certificados válidos", valor: certificados.validos, icone: "certificado" as const, href: "/dashboard/certificados" },
          ].map((item) => (
            <div key={item.rotulo} className="bg-superficie px-4 py-4 sm:px-6">
              <dt className="flex items-center gap-2 text-xs text-tinta-suave"><Icone nome={item.icone} className="h-4 w-4 flex-none" />{item.rotulo}</dt>
              <dd className="nums mt-2 text-lg font-semibold tracking-tight"><Link href={item.href} className="rounded-sm hover:text-acento">{numero(item.valor)}</Link></dd>
            </div>
          ))}
        </dl>
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <Cartao
          titulo="Precisa da sua atenção"
          icone="alerta"
          descricao={
            pendencias > 0
              ? `${contagem(pendencias, "item", "itens")} em aberto, do mais grave para o menos grave`
              : "Nenhuma decisão pendente"
          }
          className="xl:col-span-2"
          acoes={
            pendencias > 5 ? (
              <Link href="/dashboard/atencao" className="text-xs font-medium text-acento underline-offset-4 hover:underline">
                Ver todos
              </Link>
            ) : undefined
          }
        >
          {alertas.carregando ? (
            <EsqueletoLista itens={4} linhas={2} />
          ) : alertas.erro ? (
            <EstadoErro erro={alertas.erro} aoTentarNovamente={alertas.atualizar} contexto="carregar os alertas" />
          ) : alertasPendentes.length > 0 ? (
            <ul className="space-y-2">
              {[...alertasPendentes]
                .sort(compararPorGravidade)
                .slice(0, 5)
                .map((alerta: AlertaItem) => (
                  <li key={alerta.id}>
                    <CartaoAlerta alerta={alerta} compacta />
                  </li>
                ))}
            </ul>
          ) : (
            <EstadoVazio inline titulo="Operação em dia" instrucao="Nenhum item exige decisão agora." icone="verificar-circulo" />
          )}
        </Cartao>

        <Cartao
          titulo="Execuções agora"
          icone="execucao"
          descricao={
            execucoes.em_andamento > 0
              ? `${numero(execucoes.em_andamento)} em andamento · média de ${execucoes.duracao_media_minutos !== null ? numero(execucoes.duracao_media_minutos, 1) : "—"} min`
              : "Nenhuma execução em andamento"
          }
          acoes={
            <Link href="/dashboard/execucoes" className="text-xs font-medium text-acento underline-offset-4 hover:underline">
              Ver central
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
            <EstadoVazio inline titulo="Nada rodando" instrucao="A próxima varredura aparece quando começar." icone="execucao" />
          )}
        </Cartao>
      </div>

      <section aria-labelledby="titulo-numeros-mes" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="titulo-numeros-mes" className="text-md font-semibold tracking-tight text-tinta-forte">Números do mês</h2>
            <p className="text-xs text-tinta-suave">Cada valor compara a competência anterior.</p>
          </div>
          <SeletorCompetencia mes={mes} aoMudar={aoMudar} atalhos={0} className="w-full sm:w-auto" />
        </div>
        <GradeKpis itens={itens} colunas={3} rotulo={`Indicadores de ${rotuloCompetencia(mes)}`} />
      </section>

      <details className="group overflow-hidden rounded-cartao border border-traco bg-superficie">
        <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-medium text-tinta-forte marker:hidden">
          <span>
            Mês em números
            <span className="mt-1 block text-xs font-normal text-tinta-suave sm:ml-2 sm:mt-0 sm:inline sm:text-sm">evolução, tipos e maiores emitentes</span>
          </span>
          <Icone nome="chevron-baixo" className="h-4 w-4 text-tinta-suave transition-transform duration-120 group-open:rotate-180" />
        </summary>
        <div className="space-y-4 border-t border-traco p-4">
          <div className="grid gap-4 xl:grid-cols-3">
            <Cartao titulo="Evolução dos últimos 12 meses" descricao="Documentos por mês de competência" className="xl:col-span-2">
              {evolucao.carregando ? (
                <EsqueletoBloco linhas={4} />
              ) : evolucao.erro ? (
                <EstadoErro erro={evolucao.erro} aoTentarNovamente={evolucao.atualizar} contexto="carregar a evolução mensal" />
              ) : evolucao.dados && evolucao.dados.length > 0 ? (
                <GraficoBarras
                  titulo="Documentos por mês"
                  descricao="Total de documentos capturados nos últimos 12 meses"
                  dados={evolucao.dados.map((ponto) => ({
                    rotulo: ponto.rotulo,
                    valor: ponto.total,
                    titulo: `${ponto.rotulo}: ${contagem(ponto.total, "documento", "documentos")} · ${moeda(ponto.valor)}`,
                  }))}
                />
              ) : (
                <EstadoVazio inline titulo="Sem histórico" instrucao="A evolução aparece após a primeira captura mensal." />
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
                <EstadoVazio inline titulo="Nenhum documento nesta competência" instrucao="Escolha outro mês." icone="documento" />
              )}
            </Cartao>
          </div>

          <Cartao titulo="Maiores emitentes" descricao={mes ? `${rotuloCompetencia(mes)} · documentos tomados` : undefined}>
            {emitentes.carregando ? (
              <EsqueletoLista itens={5} linhas={1} />
            ) : emitentes.erro ? (
              <EstadoErro erro={emitentes.erro} aoTentarNovamente={emitentes.atualizar} contexto="carregar os maiores emitentes" />
            ) : emitentes.dados && emitentes.dados.length > 0 ? (
              <ListaEmitentes emitentes={emitentes.dados} />
            ) : (
              <EstadoVazio inline titulo="Sem emitentes nesta competência" instrucao="O ranking aparece com os primeiros documentos tomados." icone="grafico-barras" />
            )}
          </Cartao>
        </div>
      </details>

      <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-traco pt-3 text-xs text-tinta-suave">
        <IndicadorEstado
          tom={infraTom}
          icone={infraTom === "ok" ? "verificar-circulo" : infraTom === "erro" ? "negar" : "alerta"}
          rotulo={`Infra: ${numero(componentesOk)}/${numero(painel.dados.componentes.length)} componentes no ar`}
          variante="texto"
        />
        <span aria-hidden="true">·</span>
        <span className="nums">
          backup {ultimoBackup ? tempoRelativo(ultimoBackup, agora) : backups.carregando ? "em consulta" : "sem registro"}
        </span>
        <Link href="/dashboard/saude" className="font-medium text-acento underline-offset-4 hover:underline">
          Ver saúde
        </Link>
      </footer>
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
                {janela.tipo.toUpperCase()} · {janela.bloqueada ? "janela SEFAZ" : `${contagem(janela.pendencia, "pendente", "pendentes")}`}
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

function variacaoEntre(atual: number | undefined, anterior: number | undefined): number | null {
  if (atual === undefined || anterior === undefined || anterior === 0) return null;
  return ((atual - anterior) / anterior) * 100;
}
