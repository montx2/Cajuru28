"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type FiltrosDocumentos } from "@/lib/api";
import { bytesParaTexto, chaveEmGrupos, dataCurta, numero, plural } from "@/lib/format";
import { estadoDoDocumento } from "@/lib/estados";
import { mensagemDoErro } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { paraFiltro, rotuloPeriodo, sufixoArquivo } from "@/lib/periodo";
import { useBuscaUrl } from "@/lib/useBuscaUrl";
import { usePreferencia } from "@/lib/usePreferencia";
import { usePeriodoUrl } from "@/lib/usePeriodoUrl";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { PainelDocumento } from "@/components/fiscal/PainelDocumento";
import { SeletorPeriodo } from "@/components/fiscal/SeletorPeriodo";
import { Botao, BotaoLink } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { Busca, Selecao } from "@/components/ui/Campo";
import { CopiavelMono } from "@/components/ui/CopiavelMono";
import { Dado } from "@/components/ui/Dado";
import { DialogoConfirmacao } from "@/components/ui/DialogoConfirmacao";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Cnpj, ValorMoeda } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { Modal } from "@/components/ui/Modal";
import { Paginacao } from "@/components/ui/Paginacao";
import { Tabela, type ColunaTabela, type DensidadeTabela } from "@/components/ui/Tabela";
import { useToast } from "@/components/ui/Toast";
import {
  ROTULO_TIPO,
  TIPOS,
  type DirecaoDocumento,
  type DocumentoDetalhe,
  type DocumentoFiscal,
  type EstimativaExportacao,
  type LeiauteDocumento,
  type StatusDocumentoFiscal,
  type TipoDocumentoFiscal,
} from "@/lib/types";

/** Passo de carregamento: a API aceita até 5 000, mas 500 já é uma tela cheia. */
const PASSO = 500;

const DIRECOES: DirecaoDocumento[] = ["tomada", "prestada"];
const STATUS: StatusDocumentoFiscal[] = ["normal", "cancelada"];
const LEIAUTES: LeiauteDocumento[] = ["completo", "resumo", "metadados"];

/**
 * Acervo de documentos: a tela de maior volume do produto.
 *
 * Três decisões que se explicam pelo uso real:
 *  1. o período é obrigatório (a API responde 422 sem ele) e vive na URL;
 *  2. ordenação e seleção valem para as linhas **carregadas** — a API não ordena
 *     por parâmetro, e fingir que ordena o universo inteiro seria mentira;
 *  3. exclusão em massa exige digitar a palavra: é irreversível e apaga arquivo
 *     do disco, não só registro.
 */
