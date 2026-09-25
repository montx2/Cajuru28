"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { mensagemDoErro } from "@/lib/erros";
import { dataCurta, numero, plural } from "@/lib/format";
import { estadoDaAutorizacao, estadoDoJobProcuracao, estadoDoPrazoAceite } from "@/lib/estados";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { useBuscaUrl } from "@/lib/useBuscaUrl";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { Aviso } from "@/components/ui/Aviso";
import { Botao } from "@/components/ui/Botao";
import { CabecalhoPagina } from "@/components/ui/Cartao";
import { Busca } from "@/components/ui/Campo";
import { Cnpj, Truncado } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import { ConfiguracaoProcuracoes } from "./ConfiguracaoProcuracoes";
import { PainelJob } from "./PainelJob";
import type { LinhaProcuracao } from "@/lib/types";

const TAMANHO_PAGINA = 50;

const SITUACOES: Array<{ valor: string; rotulo: string }> = [
  { valor: "", rotulo: "Todas" },
  { valor: "sem_autorizacao", rotulo: "Sem autorização" },
  { valor: "em_analise", rotulo: "Em análise" },
  { valor: "ativa", rotulo: "Ativas" },
  { valor: "expirada", rotulo: "Expiradas" },
  { valor: "intervencao_manual", rotulo: "Precisa de você" },
];

/**
 * Centro das Autorizações de Acesso da Receita Federal.
 *
 * A pergunta desta tela é uma só: **quais clientes ainda não autorizaram a
 * contabilidade, e o que falta para resolver?** Por isso o KPI "sem
 * autorização" é o primeiro, o botão "Processar pendências" fica no cabeçalho
 * e cada linha diz em que ponto o processo parou.
 *
 * O que esta tela *não* faz: executar a outorga. O ato é praticado por uma
 * pessoa, no ambiente oficial da Receita, com o certificado do cliente — a
 * IN RFB nº 2.320/2026 (art. 13) veda camada de intermediação automatizada.
 * O que o sistema automatiza é tudo em volta: descobrir quem falta, validar
 * certificado e Assinador, montar a fila, abrir a página certa, registrar o
 * resultado e vigiar os prazos.
 */
