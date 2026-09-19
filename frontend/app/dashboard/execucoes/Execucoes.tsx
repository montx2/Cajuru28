"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { contagemRegressiva, dataCurta, numero, plural, tempoDecorrido, tempoRelativo } from "@/lib/format";
import { estadoDaExecucao } from "@/lib/estados";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { ultimosMeses } from "@/lib/periodo";
import { usePreferencia } from "@/lib/usePreferencia";
import { usePolling } from "@/lib/usePolling";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useBuscaUrl } from "@/lib/useBuscaUrl";
import { useAgora } from "@/components/shell/ProvedorAgora";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { LinhaExecucao } from "@/components/fiscal/LinhaExecucao";
import { Abas, type Aba } from "@/components/ui/Abas";
import { Aviso } from "@/components/ui/Aviso";
import { Botao, BotaoLink } from "@/components/ui/Botao";
import { CabecalhoPagina } from "@/components/ui/Cartao";
import { Busca, Selecao } from "@/components/ui/Campo";
import { Dado } from "@/components/ui/Dado";
import { DialogoConfirmacao } from "@/components/ui/DialogoConfirmacao";
import { EsqueletoLista } from "@/components/ui/Esqueleto";
import { EstadoErro } from "@/components/ui/EstadoErro";
import { EstadoVazio } from "@/components/ui/EstadoVazio";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { DataHora } from "@/components/ui/Formatadores";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Painel } from "@/components/ui/Painel";
import { Tabela, type ColunaTabela, type DensidadeTabela, type OrdenacaoTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import { ROTULO_TIPO, type ExecucaoImportacao, type JanelaProximaConsulta, type TipoDocumentoFiscal } from "@/lib/types";

type AbaExecucao = "agora" | "fila" | "historico" | "erros";

const ABAS_VALIDAS: AbaExecucao[] = ["agora", "fila", "historico", "erros"];

/**
 * Central de execuções: o que a máquina está fazendo, o que fará e o que falhou.
 *
 * O polling cai para 5 s só enquanto existe execução viva — com a tela em
 * repouso, 5 s seria gasto de API à toa. Reprocessar passa por confirmação
 * porque cada disparo consome a janela de 1 hora da SEFAZ.
 */
export function Execucoes() {
  const { definir, ler } = useUrlEstado();
  const { avisar } = useToast();
  const { somenteLeitura } = useSessao();
  const agora = useAgora();
  const busca = useBuscaUrl();

  const aba = (ABAS_VALIDAS.find((valor) => valor === ler("aba")) ?? "agora") as AbaExecucao;
  const empresaFiltro = ler("empresa");
  const tipoFiltro = ler("tipo");

  const [densidade, setDensidade] = usePreferencia<DensidadeTabela>("execucoes-densidade", "confortavel");
  const [colunasVisiveis, setColunasVisiveis] = usePreferencia<string[] | null>("execucoes-colunas", null);
  const [detalhe, setDetalhe] = useState<ExecucaoImportacao | null>(null);
  const [reprocessar, setReprocessar] = useState<ExecucaoImportacao | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erroAcao, setErroAcao] = useState<string | null>(null);

  const central = useRecurso(() => api.centralExecucoes(30), []);
  const historico = useRecurso(
    () => api.listarExecucoes(empresaFiltro ? Number(empresaFiltro) : undefined),
    [empresaFiltro],
    { automatico: aba === "historico" }
  );
  const empresas = useRecurso(() => api.listarEmpresas(), []);

  const aoVivo = central.dados?.agora.length ?? 0;
  useSinalizarAtualizacao(central.atualizando || historico.atualizando);
  usePolling(
    () => {
      central.atualizar();
      if (aba === "historico") historico.atualizar();
    },
    aoVivo > 0 ? 5_000 : 30_000
  );

  const ordenacao: OrdenacaoTabela | null = useMemo(() => {
    const coluna = ler("ordem");
    const direcao = ler("direcao");
    return coluna ? { coluna, direcao: direcao === "asc" ? "asc" : "desc" } : { coluna: "inicio", direcao: "desc" };
  }, [ler]);

  function aoOrdenar(proxima: OrdenacaoTabela | null) {
    definir({ ordem: proxima?.coluna ?? null, direcao: proxima?.direcao ?? null });
  }

  const linhas = useMemo(() => {
    const fonte = aba === "historico" ? historico.dados ?? [] : aba === "erros" ? central.dados?.erros ?? [] : central.dados?.recentes ?? [];
    const termo = busca.valor.trim().toLocaleLowerCase("pt-BR");
    const filtradas = fonte
      .filter((execucao) => (tipoFiltro ? execucao.tipo === tipoFiltro : true))
      .filter((execucao) => (aba === "historico" || !empresaFiltro ? true : execucao.empresa_id === Number(empresaFiltro)))
      .filter((execucao) =>
        termo
          ? `${execucao.empresa_razao_social ?? ""} ${execucao.tipo} ${execucao.mensagem_erro ?? ""} ${execucao.aviso ?? ""}`
              .toLocaleLowerCase("pt-BR")
              .includes(termo)
          : true
      );
    if (!ordenacao) return filtradas;
    const fator = ordenacao.direcao === "asc" ? 1 : -1;
    return [...filtradas].sort((a, b) => fator * compararExecucoes(a, b, ordenacao.coluna));
  }, [aba, busca.valor, central.dados, empresaFiltro, historico.dados, ordenacao, tipoFiltro]);

  const colunas = useMemo<Array<ColunaTabela<ExecucaoImportacao>>>(
    () => [
      {
        id: "empresa",
        cabecalho: "Empresa",
        largura: "min-w-56",
        fixa: true,
        ordenavel: true,
        celula: (execucao) => (
          <Link
            href={`/dashboard/empresa?id=${execucao.empresa_id}&aba=sincronismo`}
            className="block truncate text-tinta underline-offset-4 hover:text-acento hover:underline"
            title={execucao.empresa_razao_social ?? undefined}
          >
            {execucao.empresa_razao_social ?? `Empresa #${numero(execucao.empresa_id)}`}
          </Link>
        ),
      },
      {
        id: "tipo",
        cabecalho: "Tipo",
        ordenavel: true,
        celula: (execucao) => <Etiqueta tom="neutro">{ROTULO_TIPO[execucao.tipo as TipoDocumentoFiscal] ?? execucao.tipo}</Etiqueta>,
      },
      {
        id: "status",
        cabecalho: "Situação",
        ordenavel: true,
        celula: (execucao) => (
          <IndicadorEstado
            {...estadoDaExecucao(execucao.status)}
            detalhe={execucao.mensagem_erro ? <span className="sr-only">: {execucao.mensagem_erro}</span> : undefined}
            titulo={execucao.mensagem_erro ?? execucao.aviso ?? undefined}
          />
        ),
      },
      {
        id: "periodo",
        cabecalho: "Período varrido",
        celula: (execucao) =>
          execucao.data_inicio && execucao.data_fim ? (
            <span className="nums whitespace-nowrap text-tinta-suave">
              {dataCurta(execucao.data_inicio)} – {dataCurta(execucao.data_fim)}
            </span>
          ) : (
            <span className="text-tinta-fraca">—</span>
          ),
      },
      {
        id: "documentos",
        cabecalho: "Importados",
        alinhamento: "direita",
        numerica: true,
        ordenavel: true,
        celula: (execucao) => numero(execucao.documentos_importados),
      },
      {
        id: "cancelados",
        cabecalho: "Cancelados",
        alinhamento: "direita",
        numerica: true,
        ocultaPorPadrao: true,
        celula: (execucao) => numero(execucao.documentos_cancelados),
      },
      {
        id: "eventos",
        cabecalho: "Eventos não reconhecidos",
        dica: "Eventos que o NotesFlow não mapeou — vale olhar quando aparece",
        alinhamento: "direita",
        numerica: true,
        ocultaPorPadrao: true,
        celula: (execucao) => (
          <span className={cn(execucao.eventos_nao_reconhecidos > 0 && "text-espera")}>{numero(execucao.eventos_nao_reconhecidos)}</span>
        ),
      },
      {
        id: "duracao",
        cabecalho: "Duração",
        alinhamento: "direita",
        numerica: true,
        celula: (execucao) => (execucao.finalizado_em ? tempoDecorrido(execucao.iniciado_em, execucao.finalizado_em, agora) : "em curso"),
      },
      {
        id: "inicio",
        cabecalho: "Início",
        ordenavel: true,
        celula: (execucao) => <DataHora iso={execucao.iniciado_em} />,
      },
      {
        id: "nsu",
        cabecalho: "Último NSU",
        alinhamento: "direita",
        numerica: true,
        ocultaPorPadrao: true,
        celula: (execucao) => <span className="nums font-mono text-xs">{execucao.ultimo_nsu ?? "—"}</span>,
      },
      {
        id: "origem",
        cabecalho: "Origem",
        ocultaPorPadrao: true,
        celula: (execucao) => <span className="text-tinta-suave">{execucao.origem ?? "—"}</span>,
      },
    ],
    [agora]
  );

  const filtroAtivo = Boolean(empresaFiltro || tipoFiltro || busca.valor);

  const confirmarReprocessamento = useCallback(async () => {
    if (!reprocessar) return;
    setEnviando(true);
    setErroAcao(null);
    const fallback = ultimosMeses(1);
    try {
      const criada = await api.solicitarImportacao(reprocessar.empresa_id, reprocessar.tipo as TipoDocumentoFiscal, {
        forcar: true,
        data_inicio: reprocessar.data_inicio ?? fallback.inicio,
        data_fim: reprocessar.data_fim ?? fallback.fim,
      });
      avisar({
        tom: criada.status === "aguardando" ? "espera" : "ok",
        titulo: criada.status === "aguardando" ? "Reprocessamento agendado" : "Reprocessamento disparado",
        descricao: `${reprocessar.empresa_razao_social ?? ""} · ${ROTULO_TIPO[reprocessar.tipo as TipoDocumentoFiscal] ?? reprocessar.tipo}`,
      });
      setReprocessar(null);
      central.atualizar();
      historico.atualizar();
    } catch (falha) {
      setErroAcao(falha instanceof Error ? falha.message : "Não foi possível reprocessar.");
    } finally {
      setEnviando(false);
    }
  }, [avisar, central, historico, reprocessar]);

  const abas: Aba[] = [
    { valor: "agora", rotulo: "Em andamento", icone: "execucao", contador: central.dados?.agora.length },
    { valor: "fila", rotulo: "Próximas janelas", icone: "ampulheta", contador: central.dados?.proximas.length },
    { valor: "historico", rotulo: "Histórico", icone: "historico" },
    { valor: "erros", rotulo: "Erros", icone: "risco", contador: central.dados?.erros.length },
  ];

  const emAndamento = central.dados?.agora ?? [];

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Execuções"
        descricao="O que a captura está fazendo agora, o que fará na próxima janela e o que falhou."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao
              variante="sutil"
              onClick={() => {
                central.atualizar();
                historico.atualizar();
              }}
              carregando={central.atualizando || historico.atualizando}
              iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}
            >
              Atualizar
            </Botao>
            <BotaoLink variante="primaria" href={`/dashboard/importacoes${empresaFiltro ? `?empresa_ids=${empresaFiltro}` : ""}`} iconeEsquerda={<Icone nome="importacao" className="h-4 w-4" />}>
              Disparar importação
            </BotaoLink>
          </div>
        }
      />

      {aoVivo > 0 ? (
        <Aviso tom="info" icone="execucao" compacto>
          {numero(aoVivo)} {plural(aoVivo, "execução em andamento", "execuções em andamento")} — esta tela se atualiza sozinha a cada 5 segundos.
        </Aviso>
      ) : null}

      <Abas rotulo="Visão das execuções" idBase="aba-execucao" abas={abas} valor={aba} aoMudar={(valor) => definir({ aba: valor })} />

      {aba === "agora" ? (
        central.carregando ? (
          <EsqueletoLista itens={3} linhas={2} />
        ) : central.erro ? (
          <EstadoErro erro={central.erro} aoTentarNovamente={central.atualizar} contexto="carregar as execuções em andamento" />
        ) : emAndamento.length > 0 ? (
          <ul className="divide-y divide-traco rounded-cartao border border-traco bg-superficie">
            {emAndamento.map((execucao) => (
              <LinhaExecucao key={execucao.execucao_id} execucao={execucao} />
            ))}
          </ul>
        ) : (
          <EstadoVazio
            titulo="Nenhuma execução em andamento"
            instrucao="A captura automática dispara na próxima janela. Se houver documento faltando, dispare manualmente pelo período e empresa."
            acao={<BotaoLink variante="secundaria" href="/dashboard/importacoes">Ir para Importações</BotaoLink>}
            icone="execucao"
          />
        )
      ) : null}

      {aba === "fila" ? (
        central.carregando ? (
          <EsqueletoLista itens={4} linhas={2} />
        ) : central.erro ? (
          <EstadoErro erro={central.erro} aoTentarNovamente={central.atualizar} contexto="carregar as próximas janelas" />
        ) : (central.dados?.proximas.length ?? 0) > 0 ? (
          <Tabela
            linhas={central.dados?.proximas ?? []}
            chaveDaLinha={(janela: JanelaProximaConsulta) => `${janela.empresa_id}-${janela.tipo}`}
            legenda="Próximas consultas agendadas"
            colunas={[
              {
                id: "empresa",
                cabecalho: "Empresa",
                celula: (janela: JanelaProximaConsulta) => (
                  <Link href={`/dashboard/empresa?id=${janela.empresa_id}&aba=sincronismo`} className="truncate text-tinta underline-offset-4 hover:text-acento hover:underline">
                    {janela.razao_social}
                  </Link>
                ),
              },
              { id: "tipo", cabecalho: "Tipo", celula: (janela: JanelaProximaConsulta) => <Etiqueta>{janela.tipo.toUpperCase()}</Etiqueta> },
              {
                id: "proxima",
                cabecalho: "Próxima consulta",
                alinhamento: "direita",
                celula: (janela: JanelaProximaConsulta) => (
                  <span className="nums whitespace-nowrap text-tinta">
                    {contagemRegressiva(janela.proxima_consulta_em, agora) ?? tempoRelativo(janela.proxima_consulta_em, agora)}
                    <span className="ml-2 text-xs text-tinta-fraca">{new Date(janela.proxima_consulta_em).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</span>
                  </span>
                ),
              },
              {
                id: "pendencia",
                cabecalho: "Pendência",
                alinhamento: "direita",
                numerica: true,
                celula: (janela: JanelaProximaConsulta) => numero(janela.pendencia),
              },
              {
                id: "situacao",
                cabecalho: "Situação",
                celula: (janela: JanelaProximaConsulta) =>
                  janela.bloqueada ? (
                    <IndicadorEstado tom="espera" rotulo="Janela SEFAZ" icone="ampulheta" />
                  ) : (
                    <IndicadorEstado tom="ok" rotulo="Liberada" icone="verificar-circulo" />
                  ),
              },
            ]}
            estados={{
              carregando: false,
              vazioTitulo: "Nenhuma janela agendada",
              vazioInstrucao: "As próximas consultas aparecem quando a agenda automática tem trabalho a fazer.",
            }}
            densidade={densidade}
            aoMudarDensidade={setDensidade}
          />
        ) : (
          <EstadoVazio titulo="Nenhuma janela agendada" instrucao="Todas as empresas estão em dia ou com sincronismo automático desligado." icone="ampulheta" />
        )
      ) : null}

      {aba === "historico" || aba === "erros" ? (
        <Tabela
          linhas={linhas}
          colunas={colunas}
          chaveDaLinha={(execucao) => execucao.id}
          legenda={aba === "erros" ? "Execuções com erro" : "Histórico de execuções"}
          ordenacao={ordenacao}
          aoOrdenar={aoOrdenar}
          aoAbrirLinha={setDetalhe}
          densidade={densidade}
          aoMudarDensidade={setDensidade}
          colunasVisiveis={colunasVisiveis ?? undefined}
          aoMudarColunas={(ids) => setColunasVisiveis(ids)}
          virtualizar
          estados={{
            carregando: aba === "historico" ? historico.carregando : central.carregando,
            erro: aba === "historico" ? historico.erro : central.erro,
            aoTentarNovamente: aba === "historico" ? historico.atualizar : central.atualizar,
            vazioTitulo: aba === "erros" ? "Nenhuma execução com erro" : "Nenhuma execução neste recorte",
            vazioInstrucao:
              aba === "erros"
                ? "Nada falhou nas últimas execuções. Quando algo falhar, o motivo e o passo seguinte aparecem aqui."
                : "Ajuste empresa, tipo ou busca — ou dispare uma importação para gerar histórico.",
            vazioAcao:
              aba === "erros" ? undefined : (
                <BotaoLink variante="secundaria" href="/dashboard/importacoes">
                  Disparar importação
                </BotaoLink>
              ),
            vazioIcone: aba === "erros" ? "verificar-circulo" : "historico",
            filtroAtivo,
            aoLimparFiltro: filtroAtivo
              ? () => {
                  definir({ empresa: null, tipo: null, busca: null });
                  busca.aoMudar("");
                }
              : undefined,
          }}
          ferramentas={
            <div className="flex flex-wrap items-end gap-2">
              <Busca rotulo="Buscar execução" placeholder="Empresa, tipo ou mensagem de erro" valor={busca.valor} aoMudar={busca.aoMudar} className="min-w-56 flex-1" />
              <Selecao
                rotulo="Empresa"
                className="w-56"
                value={empresaFiltro}
                onChange={(evento) => definir({ empresa: evento.target.value || null })}
                opcoes={[
                  { valor: "", rotulo: "Todas as empresas" },
                  ...(empresas.dados ?? []).map((empresa) => ({ valor: String(empresa.id), rotulo: empresa.razao_social })),
                ]}
              />
              <Selecao
                rotulo="Tipo"
                className="w-40"
                value={tipoFiltro}
                onChange={(evento) => definir({ tipo: evento.target.value || null })}
                opcoes={[
                  { valor: "", rotulo: "Todos os tipos" },
                  ...(["nfse", "nfe", "cte"] as TipoDocumentoFiscal[]).map((tipo) => ({ valor: tipo, rotulo: ROTULO_TIPO[tipo] })),
                ]}
              />
            </div>
          }
          rodape={
            <p className="text-xs text-tinta-suave">
              {numero(linhas.length)} {plural(linhas.length, "execução", "execuções")} no recorte · clique em uma linha para ver o detalhe técnico
            </p>
          }
        />
      ) : null}

      <Painel
        aberto={detalhe !== null}
        aoFechar={() => setDetalhe(null)}
        titulo={detalhe ? `Execução #${numero(detalhe.id)}` : "Execução"}
        contexto={detalhe ? `${detalhe.empresa_razao_social ?? ""} · ${ROTULO_TIPO[detalhe.tipo as TipoDocumentoFiscal] ?? detalhe.tipo}` : undefined}
        acoes={
          detalhe ? (
            <Link href={`/dashboard/empresa?id=${detalhe.empresa_id}&aba=sincronismo`} className="text-xs font-medium text-acento underline-offset-4 hover:underline">
              Ver empresa
            </Link>
          ) : undefined
        }
        rodape={
          detalhe ? (
            <div className="flex flex-wrap items-center gap-2">
              <Botao
                variante="primaria"
                onClick={() => setReprocessar(detalhe)}
                disabled={somenteLeitura}
                title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
                iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}
              >
                Reprocessar período
              </Botao>
              <BotaoLink
                variante="sutil"
                href={`/dashboard/importacoes?empresa_ids=${detalhe.empresa_id}&tipos=${detalhe.tipo}&data_inicio=${detalhe.data_inicio ?? ""}&data_fim=${detalhe.data_fim ?? ""}`}
              >
                Abrir em Importações
              </BotaoLink>
            </div>
          ) : undefined
        }
      >
        {detalhe ? <DetalheExecucao execucao={detalhe} agora={agora} /> : null}
      </Painel>

      <DialogoConfirmacao
        aberto={reprocessar !== null}
        aoFechar={() => {
          setReprocessar(null);
          setErroAcao(null);
        }}
        aoConfirmar={confirmarReprocessamento}
        carregando={enviando}
        erro={erroAcao}
        titulo="Reprocessar esta execução"
        consequencia={
          reprocessar
            ? `Uma nova captura será disparada para ${reprocessar.empresa_razao_social ?? "a empresa"} (${ROTULO_TIPO[reprocessar.tipo as TipoDocumentoFiscal] ?? reprocessar.tipo}), no período ${
                reprocessar.data_inicio ? dataCurta(reprocessar.data_inicio) : "—"
              } a ${reprocessar.data_fim ? dataCurta(reprocessar.data_fim) : "—"}, ignorando o cursor atual.`
            : ""
        }
        impacto="Cada consulta consome a janela de 1 hora da SEFAZ para esta empresa e tipo. Documentos já importados não são duplicados."
        rotuloConfirmar="Reprocessar"
        tom="normal"
      />
    </div>
  );
}

