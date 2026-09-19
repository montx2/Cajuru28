"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { dataCurta, moeda, numero, percentual, plural } from "@/lib/format";
import { estadoDaConferencia } from "@/lib/estados";
import { mensagemDoErro } from "@/lib/erros";
import { rotulo as rotuloCompetencia } from "@/lib/competencia";
import { intervaloDoMes } from "@/lib/periodo";
import { useCompetenciaUrl } from "@/lib/usePeriodoUrl";
import { useRecurso } from "@/lib/useRecurso";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { SeletorCompetencia } from "@/components/fiscal/SeletorCompetencia";
import { GraficoBarras, GraficoDonut } from "@/components/fiscal/Graficos";
import { Aviso } from "@/components/ui/Aviso";
import { Botao, BotaoLink } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { EsqueletoBloco } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Cnpj, ValorMoeda } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import { ROTULO_TIPO, TIPOS, type FechamentoEmpresa, type ItemConferenciaCompetencia } from "@/lib/types";

/**
 * Fechamento mensal — a tela que vira folha de dossiê.
 *
 * Duas decisões: a conferência (`/importacoes/conferencia`) entra junto do
 * fechamento porque "quantos documentos?" sem "está completo?" não fecha mês
 * nenhum; e a impressão tem tabela própria, sem virtualização nem scroll —
 * imprimir a tabela interativa cortaria linhas silenciosamente.
 */