export function Procuracoes() {
  const { definir, ler } = useUrlEstado();
  const busca = useBuscaUrl();
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();

  const situacao = SITUACOES.some((opcao) => opcao.valor === ler("situacao")) ? ler("situacao") : "";
  const pagina = Math.max(1, Number(ler("pagina") || 1));

  const [jobAberto, setJobAberto] = useState<number | null>(null);
  const [configAberta, setConfigAberta] = useState(false);
  const [processando, setProcessando] = useState(false);

  const resumo = useRecurso(() => api.resumoProcuracoes(), []);
  const lista = useRecurso(
    () =>
      api.listarProcuracoes({
        situacao: situacao || undefined,
        busca: busca.valor.trim() || undefined,
        pagina,
        tamanho: TAMANHO_PAGINA,
      }),
    [situacao, busca.valor, pagina]
  );
  const notificacoes = useRecurso(() => api.notificacoesProcuracao(true), []);
  useSinalizarAtualizacao(resumo.atualizando || lista.atualizando);

  const recarregar = useCallback(() => {
    resumo.atualizar();
    lista.atualizar();
    notificacoes.atualizar();
  }, [lista, notificacoes, resumo]);

  const dados = resumo.dados;
  const linhas = lista.dados?.itens ?? [];
  const total = lista.dados?.total ?? 0;

  const processarPendencias = useCallback(async () => {
    setProcessando(true);
    try {
      const resultado = await api.processarPendencias({});
      const partes = [`${numero(resultado.criados)} ${plural(resultado.criados, "job criado", "jobs criados")}`];
      if (resultado.ja_na_fila > 0) partes.push(`${numero(resultado.ja_na_fila)} já na fila`);
      if (resultado.bloqueados_por_certificado > 0) {
        partes.push(`${numero(resultado.bloqueados_por_certificado)} travado(s) por certificado`);
      }
      avisar({
        tom: resultado.criados > 0 ? "ok" : "info",
        titulo: "Pendências avaliadas",
        descricao: partes.join(" · "),
      });
      recarregar();
    } catch (erro) {
      avisar({
        tom: "erro",
        titulo: "Não foi possível montar a fila",
        descricao: mensagemDoErro(erro, "processar pendências"),
      });
    } finally {
      setProcessando(false);
    }
  }, [avisar, recarregar]);

  const criarJob = useCallback(
    async (linha: LinhaProcuracao) => {
      try {
        const job = await api.criarJobProcuracao(linha.empresa_id);
        avisar({
          tom: "ok",
          titulo: `Job #${job.id} na fila`,
          descricao: `${linha.razao_social} aguarda uma estação com o certificado A1 desta empresa.`,
        });
        recarregar();
        setJobAberto(job.id);
      } catch (erro) {
        avisar({
          tom: "erro",
          titulo: "Não foi possível criar o job",
          descricao: mensagemDoErro(erro, "criar job"),
        });
      }
    },
    [avisar, recarregar]
  );

  const colunas = useMemo<Array<ColunaTabela<LinhaProcuracao>>>(
    () => [
      {
        id: "empresa",
        cabecalho: "Empresa",
        largura: "min-w-56",
        fixa: true,
        celula: (linha) => (
          <Link
            href={`/dashboard/procuracoes/empresa?id=${linha.empresa_id}`}
            className="block truncate font-medium text-tinta underline-offset-4 hover:text-acento hover:underline"
            title={linha.razao_social}
          >
            {linha.razao_social}
          </Link>
        ),
      },
      { id: "cnpj", cabecalho: "CNPJ", celula: (linha) => <Cnpj valor={linha.documento} /> },
      {
        id: "situacao",
        cabecalho: "Autorização",
        celula: (linha) => <IndicadorEstado {...estadoDaAutorizacao(linha.situacao)} />,
      },
      {
        id: "validade",
        cabecalho: "Validade",
        alinhamento: "direita",
        numerica: true,
        celula: (linha) =>
          linha.data_validade ? (
            <span
              className={
                (linha.dias_para_vencer ?? 999) < 0
                  ? "nums text-erro"
                  : (linha.dias_para_vencer ?? 999) <= 30
                    ? "nums text-espera"
                    : "nums"
              }
              title={linha.dias_para_vencer !== null ? `${linha.dias_para_vencer} dia(s)` : undefined}
            >
              {dataCurta(linha.data_validade)}
            </span>
          ) : (
            <span className="text-tinta-fraca">—</span>
          ),
      },
      {
        id: "prazo",
        cabecalho: "Prazo do aceite",
        dica: "A Receita cancela a autorização não validada em 30 dias.",
        celula: (linha) => {
          const estado = estadoDoPrazoAceite(linha.dias_para_aceite);
          return estado ? <IndicadorEstado {...estado} /> : <span className="text-tinta-fraca">—</span>;
        },
      },
      {
        id: "certificado",
        cabecalho: "A1 na frota",
        dica: "Existe certificado vigente desta empresa em alguma estação?",
        celula: (linha) =>
          linha.certificado_disponivel ? (
            <IndicadorEstado tom="ok" rotulo="Disponível" icone="certificado" />
          ) : (
            <IndicadorEstado tom="erro" rotulo="Ausente" icone="certificado" />
          ),
      },
      {
        id: "job",
        cabecalho: "Processo",
        largura: "min-w-44",
        celula: (linha) =>
          linha.job_id ? (
            <button
              type="button"
              onClick={() => setJobAberto(linha.job_id)}
              className="inline-flex items-center gap-1.5 text-left underline-offset-4 hover:underline"
              title={linha.job_etapa ? `Etapa: ${linha.job_etapa}` : "Abrir o processo"}
            >
              <IndicadorEstado {...estadoDoJobProcuracao(linha.job_status ?? "")} />
            </button>
          ) : (
            <span className="text-tinta-fraca">—</span>
          ),
      },
      {
        id: "origem",
        cabecalho: "Origem do dado",
        ocultaPorPadrao: true,
        celula: (linha) => <Truncado texto={linha.origem_dado ?? "—"} />,
      },
      {
        id: "acoes",
        cabecalho: "",
        alinhamento: "direita",
        celula: (linha) => {
          const precisaDeJob = !linha.job_id && linha.situacao !== "ativa";
          if (!precisaDeJob) {
            return (
              <Link
                href={`/dashboard/procuracoes/empresa?id=${linha.empresa_id}`}
                className="text-xs text-tinta-suave underline-offset-4 hover:text-acento hover:underline"
              >
                Detalhes
              </Link>
            );
          }
          return (
            <Botao
              variante="sutil"
              tamanho="sm"
              disabled={somenteLeitura}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : "Colocar esta empresa na fila"}
              onClick={() => criarJob(linha)}
            >
              Preparar
            </Botao>
          );
        },
      },
    ],
    [criarJob, somenteLeitura]
  );

  const indicadores: KpiProps[] = [
    {
      rotulo: "Sem autorização",
      valor: numero(dados?.sem_autorizacao ?? 0),
      tom: (dados?.sem_autorizacao ?? 0) > 0 ? "erro" : "ok",
      href: "/dashboard/procuracoes?situacao=sem_autorizacao",
      carregando: resumo.carregando,
      dica: "Empresas da carteira sem autorização de acesso vigente para a contabilidade.",
    },
    {
      rotulo: "Aguardando aceite",
      valor: numero((dados?.em_analise ?? 0) + (dados?.aguardando_aceite ?? 0)),
      tom: (dados?.em_analise ?? 0) + (dados?.aguardando_aceite ?? 0) > 0 ? "espera" : "neutro",
      href: "/dashboard/procuracoes?situacao=em_analise",
      carregando: resumo.carregando,
      dica: "Outorga registrada; falta a contabilidade validar no e-CAC. Prazo legal: 30 dias.",
    },
    {
      rotulo: "Ativas",
      valor: numero(dados?.ativas ?? 0),
      tom: "ok",
      href: "/dashboard/procuracoes?situacao=ativa",
      carregando: resumo.carregando,
      contexto: (dados?.vencendo ?? 0) > 0 ? `${numero(dados?.vencendo ?? 0)} vencendo` : undefined,
    },
    {
      rotulo: "Precisa de você",
      valor: numero(dados?.jobs_aguardando_humano ?? 0),
      tom: (dados?.jobs_aguardando_humano ?? 0) > 0 ? "espera" : "neutro",
      href: "/dashboard/procuracoes?situacao=intervencao_manual",
      carregando: resumo.carregando,
      dica: "Processos parados esperando uma ação humana — não são falhas.",
    },
  ];

  const semEstacao = (dados?.agentes_online ?? 0) === 0 && (dados?.agentes_total ?? 0) > 0;
  const semAgenteNenhum = (dados?.agentes_total ?? 0) === 0;
  const semAssinador =
    (dados?.agentes_online ?? 0) > 0 && (dados?.agentes_com_assinador ?? 0) === 0;

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Procurações RFB"
        descricao="Autorizações de Acesso da Receita Federal: quem já autorizou a contabilidade, quem falta e o que trava cada processo."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="sutil" onClick={recarregar} carregando={lista.atualizando} iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}>
              Atualizar
            </Botao>
            <Link
              href="/dashboard/procuracoes/estacoes"
              className="inline-flex h-9 items-center gap-1.5 rounded-controle border border-borda-controle bg-superficie px-3 text-xs font-medium text-tinta-suave transition-colors duration-120 hover:border-tinta-suave hover:text-tinta"
            >
              <Icone nome="monitor" className="h-4 w-4" />
              Estações
              {(dados?.agentes_online ?? 0) > 0 ? (
                <span className="nums text-ok">{dados?.agentes_online}</span>
              ) : null}
            </Link>
            <Botao
              variante="sutil"
              onClick={() => setConfigAberta(true)}
              iconeEsquerda={<Icone nome="configuracoes" className="h-4 w-4" />}
            >
              Configurar
            </Botao>
            <Botao
              variante="primaria"
              onClick={processarPendencias}
              carregando={processando}
              disabled={somenteLeitura}
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : "Avalia a carteira e monta a fila de trabalho"}
              iconeEsquerda={<Icone nome="fila" className="h-4 w-4" />}
            >
              Processar pendências
            </Botao>
          </div>
        }
      />

      {semAgenteNenhum ? (
        <Aviso tom="espera" icone="monitor" titulo="Nenhuma estação matriculada" acao={<Link href="/dashboard/procuracoes/estacoes" className="text-xs font-medium underline underline-offset-4">Matricular estação</Link>}>
          O Cajuru Agent roda na máquina que tem os certificados A1 e o Assinador SERPRO. Sem pelo menos uma estação, a fila até é montada — mas
          ninguém a executa.
        </Aviso>
      ) : null}

      {semEstacao ? (
        <Aviso tom="erro" icone="monitor" titulo="Nenhuma estação respondendo">
          As estações cadastradas pararam de enviar sinal. Jobs em andamento voltam sozinhos para a fila; nada é perdido. Verifique se o Cajuru
          Agent está em execução nas máquinas do escritório.
        </Aviso>
      ) : null}

      {semAssinador ? (
        <Aviso tom="erro" icone="certificado" titulo="Assinador SERPRO indisponível nas estações">
          Nenhum job é entregue enquanto o Assinador Digital SERPRO não estiver instalado, em execução e respondendo na porta local. A tela de
          Estações lista exatamente o que falta em cada máquina.
        </Aviso>
      ) : null}

      {(notificacoes.dados ?? []).slice(0, 2).map((item) => (
        <Aviso
          key={item.id}
          tom={item.nivel === "erro" ? "erro" : item.nivel === "alerta" || item.nivel === "atencao" ? "espera" : "info"}
          icone="alerta"
          titulo={item.titulo}
          acao={
            <button
              type="button"
              className="text-xs font-medium underline underline-offset-4"
              onClick={async () => {
                await api.reconhecerNotificacaoProcuracao(item.id);
                notificacoes.atualizar();
              }}
            >
              Marcar como visto
            </button>
          }
        >
          {item.detalhe}
        </Aviso>
      ))}

      <GradeKpis itens={indicadores} colunas={4} rotulo="Situação das autorizações" />

      <Tabela
        linhas={linhas}
        colunas={colunas}
        chaveDaLinha={(linha) => linha.empresa_id}
        legenda="Autorizações de acesso por empresa"
        virtualizar
        estados={{
          carregando: lista.carregando,
          erro: lista.erro,
          aoTentarNovamente: lista.atualizar,
          vazioTitulo: "Nenhuma empresa neste recorte",
          vazioInstrucao: "Troque o filtro, ou sincronize com a fonte configurada para trazer a situação atual.",
          vazioIcone: "cadeado",
          filtroAtivo: Boolean(situacao || busca.valor.trim()),
          aoLimparFiltro: () => {
            definir({ situacao: null, busca: null, pagina: null });
            busca.aoMudar("");
          },
        }}
        ferramentas={
          <div className="flex flex-wrap items-end gap-2">
            <Busca
              rotulo="Buscar empresa"
              placeholder="Razão social ou CNPJ"
              valor={busca.valor}
              aoMudar={(valor) => {
                busca.aoMudar(valor);
                definir({ pagina: null });
              }}
              className="min-w-64 flex-1"
            />
            <div className="flex flex-wrap items-center gap-1">
              {SITUACOES.map((opcao) => (
                <button
                  key={opcao.valor}
                  type="button"
                  onClick={() => definir({ situacao: opcao.valor || null, pagina: null })}
                  aria-pressed={situacao === opcao.valor}
                  className={
                    situacao === opcao.valor
                      ? "inline-flex h-9 items-center rounded-controle border border-acento bg-acento-tenue px-2.5 text-xs font-medium text-acento"
                      : "inline-flex h-9 items-center rounded-controle border border-borda-controle bg-superficie px-2.5 text-xs text-tinta-suave transition-colors duration-120 hover:border-tinta-suave hover:text-tinta"
                  }
                >
                  {opcao.rotulo}
                </button>
              ))}
            </div>
          </div>
        }
        rodape={
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="nums text-xs text-tinta-suave">
              {numero(total)} {plural(total, "empresa", "empresas")}
              {dados ? (
                <span className="ml-2 text-tinta-fraca">
                  · {numero(dados.jobs_na_fila)} na fila · {numero(dados.agentes_online)} estação(ões) online
                </span>
              ) : null}
            </p>
            {total > TAMANHO_PAGINA ? (
              <div className="flex items-center gap-2">
                <Botao variante="sutil" tamanho="sm" disabled={pagina <= 1} onClick={() => definir({ pagina: pagina > 2 ? String(pagina - 1) : null })}>
                  Anterior
                </Botao>
                <span className="nums text-xs text-tinta-suave">
                  {pagina} / {Math.max(1, Math.ceil(total / TAMANHO_PAGINA))}
                </span>
                <Botao
                  variante="sutil"
                  tamanho="sm"
                  disabled={pagina >= Math.ceil(total / TAMANHO_PAGINA)}
                  onClick={() => definir({ pagina: String(pagina + 1) })}
                >
                  Próxima
                </Botao>
              </div>
            ) : null}
          </div>
        }
      />

      <PainelJob jobId={jobAberto} aoFechar={() => setJobAberto(null)} aoMudar={recarregar} />
      <ConfiguracaoProcuracoes aberta={configAberta} aoFechar={() => setConfigAberta(false)} aoSalvar={recarregar} />
    </div>
  );
}