export function Documentos() {
  const { definir, ler, lerNumero } = useUrlEstado();
  const { periodo, aoMudar: aoMudarPeriodo, pronto } = usePeriodoUrl();
  const busca = useBuscaUrl();
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();

  const tipo = ler("tipo");
  const direcao = ler("direcao");
  const status = ler("status");
  const leiaute = ler("leiaute");
  const empresa = lerNumero("empresa");
  const documentoAberto = lerNumero("doc") ?? null;

  const [densidade, setDensidade] = usePreferencia<DensidadeTabela>("documentos-densidade", "compacta");
  const [colunasVisiveis, setColunasVisiveis] = usePreferencia<string[] | null>("documentos-colunas", null);
  const [extras, setExtras] = useState<DocumentoFiscal[]>([]);
  const [carregandoMais, setCarregandoMais] = useState(false);
  const [selecao, setSelecao] = useState<Set<string>>(new Set());

  const [exportacao, setExportacao] = useState<"xml" | "csv" | null>(null);
  const [estimativa, setEstimativa] = useState<EstimativaExportacao | null>(null);
  const [carregandoEstimativa, setCarregandoEstimativa] = useState(false);
  const [erroExportacao, setErroExportacao] = useState<string | null>(null);
  const [baixando, setBaixando] = useState(false);

  const [excluirLote, setExcluirLote] = useState<number[] | null>(null);
  const [excluirUm, setExcluirUm] = useState<DocumentoDetalhe | null>(null);
  const [enviandoExclusao, setEnviandoExclusao] = useState(false);
  const [erroExclusao, setErroExclusao] = useState<string | null>(null);
  const [completandoXml, setCompletandoXml] = useState(false);

  const filtros = useMemo<FiltrosDocumentos>(() => {
    const base: FiltrosDocumentos = { ...paraFiltro(periodo) };
    if (TIPOS.includes(tipo as TipoDocumentoFiscal)) base.tipo = tipo as TipoDocumentoFiscal;
    if (DIRECOES.includes(direcao as DirecaoDocumento)) base.direcao = direcao as DirecaoDocumento;
    if (STATUS.includes(status as StatusDocumentoFiscal)) base.status = status as StatusDocumentoFiscal;
    if (LEIAUTES.includes(leiaute as LeiauteDocumento)) base.leiaute = leiaute as LeiauteDocumento;
    if (empresa) base.empresa_id = empresa;
    if (busca.valor.trim()) base.busca = busca.valor.trim();
    return base;
  }, [busca.valor, direcao, empresa, leiaute, periodo, status, tipo]);

  const chaveFiltros = useMemo(() => JSON.stringify(filtros), [filtros]);

  const documentos = useRecurso(() => api.listarDocumentos({ ...filtros, limit: PASSO, offset: 0 }), [chaveFiltros], { automatico: pronto });
  const resumo = useRecurso(() => api.resumoDocumentos(filtros), [chaveFiltros], { automatico: pronto });
  const empresas = useRecurso(() => api.listarEmpresas(), []);

  useSinalizarAtualizacao(documentos.atualizando || resumo.atualizando);

  // Trocou o filtro, a seleção anterior não significa mais nada.
  useEffect(() => {
    setExtras([]);
    setSelecao(new Set());
  }, [chaveFiltros]);

  const razaoPorId = useMemo(() => {
    const mapa = new Map<number, string>();
    for (const item of empresas.dados ?? []) mapa.set(item.id, item.razao_social);
    return mapa;
  }, [empresas.dados]);

  const ordem = ler("ordem") || "emissao";
  const sentido = ler("sentido") === "asc" ? "asc" : "desc";

  const linhas = useMemo(() => {
    const todas = [...(documentos.dados ?? []), ...extras];
    const fator = sentido === "asc" ? 1 : -1;
    return [...todas].sort((a, b) => fator * compararDocumentos(a, b, ordem, razaoPorId));
  }, [documentos.dados, extras, ordem, razaoPorId, sentido]);

  const idsSelecionados = useMemo(
    () => Array.from(selecao).map((chave) => Number(chave)).filter((id) => Number.isFinite(id)),
    [selecao]
  );

  const total = resumo.dados?.total ?? null;
  const filtroAtivo = Boolean(tipo || direcao || status || leiaute || empresa || busca.valor.trim());

  function limparFiltros() {
    definir({ tipo: null, direcao: null, status: null, leiaute: null, empresa: null, busca: null, ordem: null, sentido: null });
    busca.aoMudar("");
  }

  const carregarMais = useCallback(async () => {
    setCarregandoMais(true);
    try {
      const proximos = await api.listarDocumentos({ ...filtros, limit: PASSO, offset: linhas.length });
      setExtras((atual) => [...atual, ...proximos]);
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível carregar mais", descricao: mensagemDoErro(falha, "carregar mais documentos") });
    } finally {
      setCarregandoMais(false);
    }
  }, [avisar, filtros, linhas.length]);

  async function estimarExportacao(qual: "xml" | "csv") {
    setExportacao(qual);
    setEstimativa(null);
    setErroExportacao(null);
    setCarregandoEstimativa(true);
    try {
      setEstimativa(await api.estimarExportacao(filtros));
    } catch (falha) {
      setErroExportacao(mensagemDoErro(falha, "estimar o tamanho do download"));
    } finally {
      setCarregandoEstimativa(false);
    }
  }

  async function confirmarExportacao() {
    if (!exportacao) return;
    setBaixando(true);
    setErroExportacao(null);
    try {
      if (exportacao === "xml") {
        await api.baixarZip(filtros, `NotasFlow_xmls_${sufixoArquivo(periodo)}.zip`);
        avisar({ tom: "ok", titulo: "ZIP gerado", descricao: `${rotuloPeriodo(periodo)} · ${estimativa ? numero(estimativa.documentos) : ""} documentos` });
      } else {
        await api.baixarCsvDocumentos(filtros, `NotasFlow_relacao_${sufixoArquivo(periodo)}.csv`);
        avisar({ tom: "ok", titulo: "Relação em CSV gerada", descricao: rotuloPeriodo(periodo) });
      }
      setExportacao(null);
    } catch (falha) {
      setErroExportacao(mensagemDoErro(falha, "baixar os arquivos"));
    } finally {
      setBaixando(false);
    }
  }

  async function baixarSelecao(qual: "xml" | "csv") {
    if (idsSelecionados.length === 0) return;
    setBaixando(true);
    try {
      const filtroSelecao = { ...filtros, documento_ids: idsSelecionados.join(",") };
      if (qual === "xml") {
        await api.baixarZip(filtroSelecao, `NotasFlow_selecao_${sufixoArquivo(periodo)}.zip`);
        avisar({ tom: "ok", titulo: "XMLs da seleção baixados", descricao: `${numero(idsSelecionados.length)} ${plural(idsSelecionados.length, "documento", "documentos")}` });
      } else {
        await api.baixarCsvDocumentos(filtroSelecao, `NotasFlow_selecao_${sufixoArquivo(periodo)}.csv`);
        avisar({ tom: "ok", titulo: "CSV da seleção gerado", descricao: `${numero(idsSelecionados.length)} ${plural(idsSelecionados.length, "documento", "documentos")}` });
      }
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível baixar a seleção", descricao: mensagemDoErro(falha, "baixar a seleção") });
    } finally {
      setBaixando(false);
    }
  }

  async function excluir(ids: number[], origem: "lote" | "unico") {
    setEnviandoExclusao(true);
    setErroExclusao(null);
    try {
      const resultado = ids.length === 1 ? await api.excluirDocumento(ids[0]) : await api.excluirDocumentos(ids);
      avisar({
        tom: "ok",
        titulo: `${numero(resultado.excluidos)} ${plural(resultado.excluidos, "documento excluído", "documentos excluídos")}`,
        descricao: `${numero(resultado.arquivos_removidos)} ${plural(resultado.arquivos_removidos, "arquivo removido", "arquivos removidos")} do disco`,
      });
      setExcluirLote(null);
      setExcluirUm(null);
      setSelecao(new Set());
      if (origem === "unico") definir({ doc: null });
      documentos.atualizar();
      resumo.atualizar();
    } catch (falha) {
      setErroExclusao(mensagemDoErro(falha, "excluir documentos"));
    } finally {
      setEnviandoExclusao(false);
    }
  }

  async function completarXmls() {
    setCompletandoXml(true);
    try {
      const resultado = await api.completarXmls(empresa, 50);
      avisar({
        tom: resultado.disparado ? "ok" : "espera",
        titulo: resultado.disparado ? "Busca de XMLs completos disparada" : "Nada a completar agora",
        descricao: resultado.aviso,
      });
      documentos.atualizar();
      resumo.atualizar();
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível completar os XMLs", descricao: mensagemDoErro(falha, "completar XMLs") });
    } finally {
      setCompletandoXml(false);
    }
  }

  const colunas = useMemo<Array<ColunaTabela<DocumentoFiscal>>>(
    () => [
      {
        id: "emissao",
        cabecalho: "Emissão",
        largura: "w-28",
        ordenavel: true,
        celula: (documento) => <span className="nums whitespace-nowrap text-tinta">{dataCurta(documento.data_emissao)}</span>,
      },
      {
        id: "tipo",
        cabecalho: "Tipo",
        ordenavel: true,
        celula: (documento) => <Etiqueta tom="neutro">{ROTULO_TIPO[documento.tipo] ?? documento.tipo}</Etiqueta>,
      },
      {
        id: "numero",
        cabecalho: "Número",
        ordenavel: true,
        celula: (documento) => (
          <span className="nums whitespace-nowrap text-tinta">
            {documento.numero ?? "—"}
            {documento.serie ? <span className="ml-1.5 text-xs text-tinta-suave">série {documento.serie}</span> : null}
          </span>
        ),
      },
      {
        id: "parte",
        cabecalho: "Emitente / destinatário",
        dica: "Emitente nas tomadas, destinatário nas prestadas",
        largura: "min-w-60",
        ordenavel: true,
        celula: (documento) => {
          const nome = documento.direcao === "tomada" ? documento.emitente_nome : documento.destinatario_nome;
          const documentoDaParte = documento.direcao === "tomada" ? documento.emitente_documento : documento.destinatario_documento;
          return (
            <span className="block min-w-0">
              <span className="block truncate text-tinta" title={nome ?? undefined}>
                {nome ?? "Parte não informada"}
              </span>
              {documentoDaParte ? <Cnpj valor={documentoDaParte} copiar={false} className="text-xs text-tinta-suave" /> : null}
            </span>
          );
        },
      },
      {
        id: "empresa",
        cabecalho: "Empresa",
        largura: "min-w-48",
        ordenavel: true,
        celula: (documento) => (
          <Link
            href={`/dashboard/empresa?id=${documento.empresa_id}`}
            onClick={(evento) => evento.stopPropagation()}
            className="block truncate text-tinta-suave underline-offset-4 hover:text-acento hover:underline"
            title={razaoPorId.get(documento.empresa_id)}
          >
            {razaoPorId.get(documento.empresa_id) ?? `#${numero(documento.empresa_id)}`}
          </Link>
        ),
      },
      {
        id: "valor",
        cabecalho: "Valor",
        alinhamento: "direita",
        numerica: true,
        ordenavel: true,
        celula: (documento) => <ValorMoeda valor={documento.valor_total} cancelado={documento.status === "cancelada"} />,
      },
      {
        id: "status",
        cabecalho: "Situação",
        ordenavel: true,
        celula: (documento) => (
          <IndicadorEstado
            {...estadoDoDocumento(documento)}
            titulo={documento.motivo_cancelamento ?? (documento.leiaute === "resumo" ? "Recebido em resumo — XML completo pendente" : documento.leiaute === "metadados" ? "NFS-e sem XML original; exporte o período para obter o JSON normalizado." : undefined)}
          />
        ),
      },
      {
        id: "chave",
        cabecalho: "Chave de acesso",
        largura: "min-w-52",
        celula: (documento) => (
          <CopiavelMono
            valor={documento.chave_acesso}
            exibicao={chaveEmGrupos(documento.chave_acesso)}
            rotulo={`Chave de acesso do documento ${documento.numero ?? documento.id}`}
            className="max-w-56"
          />
        ),
      },
      {
        id: "nsu",
        cabecalho: "NSU",
        alinhamento: "direita",
        numerica: true,
        ocultaPorPadrao: true,
        celula: (documento) => <span className="nums font-mono text-xs">{documento.nsu ?? "—"}</span>,
      },
      {
        id: "origem",
        cabecalho: "Origem",
        ocultaPorPadrao: true,
        celula: (documento) => <span className="text-tinta-suave">{documento.origem ?? "—"}</span>,
      },
    ],
    [razaoPorId]
  );

  const indicadores: KpiProps[] = resumo.dados
    ? [
        { rotulo: "Documentos no recorte", valor: numero(resumo.dados.total), contexto: rotuloPeriodo(periodo), carregando: resumo.atualizando },
        { rotulo: "Normais", valor: numero(resumo.dados.normais), tom: "ok" },
        {
          rotulo: "Canceladas",
          valor: numero(resumo.dados.canceladas),
          tom: resumo.dados.canceladas > 0 ? "espera" : "neutro",
          href: "/dashboard/documentos?status=cancelada",
        },
        ...TIPOS.filter((tipoItem) => (resumo.dados?.por_tipo[tipoItem] ?? 0) > 0).map((tipoItem) => ({
          rotulo: ROTULO_TIPO[tipoItem],
          valor: numero(resumo.dados?.por_tipo[tipoItem] ?? 0),
          contexto: "no recorte",
          href: `/dashboard/documentos?tipo=${tipoItem}`,
        })),
      ]
    : [];

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        titulo="Documentos"
        descricao="Acervo capturado: conferir chave, baixar XML, exportar a relação e completar documentos que chegaram em resumo."
        acoes={
          <div className="flex flex-wrap items-center gap-2">
            <Botao
              variante="sutil"
              onClick={() => {
                documentos.atualizar();
                resumo.atualizar();
              }}
              carregando={documentos.atualizando}
              iconeEsquerda={<Icone nome="atualizar" className="h-4 w-4" />}
            >
              Atualizar
            </Botao>
            <Botao
              variante="secundaria"
              onClick={() => estimarExportacao("csv")}
              disabled={!pronto}
              iconeEsquerda={<Icone nome="baixar" className="h-4 w-4" />}
            >
              Exportar CSV
            </Botao>
            <Botao
              variante="primaria"
              onClick={() => estimarExportacao("xml")}
              disabled={!pronto}
              iconeEsquerda={<Icone nome="documento" className="h-4 w-4" />}
            >
              Baixar XML do filtro
            </Botao>
          </div>
        }
      />

      <Cartao densidade="compacta" className="nao-imprimir">
        <div className="space-y-3">
          <SeletorPeriodo periodo={periodo} aoMudar={aoMudarPeriodo} obrigatorio />

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            <Busca
              rotuloVisivel
              rotulo="Buscar documento"
              placeholder="Chave, número, NSU, emitente ou destinatário"
              valor={busca.valor}
              aoMudar={busca.aoMudar}
              className="md:col-span-2"
            />
            <Selecao
              rotulo="Tipo"
              value={tipo}
              onChange={(evento) => definir({ tipo: evento.target.value || null })}
              opcoes={[{ valor: "", rotulo: "Todos os tipos" }, ...TIPOS.map((item) => ({ valor: item, rotulo: ROTULO_TIPO[item] }))]}
            />
            <Selecao
              rotulo="Direção"
              value={direcao}
              onChange={(evento) => definir({ direcao: evento.target.value || null })}
              opcoes={[
                { valor: "", rotulo: "Tomadas e prestadas" },
                { valor: "tomada", rotulo: "Tomadas (recebidas)" },
                { valor: "prestada", rotulo: "Prestadas (emitidas)" },
              ]}
            />
            <Selecao
              rotulo="Situação"
              value={status}
              onChange={(evento) => definir({ status: evento.target.value || null })}
              opcoes={[
                { valor: "", rotulo: "Normais e canceladas" },
                ...STATUS.map((item) => ({ valor: item, rotulo: item === "normal" ? "Somente normais" : "Somente canceladas" })),
              ]}
            />
            <Selecao
              rotulo="Leiaute"
              value={leiaute}
              onChange={(evento) => definir({ leiaute: evento.target.value || null })}
              opcoes={[
                { valor: "", rotulo: "Todos os leiautes" },
                { valor: "completo", rotulo: "Somente XML completo" },
                { valor: "resumo", rotulo: "Somente resumo (pendentes)" },
                { valor: "metadados", rotulo: "Somente metadados (sem XML)" },
              ]}
            />
            <Selecao
              rotulo="Empresa"
              value={empresa ? String(empresa) : ""}
              onChange={(evento) => definir({ empresa: evento.target.value || null })}
              className="md:col-span-2 xl:col-span-1"
              opcoes={[
                { valor: "", rotulo: "Todas as empresas" },
                ...(empresas.dados ?? []).map((item) => ({ valor: String(item.id), rotulo: item.razao_social })),
              ]}
            />
          </div>

          {leiaute === "metadados" ? (
            <div className="rounded-controle border border-espera/40 bg-espera-tenue px-3 py-2 text-sm text-espera">
              Estas NFS-e foram registradas sem XML original. A exportação do período inclui um JSON normalizado e a relação CSV; não há XML a completar pela SEFAZ.
            </div>
          ) : null}
          {leiaute === "resumo" ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-controle border border-espera/40 bg-espera-tenue px-3 py-2">
              <p className="text-sm text-espera">
                Estes documentos chegaram apenas em resumo (resNFe). O XML completo é buscado pela chave de acesso, na fila da SEFAZ.
              </p>
              <Botao
                variante="secundaria"
                tamanho="sm"
                onClick={completarXmls}
                carregando={completandoXml}
                disabled={somenteLeitura}
                title={somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined}
                iconeEsquerda={<Icone nome="sincronizar" className="h-3.5 w-3.5" />}
              >
                Completar XMLs agora
              </Botao>
            </div>
          ) : null}
        </div>
      </Cartao>

      {resumo.dados ? <GradeKpis itens={indicadores} colunas={5} rotulo="Resumo do recorte" /> : null}

      <Tabela
        linhas={linhas}
        colunas={colunas}
        chaveDaLinha={(documento) => documento.id}
        legenda="Documentos fiscais do período"
        aoAbrirLinha={(documento) => definir({ doc: documento.id })}
        classeLinha={classeDaLinhaDocumento}
        ordenacao={{ coluna: ordem, direcao: sentido }}
        aoOrdenar={(proxima) => definir({ ordem: proxima?.coluna ?? null, sentido: proxima?.direcao ?? null })}
        densidade={densidade}
        aoMudarDensidade={setDensidade}
        colunasVisiveis={colunasVisiveis ?? undefined}
        aoMudarColunas={(ids) => setColunasVisiveis(ids)}
        altura="h-[calc(100vh-24rem)]"
        selecao={{
          chaves: selecao,
          aoMudar: setSelecao,
          totalNoFiltro: total ?? undefined,
        }}
        barraDeSelecao={({ quantidade, limpar }) => (
          <div className="flex flex-wrap items-center gap-2">
            <Botao variante="secundaria" tamanho="sm" onClick={() => baixarSelecao("xml")} carregando={baixando} iconeEsquerda={<Icone nome="documento" className="h-3.5 w-3.5" />}>
              Baixar XML ({numero(quantidade)})
            </Botao>
            <Botao variante="secundaria" tamanho="sm" onClick={() => baixarSelecao("csv")} iconeEsquerda={<Icone nome="baixar" className="h-3.5 w-3.5" />}>
              Exportar CSV ({numero(quantidade)})
            </Botao>
            {somenteLeitura ? (
              <span className="text-xs text-tinta-suave" title={MOTIVO_SOMENTE_LEITURA}>
                Exclusão indisponível para o seu papel
              </span>
            ) : (
              <Botao
                variante="perigo-sutil"
                tamanho="sm"
                onClick={() => setExcluirLote(idsSelecionados)}
                iconeEsquerda={<Icone nome="excluir" className="h-3.5 w-3.5" />}
              >
                Excluir ({numero(quantidade)})
              </Botao>
            )}
            <Botao variante="sutil" tamanho="sm" onClick={limpar}>
              Limpar seleção
            </Botao>
          </div>
        )}
        estados={{
          carregando: documentos.carregando,
          erro: documentos.erro,
          aoTentarNovamente: documentos.atualizar,
          vazioTitulo: pronto ? "Nenhum documento neste recorte" : "Escolha o período para consultar",
          vazioInstrucao: pronto
            ? "Nenhuma nota foi capturada com esta combinação de período, empresa e filtros. Se o período estiver certo, dispare a importação."
            : "A API exige data inicial e final para listar o acervo — é o que impede varrer meses que ninguém pediu.",
          vazioAcao: pronto ? (
            <BotaoLink variante="secundaria" href="/dashboard/importacoes">
              Disparar importação
            </BotaoLink>
          ) : undefined,
          vazioIcone: "documento",
          filtroAtivo,
          aoLimparFiltro: filtroAtivo ? limparFiltros : undefined,
        }}
        ferramentas={
          <p className="nums text-xs text-tinta-suave">
            {total === null
              ? "contando…"
              : `${numero(linhas.length)} de ${numero(total)} ${plural(total, "documento", "documentos")} carregados`}
            {linhas.length < (total ?? 0) ? " · ordenação e seleção valem para as linhas carregadas" : ""}
          </p>
        }
        rodape={
          <Paginacao
            total={total ?? linhas.length}
            exibidos={linhas.length}
            passo={PASSO}
            aoCarregarMais={linhas.length < (total ?? 0) ? carregarMais : undefined}
            carregando={carregandoMais}
            complemento={
              linhas.length > 0 ? (
                <span className="text-xs text-tinta-fraca">
                  Período {rotuloPeriodo(periodo)} · {selecao.size > 0 ? `${numero(selecao.size)} selecionados` : "clique numa linha para ver o documento"}
                </span>
              ) : undefined
            }
          />
        }
      />

      <PainelDocumento
        documentoId={documentoAberto}
        aoFechar={() => definir({ doc: null })}
        aoExcluir={somenteLeitura ? undefined : (detalhe) => setExcluirUm(detalhe)}
        somenteLeitura={somenteLeitura}
      />

      <Modal
        aberto={exportacao !== null}
        aoFechar={() => setExportacao(null)}
        titulo={exportacao === "csv" ? "Exportar relação em CSV" : "Baixar XMLs do filtro"}
        descricao="Confira o tamanho antes: o download roda na API e pode levar minutos em períodos grandes."
        largura="media"
        rodape={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Botao variante="sutil" onClick={() => setExportacao(null)}>
              Cancelar
            </Botao>
            <Botao
              variante="primaria"
              onClick={confirmarExportacao}
              carregando={baixando}
              disabled={carregandoEstimativa || (estimativa?.documentos ?? 0) === 0}
            >
              {exportacao === "csv" ? "Gerar CSV" : "Baixar ZIP"}
            </Botao>
          </div>
        }
      >
        {carregandoEstimativa ? (
          <p className="text-sm text-tinta-suave" aria-busy="true">
            Calculando o que será baixado…
          </p>
        ) : erroExportacao ? (
          <p role="alert" className="text-sm text-erro">
            {erroExportacao}
          </p>
        ) : estimativa ? (
          <div className="space-y-3">
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <Dado destaque rotulo="Documentos" valor={numero(estimativa.documentos)} />
              <Dado destaque rotulo="Empresas" valor={numero(estimativa.empresas)} />
              <Dado destaque rotulo="Tamanho estimado" valor={bytesParaTexto(estimativa.estimado_bytes)} />
              <Dado destaque rotulo="Período" valor={estimativa.periodo || rotuloPeriodo(periodo)} />
            </dl>
            {estimativa.estimado_bytes > estimativa.limite ? (
              <p className="rounded-controle border border-espera/40 bg-espera-tenue px-3 py-2 text-sm leading-6 text-espera">
                O tamanho estimado ({bytesParaTexto(estimativa.estimado_bytes)}) passa do limite de {bytesParaTexto(estimativa.limite)}. Reduza o
                período ou filtre por empresa antes de baixar.
              </p>
            ) : null}
          </div>
        ) : null}
      </Modal>

      <DialogoConfirmacao
        aberto={excluirLote !== null && excluirLote.length > 0}
        aoFechar={() => {
          setExcluirLote(null);
          setErroExclusao(null);
        }}
        aoConfirmar={() => excluir(excluirLote ?? [], "lote")}
        carregando={enviandoExclusao}
        erro={erroExclusao}
        tom="perigo"
        titulo={`Excluir ${numero(excluirLote?.length ?? 0)} ${plural(excluirLote?.length ?? 0, "documento", "documentos")}`}
        consequencia="Os registros saem do banco e os arquivos XML são apagados do disco. Não há como desfazer."
        impacto={
          <span>
            Período {rotuloPeriodo(periodo)}
            {empresa ? ` · empresa ${razaoPorId.get(empresa) ?? numero(empresa)}` : " · todas as empresas do filtro"}
            {tipo ? ` · tipo ${ROTULO_TIPO[tipo as TipoDocumentoFiscal] ?? tipo}` : ""}. Para recuperar, será preciso capturar de novo pela SEFAZ.
          </span>
        }
        exigirTexto="EXCLUIR"
        rotuloConfirmar="Excluir documentos"
      />

      <DialogoConfirmacao
        aberto={excluirUm !== null}
        aoFechar={() => {
          setExcluirUm(null);
          setErroExclusao(null);
        }}
        aoConfirmar={() => excluir(excluirUm ? [excluirUm.id] : [], "unico")}
        carregando={enviandoExclusao}
        erro={erroExclusao}
        tom="perigo"
        titulo="Excluir este documento"
        consequencia={
          excluirUm
            ? `${ROTULO_TIPO[excluirUm.tipo] ?? excluirUm.tipo} ${excluirUm.numero ?? ""} (chave ${chaveEmGrupos(excluirUm.chave_acesso)}) sai do banco e o XML é apagado do disco.`
            : ""
        }
        impacto="Para recuperar, será preciso capturar o documento de novo pela SEFAZ, dentro do período de distribuição."
        rotuloConfirmar="Excluir"
      />
    </div>
  );
}

