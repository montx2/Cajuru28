"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
import { BotaoIcone } from "@/components/ui/BotaoIcone";
import { CabecalhoPagina } from "@/components/ui/Cartao";
import { Busca } from "@/components/ui/Campo";
import { Cnpj, DataHora, Truncado } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Tabela, type ColunaTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import { ConfiguracaoProcuracoes } from "./ConfiguracaoProcuracoes";
import { DadosDoEscritorio } from "./DadosDoEscritorio";
import { ImportarLista } from "./ImportarLista";
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
 * certificado e Assinador, montar a fila, entregar ao Agent local para abrir
 * a página certa, registrar o resultado e vigiar os prazos.
 */
export function Procuracoes() {
  const { definir, ler } = useUrlEstado();
  const busca = useBuscaUrl();
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();

  const situacao = SITUACOES.some((opcao) => opcao.valor === ler("situacao")) ? ler("situacao") : "";
  const pagina = Math.max(1, Number(ler("pagina") || 1));
  // A fila de atenção enlaça direto no processo: `/procuracoes?job=42` abre o
  // painel do job 42 — o clique do alerta não pode virar caça na lista.
  const jobDaUrl = Number(ler("job")) || null;

  const [jobAberto, setJobAberto] = useState<number | null>(jobDaUrl);
  useEffect(() => {
    if (jobDaUrl) setJobAberto(jobDaUrl);
  }, [jobDaUrl]);
  const [configAberta, setConfigAberta] = useState(false);
  const [dadosDoEscritorioAbertos, setDadosDoEscritorioAbertos] = useState(false);
  const [empresaParaFazer, setEmpresaParaFazer] = useState<LinhaProcuracao | null>(null);
  const [importacaoAberta, setImportacaoAberta] = useState(false);
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
  // A mesma fonte que alimenta o roteiro do processo também informa qual é a
  // página oficial que o modo manual pode abrir. No modo automático, a janela
  // é aberta pelo Agent local com a política do certificado. Não há URL
  // inventada no navegador nem redirecionamento para domínio de terceiro.
  const roteiro = useRecurso(() => api.roteiroProcuracao(), []);
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

  const criarProcuracaoDireta = useCallback(
    async (linha: LinhaProcuracao, usarAgent: boolean) => {
      // O Agent local precisa ser o único dono da janela automática: ele abre
      // um contexto isolado, aplica AutoSelectCertificateForUrls e limpa a
      // sessão entre clientes. O modo manual mantém a aba simples como
      // fallback quando o escritório opta por não usar uma estação.
      const abaDaReceita = usarAgent
        ? null
        : typeof window === "undefined"
          ? null
          : window.open("", "_blank");
      try {
        const job = await api.criarJobProcuracao(linha.empresa_id);
        if (!usarAgent) {
          await api.intervencaoJobProcuracao(
            job.id,
            "Operação direta iniciada pelo painel neste computador."
          );
        }

        const paginaOficial =
          roteiro.dados?.passos.find((passo) => passo.fase === job.fase && passo.url)?.url ??
          roteiro.dados?.urls_oficiais.portal_servicos;
        if (abaDaReceita && paginaOficial) {
          // A página começa em branco e perde o acesso ao painel antes de ir
          // para a Receita; ela não pode controlar a aba do Cajuru28.
          abaDaReceita.opener = null;
          abaDaReceita.location.replace(paginaOficial);
        }

        avisar({
          tom: "ok",
          titulo: usarAgent ? "Procuração enviada para automação local" : "Procuração iniciada",
          descricao: usarAgent
            ? "O Cajuru Agent abrirá a página oficial com o A1 do cliente. Você só resolve as proteções oficiais e assina na janela do SERPRO."
            : abaDaReceita
              ? "A página oficial da Receita foi aberta. Depois de confirmar, volte aqui e cole a mensagem do portal."
              : "O processo está pronto. Abra a página oficial pelo botão no painel ao lado.",
        });
        recarregar();
        setJobAberto(job.id);
      } catch (erro) {
        abaDaReceita?.close();
        avisar({
          tom: "erro",
          titulo: "Não foi possível iniciar a procuração",
          descricao: mensagemDoErro(erro, "iniciar a procuração"),
        });
      }
    },
    [avisar, recarregar, roteiro.dados]
  );

  const fazerProcuracao = useCallback(
    async (linha: LinhaProcuracao) => {
      try {
        const configuracao = await api.configuracaoProcuracoes();
        if (!configuracao.outorgado_documento) {
          setEmpresaParaFazer(linha);
          setDadosDoEscritorioAbertos(true);
          return;
        }
        await criarProcuracaoDireta(linha, configuracao.processamento_automatico !== false);
      } catch (erro) {
        avisar({
          tom: "erro",
          titulo: "Não foi possível preparar a procuração",
          descricao: mensagemDoErro(erro, "preparar a procuração"),
        });
      }
    },
    [avisar, criarProcuracaoDireta]
  );

  const concluirDadosDoEscritorio = useCallback(
    () => {
      const empresa = empresaParaFazer;
      setDadosDoEscritorioAbertos(false);
      setEmpresaParaFazer(null);
      if (empresa) {
        // A configuração recém-salva usa o padrão automático. A próxima
        // abertura do painel continua permitindo desligá-lo em Configurar.
        void criarProcuracaoDireta(empresa, true);
      }
    },
    [criarProcuracaoDireta, empresaParaFazer]
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
              title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : "Abrir a página oficial e iniciar nesta empresa"}
              onClick={() => fazerProcuracao(linha)}
            >
              Fazer procuração
            </Botao>
          );
        },
      },
    ],
    [fazerProcuracao, somenteLeitura]
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



  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Procurações RFB"
        descricao="Autorizações de Acesso da Receita Federal: quem já autorizou a contabilidade, quem falta e o que trava cada processo."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            {lista.ultimaAtualizacao ? (
              <span className="nums text-xs text-tinta-suave">
                Atualizado <DataHora iso={new Date(lista.ultimaAtualizacao).toISOString()} />
              </span>
            ) : null}
            <BotaoIcone
              rotulo="Atualizar procurações"
              dica="Atualizar procurações"
              icone={<Icone nome="atualizar" className="h-4 w-4" />}
              onClick={recarregar}
              aria-busy={lista.atualizando}
            />
            <Botao
              variante="sutil"
              onClick={() => setImportacaoAberta(true)}
              disabled={somenteLeitura}
              title={
                somenteLeitura
                  ? MOTIVO_SOMENTE_LEITURA
                  : "Traz a relação de procurações do painel do fornecedor, por colagem ou arquivo"
              }
              iconeEsquerda={<Icone nome="importacao" className="h-4 w-4" />}
            >
              Importar lista
            </Botao>
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

      <Aviso tom="info" icone="certificado" titulo="Como funciona neste computador">
        Pesquise a empresa e clique em <strong>Fazer procuração</strong>. Com o Agent local ligado, ele abre automaticamente a página oficial de
        Autorizações com o A1 do cliente e o painel guarda o processo para você só resolver as proteções oficiais e assinar na janela do SERPRO.
        Se o portal pedir CAPTCHA, validação gov.br ou a senha do certificado, faça essa confirmação na própria página oficial: o Cajuru28 não
        pede, guarda nem tenta contornar essas proteções. Sem Agent, o painel mantém o modo manual e abre o mesmo endereço oficial.
      </Aviso>

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
                  · {numero(dados.jobs_na_fila)} na fila
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

      <PainelJob
        jobId={jobAberto}
        aoFechar={() => {
          setJobAberto(null);
          // Chegou com ?job=: devolve a URL limpa para o histórico não reabrir.
          if (jobDaUrl) definir({ job: null });
        }}
        aoMudar={recarregar}
      />
      <DadosDoEscritorio
        aberta={dadosDoEscritorioAbertos}
        aoFechar={() => {
          setDadosDoEscritorioAbertos(false);
          setEmpresaParaFazer(null);
        }}
        aoSalvar={concluirDadosDoEscritorio}
      />
      <ConfiguracaoProcuracoes aberta={configAberta} aoFechar={() => setConfigAberta(false)} aoSalvar={recarregar} />
      <ImportarLista aberta={importacaoAberta} aoFechar={() => setImportacaoAberta(false)} aoImportar={recarregar} />
    </div>
  );
}