export function Relatorios() {
  const { mes, competencia, aoMudar, pronto } = useCompetenciaUrl();
  const { avisar } = useToast();
  const [baixando, setBaixando] = useState(false);

  const fechamento = useRecurso(() => api.fechamento(competencia), [competencia], { automatico: pronto });
  const conferencia = useRecurso(() => api.conferirCompetencia({ competencia }), [competencia], { automatico: pronto });

  useSinalizarAtualizacao(fechamento.atualizando || conferencia.atualizando);

  const situacaoPorEmpresa = useMemo(() => {
    const mapa = new Map<number, ItemConferenciaCompetencia[]>();
    for (const item of conferencia.dados?.itens ?? []) {
      const lista = mapa.get(item.empresa_id) ?? [];
      lista.push(item);
      mapa.set(item.empresa_id, lista);
    }
    return mapa;
  }, [conferencia.dados]);

  const empresas = useMemo(() => fechamento.dados?.empresas ?? [], [fechamento.dados]);
  const totais = fechamento.dados?.totais ?? null;
  const estadoConferencia = estadoDaConferencia(conferencia.dados?.status ?? "");

  const indicadores: KpiProps[] = totais
    ? [
        { rotulo: "Documentos", valor: numero(totais.documentos), contexto: rotuloCompetencia(mes), carregando: fechamento.atualizando },
        { rotulo: "Valor do mês", valor: moeda(totais.valor), carregando: fechamento.atualizando },
        { rotulo: "Canceladas", valor: numero(totais.canceladas), tom: totais.canceladas > 0 ? "espera" : "neutro", contexto: totais.documentos > 0 ? `${percentual((totais.canceladas / totais.documentos) * 100, 1)} do mês` : undefined },
        { rotulo: "Sem XML completo", valor: numero(totais.sem_xml), tom: totais.sem_xml > 0 ? "erro" : "ok", contexto: "recebidas só em resumo", href: `/dashboard/documentos?leiaute=resumo&mes=${mes}` },
        {
          rotulo: "Empresas com documento",
          valor: `${numero(totais.empresas_com_documento)}/${numero(totais.empresas_total)}`,
          tom: totais.empresas_com_documento < totais.empresas_total ? "espera" : "ok",
          contexto: "as demais ficaram mudas no mês",
        },
      ]
    : [];

  const colunas = useMemo<Array<ColunaTabela<FechamentoEmpresa>>>(
    () => [
      {
        id: "empresa",
        cabecalho: "Empresa",
        largura: "min-w-56",
        fixa: true,
        ordenavel: true,
        celula: (linha) => (
          <Link href={`/dashboard/empresa?id=${linha.empresa_id}`} className="block truncate font-medium text-tinta underline-offset-4 hover:text-acento hover:underline" title={linha.razao_social}>
            {linha.razao_social}
          </Link>
        ),
      },
      { id: "cnpj", cabecalho: "CNPJ", celula: (linha) => <Cnpj valor={linha.cnpj} /> },
      { id: "uf", cabecalho: "UF", celula: (linha) => <span className="nums text-tinta-suave">{linha.uf || "—"}</span> },
      { id: "total", cabecalho: "Documentos", alinhamento: "direita", numerica: true, ordenavel: true, celula: (linha) => numero(linha.total) },
      { id: "valor", cabecalho: "Valor", alinhamento: "direita", numerica: true, ordenavel: true, celula: (linha) => <ValorMoeda valor={linha.valor} /> },
      { id: "canceladas", cabecalho: "Canceladas", alinhamento: "direita", numerica: true, celula: (linha) => numero(linha.canceladas) },
      {
        id: "sem_xml",
        cabecalho: "Sem XML",
        alinhamento: "direita",
        numerica: true,
        celula: (linha) => <span className={linha.sem_xml > 0 ? "text-erro" : undefined}>{numero(linha.sem_xml)}</span>,
      },
      ...TIPOS.map((tipo) => ({
        id: `tipo-${tipo}`,
        cabecalho: ROTULO_TIPO[tipo],
        alinhamento: "direita" as const,
        numerica: true,
        ocultaPorPadrao: true,
        celula: (linha: FechamentoEmpresa) => numero(linha.por_tipo[tipo]?.qtd ?? 0),
      })),
      {
        id: "conferencia",
        cabecalho: "Conferência",
        celula: (linha) => {
          const itens = situacaoPorEmpresa.get(linha.empresa_id) ?? [];
          if (itens.length === 0) return <span className="text-tinta-fraca">sem dados</span>;
          const criticos = itens.filter((item) => item.status === "critico").length;
          const pendentes = itens.filter((item) => item.status === "pendente" || item.status === "parcial").length;
          if (criticos > 0) return <Etiqueta tom="erro" titulo={itens.find((item) => item.status === "critico")?.mensagem}>{numero(criticos)} críticos</Etiqueta>;
          if (pendentes > 0) return <Etiqueta tom="espera" titulo={itens.find((item) => item.status === "pendente" || item.status === "parcial")?.mensagem}>{numero(pendentes)} pendências</Etiqueta>;
          return <Etiqueta tom="ok">completa</Etiqueta>;
        },
      },
    ],
    [situacaoPorEmpresa]
  );

  async function baixarCsv() {
    setBaixando(true);
    try {
      await api.baixarFechamentoCsv(competencia);
      avisar({ tom: "ok", titulo: "CSV do fechamento gerado", descricao: rotuloCompetencia(mes) });
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível gerar o CSV", descricao: mensagemDoErro(falha, "baixar o fechamento em CSV") });
    } finally {
      setBaixando(false);
    }
  }

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Fechamento mensal"
        descricao="Conferência do mês por empresa e tipo, com a folha pronta para o dossiê do cliente."
        acoes={
          <div className="flex flex-wrap items-center gap-2 nao-imprimir">
            <Botao
              variante="sutil"
              onClick={() => {
                fechamento.atualizar();
                conferencia.atualizar();
              }}
              carregando={fechamento.atualizando || conferencia.atualizando}
              iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}
            >
              Atualizar
            </Botao>
            <Botao variante="secundaria" onClick={baixarCsv} carregando={baixando} disabled={!pronto} iconeEsquerda={<Icone nome="baixar" className="h-4 w-4" />}>
              Baixar CSV
            </Botao>
            <Botao variante="primaria" onClick={() => window.print()} iconeEsquerda={<Icone nome="imprimir" className="h-4 w-4" />}>
              Imprimir fechamento
            </Botao>
          </div>
        }
      />

      <div className="nao-imprimir">
        <SeletorCompetencia mes={mes} aoMudar={aoMudar} descricao="Mês de emissão dos documentos" />
      </div>

      {/* Cabeçalho que só existe no papel: sem ele a folha perde competência, data e responsável. */}
      <div className="hidden print:block">
        <h1 className="text-lg font-semibold">NotasFlow · Fechamento de {rotuloCompetencia(mes)}</h1>
        <p className="mt-1 text-xs">
          Período de {fechamento.dados ? `${dataCurta(fechamento.dados.inicio)} a ${dataCurta(fechamento.dados.fim)}` : "—"} · gerado em{" "}
          {new Date().toLocaleString("pt-BR")} · conferência: {conferencia.dados?.status ?? "—"}
        </p>
      </div>

      {conferencia.dados ? (
        <Aviso
          className="nao-imprimir"
          tom={estadoConferencia.tom}
          icone={estadoConferencia.icone}
          titulo={estadoConferencia.rotulo}
          acao={
            conferencia.dados.ok ? undefined : (
              <Link href="/dashboard/importacoes" className="text-sm font-medium underline-offset-4 hover:underline">
                Disparar captura
              </Link>
            )
          }
        >
          {conferencia.dados.mensagem}{" "}
          <span className="nums">
            {numero(conferencia.dados.itens_ok)}/{numero(conferencia.dados.itens_total)} combinações conferidas ·{" "}
            {numero(conferencia.dados.itens_pendentes)} pendentes · {numero(conferencia.dados.itens_criticos)} críticas.
          </span>
        </Aviso>
      ) : null}

      {fechamento.carregando ? (
        <EsqueletoBloco linhas={8} />
      ) : fechamento.erro ? (
        <EstadoErro erro={fechamento.erro} aoTentarNovamente={fechamento.atualizar} contexto="carregar o fechamento do mês" />
      ) : !totais || totais.documentos === 0 ? (
        <EstadoVazio
          titulo={pronto ? `Nenhum documento em ${rotuloCompetencia(mes)}` : "Escolha a competência"}
          instrucao={
            pronto
              ? "Sem documento capturado não há o que fechar. Confira certificados e sincronismo, depois dispare a captura do mês."
              : "O fechamento é sempre por competência (mês de emissão)."
          }
          acao={
            pronto ? (
              <BotaoLink
                variante="secundaria"
                href={`/dashboard/importacoes?data_inicio=${intervaloDoMes(mes).inicio}&data_fim=${intervaloDoMes(mes).fim}`}
              >
                Disparar captura do mês
              </BotaoLink>
            ) : undefined
          }
          icone="fechamento"
        />
      ) : (
        <>
          <GradeKpis itens={indicadores} colunas={5} rotulo={`Fechamento de ${rotuloCompetencia(mes)}`} className="nao-imprimir" />

          <div className="grid gap-4 nao-imprimir xl:grid-cols-3">
            <Cartao titulo="Documentos por tipo" descricao={`${rotuloCompetencia(mes)} · quantidade`}>
              <GraficoDonut
                titulo="Participação por tipo"
                descricao="Quantidade de documentos por tipo no mês"
                centro={numero(totais.documentos)}
                dados={TIPOS.map((tipo, indice) => ({
                  rotulo: ROTULO_TIPO[tipo],
                  valor: totais.por_tipo[tipo]?.qtd ?? 0,
                  cor: (["acento", "info", "neutro"] as const)[indice % 3],
                }))}
              />
              <dl className="mt-3 space-y-1 border-t border-traco pt-3 text-sm">
                {TIPOS.map((tipo) => (
                  <div key={tipo} className="flex items-baseline justify-between gap-3">
                    <dt className="text-tinta-suave">{ROTULO_TIPO[tipo]}</dt>
                    <dd className="nums text-tinta-forte">
                      {numero(totais.por_tipo[tipo]?.qtd ?? 0)}
                      <span className="ml-2 text-xs font-normal text-tinta-suave">{moeda(totais.por_tipo[tipo]?.valor ?? 0)}</span>
                    </dd>
                  </div>
                ))}
              </dl>
            </Cartao>

            <Cartao titulo="Empresas com mais documentos" descricao="Top 8 do mês" className="xl:col-span-2">
              {empresas.length > 0 ? (
                <GraficoBarras
                  titulo="Documentos por empresa"
                  descricao="Quantidade de documentos capturados por empresa na competência"
                  dados={[...empresas]
                    .sort((a, b) => b.total - a.total)
                    .slice(0, 8)
                    .map((linha) => ({ rotulo: linha.razao_social, valor: linha.total, titulo: `${linha.razao_social}: ${numero(linha.total)} documentos · ${moeda(linha.valor)}` }))}
                />
              ) : (
                <EstadoVazio inline titulo="Nenhuma empresa com documento" icone="empresa" />
              )}
            </Cartao>
          </div>

          <div className="nao-imprimir">
            <Tabela
              linhas={empresas}
              colunas={colunas}
              chaveDaLinha={(linha) => linha.empresa_id}
              legenda={`Fechamento por empresa · ${rotuloCompetencia(mes)}`}
              virtualizar
              estados={{
                carregando: false,
                vazioTitulo: "Nenhuma empresa com documento no mês",
                vazioInstrucao: "Dispare a captura do período para preencher o fechamento.",
                vazioIcone: "fechamento",
              }}
              rodape={
                <p className="nums text-xs text-tinta-suave">
                  {numero(empresas.length)} {plural(empresas.length, "empresa", "empresas")} · {numero(totais.documentos)} documentos · {moeda(totais.valor)} ·{" "}
                  {numero(totais.canceladas)} canceladas
                </p>
              }
            />
          </div>

          {/* Folha de impressão: tabela completa (sem virtualização), totais e assinatura. */}
          <div className="hidden print:block pagina-paisagem">
            <table className="w-full text-xs">
              <caption className="sr-only">Fechamento por empresa</caption>
              <thead>
                <tr>
                  <th scope="col" className="text-left">
                    Empresa
                  </th>
                  <th scope="col" className="text-left">
                    CNPJ
                  </th>
                  <th scope="col" className="text-left">
                    UF
                  </th>
                  {TIPOS.map((tipo) => (
                    <th key={tipo} scope="col" className="text-right">
                      {ROTULO_TIPO[tipo]}
                    </th>
                  ))}
                  <th scope="col" className="text-right">
                    Documentos
                  </th>
                  <th scope="col" className="text-right">
                    Canceladas
                  </th>
                  <th scope="col" className="text-right">
                    Valor
                  </th>
                </tr>
              </thead>
              <tbody>
                {empresas.map((linha) => (
                  <tr key={linha.empresa_id} className="evitar-quebra">
                    <th scope="row" className="text-left font-normal">
                      {linha.razao_social}
                    </th>
                    <td className="nums text-left">{linha.cnpj}</td>
                    <td className="text-left">{linha.uf || "—"}</td>
                    {TIPOS.map((tipo) => (
                      <td key={tipo} className="nums text-right">
                        {numero(linha.por_tipo[tipo]?.qtd ?? 0)}
                      </td>
                    ))}
                    <td className="nums text-right">{numero(linha.total)}</td>
                    <td className="nums text-right">{numero(linha.canceladas)}</td>
                    <td className="nums text-right">{moeda(linha.valor)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="evitar-quebra">
                  <th scope="row" colSpan={3} className="text-left font-semibold">
                    Total do mês
                  </th>
                  {TIPOS.map((tipo) => (
                    <td key={tipo} className="nums text-right font-semibold">
                      {numero(totais.por_tipo[tipo]?.qtd ?? 0)}
                    </td>
                  ))}
                  <td className="nums text-right font-semibold">{numero(totais.documentos)}</td>
                  <td className="nums text-right font-semibold">{numero(totais.canceladas)}</td>
                  <td className="nums text-right font-semibold">{moeda(totais.valor)}</td>
                </tr>
              </tfoot>
            </table>

            <div className="mt-6 flex justify-between gap-8 text-xs">
              <div>
                <p>Conferência: {conferencia.dados?.status ?? "não verificada"}</p>
                <p>
                  {numero(conferencia.dados?.itens_ok ?? 0)} de {numero(conferencia.dados?.itens_total ?? 0)} combinações conferidas ·{" "}
                  {numero(conferencia.dados?.sem_xml_completo ?? 0)} documentos sem XML completo
                </p>
              </div>
              <div className="text-right">
                <p className="mt-8 border-t border-black pt-1">Assinatura do responsável</p>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