function compararDocumentos(a: DocumentoFiscal, b: DocumentoFiscal, coluna: string, razaoPorId: Map<number, string>): number {
  switch (coluna) {
    case "emissao":
      return new Date(a.data_emissao).getTime() - new Date(b.data_emissao).getTime();
    case "tipo":
      return a.tipo.localeCompare(b.tipo);
    case "numero":
      return Number(a.numero ?? 0) - Number(b.numero ?? 0);
    case "parte": {
      const nomeA = (a.direcao === "tomada" ? a.emitente_nome : a.destinatario_nome) ?? "";
      const nomeB = (b.direcao === "tomada" ? b.emitente_nome : b.destinatario_nome) ?? "";
      return nomeA.localeCompare(nomeB, "pt-BR");
    }
    case "empresa":
      return (razaoPorId.get(a.empresa_id) ?? "").localeCompare(razaoPorId.get(b.empresa_id) ?? "", "pt-BR");
    case "valor":
      return a.valor_total - b.valor_total;
    case "status":
      return a.status.localeCompare(b.status);
    default:
      return 0;
  }
}

/** Marca a linha cancelada sem tirar contraste: fundo levemente quente, valor riscado, selo avisando. */
function classeDaLinhaDocumento(documento: DocumentoFiscal): string | undefined {
  return documento.status === "cancelada" ? "bg-erro-tenue/40" : undefined;
}