function compararExecucoes(a: ExecucaoImportacao, b: ExecucaoImportacao, coluna: string): number {
  switch (coluna) {
    case "empresa":
      return (a.empresa_razao_social ?? "").localeCompare(b.empresa_razao_social ?? "", "pt-BR");
    case "tipo":
      return a.tipo.localeCompare(b.tipo);
    case "status":
      return a.status.localeCompare(b.status);
    case "documentos":
      return a.documentos_importados - b.documentos_importados;
    case "inicio":
      return new Date(a.iniciado_em).getTime() - new Date(b.iniciado_em).getTime();
    default:
      return 0;
  }
}

function DetalheExecucao({ execucao, agora }: { execucao: ExecucaoImportacao; agora: number }) {
  const estado = estadoDaExecucao(execucao.status);
  const duracao = execucao.finalizado_em
    ? tempoDecorrido(execucao.iniciado_em, execucao.finalizado_em, agora)
    : tempoDecorrido(execucao.iniciado_em, null, agora);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <IndicadorEstado {...estado} />
        {execucao.forcar ? <Etiqueta tom="espera">Cursor ignorado</Etiqueta> : null}
        {execucao.origem ? <Etiqueta tom="neutro">{execucao.origem}</Etiqueta> : null}
        {execucao.tentativas && execucao.tentativas > 1 ? <Etiqueta tom="espera">{numero(execucao.tentativas)} tentativas</Etiqueta> : null}
      </div>

      {execucao.mensagem_erro ? (
        <Aviso tom="erro" titulo="Por que falhou">
          <p className="text-sm leading-6">{execucao.mensagem_erro}</p>
          <p className="mt-2 text-sm leading-6">
            Próximo passo: confira se o certificado A1 da empresa está válido e se a SEFAZ não está em janela de espera. Depois, reprocesse o período.
          </p>
        </Aviso>
      ) : null}

      {execucao.aviso ? (
        <Aviso tom="espera" titulo="Aviso">
          {execucao.aviso}
        </Aviso>
      ) : null}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <Dado rotulo="Início" valor={<DataHora iso={execucao.iniciado_em} />} />
        <Dado rotulo="Fim" valor={execucao.finalizado_em ? <DataHora iso={execucao.finalizado_em} /> : "em curso"} />
        <Dado rotulo="Duração" valor={<span className="nums">{duracao}</span>} />
        <Dado rotulo="Período varrido" valor={execucao.data_inicio && execucao.data_fim ? <span className="nums">{`${dataCurta(execucao.data_inicio)} – ${dataCurta(execucao.data_fim)}`}</span> : "—"} />
        <Dado rotulo="Documentos no período" valor={<span className="nums">{numero(execucao.documentos_no_periodo)}</span>} />
        <Dado rotulo="Importados" valor={<span className="nums">{numero(execucao.documentos_importados)}</span>} />
        <Dado rotulo="Cancelados" valor={<span className="nums">{numero(execucao.documentos_cancelados)}</span>} />
        <Dado rotulo="Eventos não reconhecidos" valor={<span className="nums">{numero(execucao.eventos_nao_reconhecidos)}</span>} />
        <Dado rotulo="Último NSU" valor={execucao.ultimo_nsu ? <span className="nums font-mono text-xs">{execucao.ultimo_nsu}</span> : "—"} />
        <Dado
          rotulo="Bloqueado até"
          valor={
            execucao.bloqueado_ate ? (
              <span className="nums text-espera">
                {contagemRegressiva(execucao.bloqueado_ate, agora) ?? dataCurta(execucao.bloqueado_ate)}
              </span>
            ) : (
              "não bloqueada"
            )
          }
        />
      </dl>

      <div className="border-t border-traco pt-4 text-xs">
        <Link href={`/dashboard/documentos?empresa_id=${execucao.empresa_id}`} className="font-medium text-acento underline-offset-4 hover:underline">
          Ver documentos desta empresa
        </Link>
      </div>
    </div>
  );
}

