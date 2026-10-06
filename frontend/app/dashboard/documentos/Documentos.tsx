"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, type FiltrosDocumentos } from "@/lib/api";
import { ROTULO_ACAO_LOTE } from "@/lib/acoes-documento";
import { bytesParaTexto, chaveEmGrupos, dataCurta, formatarCnpjCpf, mesAno, numero, plural } from "@/lib/format";
import { estadoDoDocumento } from "@/lib/estados";
import { mensagemDoErro } from "@/lib/erros";
import { MOTIVO_SOMENTE_LEITURA } from "@/lib/papel";
import { intervaloDoMes, mesDoIntervalo, paraFiltro, periodoValido, rotuloPeriodo, sufixoArquivo, type Periodo } from "@/lib/periodo";
import { hrefComEstado } from "@/lib/urlEstadoLink";
import { useBuscaUrl } from "@/lib/useBuscaUrl";
import { usePreferencia } from "@/lib/usePreferencia";
import { usePeriodoUrl } from "@/lib/usePeriodoUrl";
import { useRecurso } from "@/lib/useRecurso";
import { useUrlEstado } from "@/lib/urlEstado";
import { useSinalizarAtualizacao } from "@/components/shell/BarraAtualizacao";
import { useSessao } from "@/components/shell/ProvedorSessao";
import { PainelDocumento } from "@/components/fiscal/PainelDocumento";
import { SeletorCompetencia } from "@/components/fiscal/SeletorCompetencia";
import { SeletorPeriodo } from "@/components/fiscal/SeletorPeriodo";
import { ModalImportarXmls } from "@/app/dashboard/importacoes/ImportarXmls";
import { Botao, BotaoLink } from "@/components/ui/Botao";
import { CabecalhoPagina, Cartao } from "@/components/ui/Cartao";
import { Busca, Caixa, Entrada, Selecao } from "@/components/ui/Campo";
import { Combobox, type OpcaoCombobox } from "@/components/ui/Combobox";
import { Dado } from "@/components/ui/Dado";
import { DialogoConfirmacao } from "@/components/ui/DialogoConfirmacao";
import { Etiqueta } from "@/components/ui/Etiqueta";
import { Cnpj, ValorMoeda } from "@/components/ui/Formatadores";
import { GradeKpis, type KpiProps } from "@/components/ui/Kpi";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";
import { MenuSuspenso } from "@/components/ui/MenuSuspenso";
import { Modal } from "@/components/ui/Modal";
import { Paginacao } from "@/components/ui/Paginacao";
import { Popover, PopoverCabecalho } from "@/components/ui/Popover";
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
  const { definir, ler, lerNumero, parametros } = useUrlEstado();
  const { periodo, pronto } = usePeriodoUrl();
  const busca = useBuscaUrl();
  const { somenteLeitura } = useSessao();
  const { avisar } = useToast();
  const [mostrarIntervaloPersonalizado, setMostrarIntervaloPersonalizado] = useState(false);

  const tipo = ler("tipo");
  const direcao = ler("direcao");
  const status = ler("status");
  const leiaute = ler("leiaute");
  const valorMin = ler("valor_min");
  const valorMax = ler("valor_max");
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
  // Opt-in explícito: por padrão o pacote leva só XML de nota. Quem precisa do
  // resumo marca a caixa e recebe esses arquivos numa pasta à parte — nunca
  // misturados, porque o importador contábil lê a pasta da empresa e reclama.
  const [incluirIncompletos, setIncluirIncompletos] = useState(false);

  const [importacaoXmlAberta, setImportacaoXmlAberta] = useState(false);
  const [colunasAbertas, setColunasAbertas] = useState(false);
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
    if (valorMin !== "" && Number.isFinite(Number(valorMin))) base.valor_min = valorMin;
    if (valorMax !== "" && Number.isFinite(Number(valorMax))) base.valor_max = valorMax;
    if (empresa) base.empresa_id = empresa;
    if (busca.valor.trim()) base.busca = busca.valor.trim();
    return base;
  }, [busca.valor, direcao, empresa, leiaute, periodo, status, tipo, valorMax, valorMin]);

  const chaveFiltros = useMemo(() => JSON.stringify(filtros), [filtros]);

  const documentos = useRecurso(() => api.listarDocumentos({ ...filtros, limit: PASSO, offset: 0 }), [chaveFiltros], { automatico: pronto });
  const resumo = useRecurso(() => api.resumoDocumentos(filtros), [chaveFiltros], { automatico: pronto });
  const empresas = useRecurso(() => api.listarEmpresas(), []);
  const opcoesEmpresa = useMemo<OpcaoCombobox[]>(
    () => [
      { valor: "", rotulo: "Todas as empresas" },
      ...(empresas.dados ?? []).map((item) => ({
        valor: String(item.id),
        rotulo: item.razao_social,
        descricao: `${formatarCnpjCpf(item.cnpj_cpf)} · ${item.uf}`,
        termosBusca: item.cnpj_cpf,
      })),
    ],
    [empresas.dados]
  );
  const empresaSelecionada = (empresas.dados ?? []).find((item) => item.id === empresa) ?? null;
  const escopoEmpresa = empresaSelecionada?.razao_social ?? "Todas as empresas";
  const mesDoPeriodo = mesDoIntervalo(periodo);
  const intervaloPersonalizado = mostrarIntervaloPersonalizado || (pronto && !mesDoPeriodo);
  const mesSelecionado = mesDoPeriodo || periodo.inicio.slice(0, 7);

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
  const filtroAtivo = Boolean(tipo || direcao || status || leiaute || valorMin || valorMax || empresa || busca.valor.trim());
  // Empresa fica visível na barra da tabela; o contador aqui representa apenas o popover.
  const quantidadeFiltros = [tipo, direcao, status, leiaute, valorMin, valorMax].filter(Boolean).length;

  function hrefDoAcervo(mudancas: Record<string, string | null> = {}, remover: string[] = []) {
    const temPeriodo = periodoValido(periodo);
    return hrefComEstado(
      "/dashboard/documentos",
      parametros.toString(),
      {
        data_inicio: temPeriodo ? periodo.inicio : null,
        data_fim: temPeriodo ? periodo.fim : null,
        mes: null,
        competencia: null,
        busca: busca.valor.trim() || null,
        ...mudancas,
      },
      remover
    );
  }

  function mudarPeriodo(proximo: Periodo) {
    definir({
      data_inicio: proximo.inicio,
      data_fim: proximo.fim,
      mes: null,
      competencia: null,
      pagina: null,
      doc: null,
    });
  }

  function limparFiltros() {
    definir({ tipo: null, direcao: null, status: null, leiaute: null, valor_min: null, valor_max: null, empresa: null, busca: null, ordem: null, sentido: null });
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
        await api.baixarZip(
          { ...filtros, incluir_incompletos: incluirIncompletos },
          `Fluxa_xmls_${sufixoArquivo(periodo)}.zip`
        );
        // A confirmação diz o que de fato entrou no pacote: sem isso o operador
        // só descobre as pendências abrindo o ZIP.
        const pendentes = estimativa?.sem_xml_completo ?? 0;
        avisar({
          tom: "ok",
          titulo: "ZIP gerado",
          descricao:
            `${escopoEmpresa} · ${rotuloPeriodo(periodo)} · ${estimativa ? numero(estimativa.documentos) : ""} documentos` +
            (pendentes > 0 ? ` · ${numero(pendentes)} listados em pendencias.csv` : ""),
        });
      } else {
        await api.baixarCsvDocumentos(filtros, `Fluxa_relacao_${sufixoArquivo(periodo)}.csv`);
        avisar({
          tom: "ok",
          titulo: "Relação em CSV gerada",
          descricao: `${escopoEmpresa} · ${rotuloPeriodo(periodo)}`,
        });
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
        await api.baixarZip(filtroSelecao, `Fluxa_selecao_${sufixoArquivo(periodo)}.zip`);
        avisar({
          tom: "ok",
          titulo: "XMLs da seleção baixados",
          descricao: `${escopoEmpresa} · ${numero(idsSelecionados.length)} ${plural(idsSelecionados.length, "documento", "documentos")}`,
        });
      } else {
        await api.baixarCsvDocumentos(filtroSelecao, `Fluxa_selecao_${sufixoArquivo(periodo)}.csv`);
        avisar({
          tom: "ok",
          titulo: "CSV da seleção gerado",
          descricao: `${escopoEmpresa} · ${numero(idsSelecionados.length)} ${plural(idsSelecionados.length, "documento", "documentos")}`,
        });
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

  const baixarDocumento = useCallback(async (documento: DocumentoFiscal) => {
    try {
      await api.baixarXmlDocumento(documento.id, `${documento.chave_acesso || `documento-${documento.id}`}.xml`);
      avisar({ tom: "ok", titulo: "XML baixado", descricao: documento.numero ? `Documento ${documento.numero}` : undefined });
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível baixar o XML", descricao: mensagemDoErro(falha, "baixar o XML") });
    }
  }, [avisar]);

  const copiarChave = useCallback(async (documento: DocumentoFiscal) => {
    try {
      await navigator.clipboard.writeText(documento.chave_acesso);
      avisar({ tom: "ok", titulo: "Chave copiada" });
    } catch {
      avisar({ tom: "erro", titulo: "A chave não foi copiada", descricao: "O navegador bloqueou a área de transferência. Abra o detalhe e copie a chave manualmente." });
    }
  }, [avisar]);

  async function completarXmls() {
    setCompletandoXml(true);
    try {
      const resultado = await api.completarXmls(empresa, 20);
      avisar({
        tom: resultado.disparado ? "ok" : "espera",
        titulo: resultado.disparado ? "Busca de XMLs completos disparada" : "Nada a buscar agora",
        descricao: resultado.aviso,
      });
      documentos.atualizar();
      resumo.atualizar();
    } catch (falha) {
      avisar({ tom: "erro", titulo: "Não foi possível buscar os XMLs", descricao: mensagemDoErro(falha, "buscar os XMLs") });
    } finally {
      setCompletandoXml(false);
    }
  }

  const colunas = useMemo<Array<ColunaTabela<DocumentoFiscal>>>(
    () => [
      {
        id: "emissao",
        cabecalho: "Emissão",
        largura: "min-w-28",
        ordenavel: true,
        celula: (documento) => <span className="nums whitespace-nowrap text-tinta">{dataCurta(documento.data_emissao)}</span>,
      },
      {
        id: "competencia",
        cabecalho: "Competência",
        largura: "min-w-28",
        ordenavel: true,
        celula: (documento) => (
          <span className="nums whitespace-nowrap text-tinta">
            {documento.competencia ? mesAno(documento.competencia) : "—"}
          </span>
        ),
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
        largura: "min-w-36",
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
        largura: "min-w-36",
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
        ocultaPorPadrao: true,
        largura: "min-w-52",
        celula: (documento) => (
          <span className="block max-w-56 truncate font-mono text-xs text-tinta-suave" title={chaveEmGrupos(documento.chave_acesso)}>
            {chaveEmGrupos(documento.chave_acesso)}
          </span>
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
      {
        id: "acoes",
        fixar: "direita",
        cabecalho: "Ações",
        largura: "w-16 min-w-16",
        alinhamento: "direita",
        fixa: true,
        celula: (documento) => (
          <MenuSuspenso
            rotulo={`Ações do documento ${documento.numero ?? documento.id}`}
            icone="mais"
            dica="Ações do documento"
            tamanho="sm"
            itens={[
              { id: "detalhe", rotulo: "Abrir detalhe", icone: "ver", aoClicar: () => definir({ doc: documento.id }) },
              { id: "copiar", rotulo: "Copiar chave", icone: "copiar", aoClicar: () => copiarChave(documento) },
              { id: "baixar", rotulo: "Baixar XML", icone: "baixar", aoClicar: () => baixarDocumento(documento) },
              { id: "recibo", rotulo: "Ver recibo de captura", icone: "auditoria", aoClicar: () => definir({ doc: documento.id }) },
            ]}
          />
        ),
      },
    ],
    [baixarDocumento, copiarChave, definir, razaoPorId]
  );

  const indicadores: KpiProps[] = resumo.dados
    ? [
        { rotulo: "Documentos no recorte", valor: numero(resumo.dados.total), contexto: rotuloPeriodo(periodo), carregando: resumo.atualizando },
        { rotulo: "Normais", valor: numero(resumo.dados.normais), tom: "ok" },
        {
          rotulo: "Canceladas",
          valor: numero(resumo.dados.canceladas),
          tom: resumo.dados.canceladas > 0 ? "espera" : "neutro",
          href: hrefDoAcervo({ status: "cancelada" }, ["doc", "pagina"]),
        },
        ...TIPOS.filter((tipoItem) => (resumo.dados?.por_tipo[tipoItem] ?? 0) > 0).map((tipoItem) => ({
          rotulo: ROTULO_TIPO[tipoItem],
          valor: numero(resumo.dados?.por_tipo[tipoItem] ?? 0),
          contexto: "no recorte",
          href: hrefDoAcervo({ tipo: tipoItem }, ["doc", "pagina"]),
        })),
      ]
    : [];

  return (
    <div className="space-y-5">
      <CabecalhoPagina
        kicker="Fiscal · Acervo"
        titulo="Documentos"
        descricao="Localize a nota, confira a chave e entregue XMLs ou a relação da competência escolhida."
      />

      <Cartao densidade="compacta" className="nao-imprimir">
        {!pronto ? (
          <SeletorPeriodo periodo={periodo} aoMudar={mudarPeriodo} obrigatorio />
        ) : intervaloPersonalizado ? (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <SeletorPeriodo periodo={periodo} aoMudar={mudarPeriodo} obrigatorio className="min-w-0 flex-1" />
            <Botao
              tamanho="sm"
              variante="sutil"
              className="mb-1 w-full sm:w-auto"
              onClick={() => {
                setMostrarIntervaloPersonalizado(false);
                mudarPeriodo(intervaloDoMes(mesSelecionado));
              }}
            >
              Voltar à competência mensal
            </Botao>
          </div>
        ) : (
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
            <SeletorCompetencia
              className="min-w-0 flex-1"
              mes={mesSelecionado}
              aoMudar={(mes) => {
                setMostrarIntervaloPersonalizado(false);
                mudarPeriodo(intervaloDoMes(mes));
              }}
              descricao="O mês escolhido vale para a lista, a seleção e os downloads."
            />
            <Botao
              tamanho="sm"
              variante="sutil"
              className="mb-1 w-full sm:w-auto"
              onClick={() => setMostrarIntervaloPersonalizado(true)}
            >
              Período personalizado
            </Botao>
          </div>
        )}
        {leiaute === "metadados" ? (
          <p className="mt-3 rounded-controle border border-espera/40 bg-espera-tenue px-3 py-2 text-sm text-espera">
            Estas NFS-e foram registradas sem XML original. A exportação inclui um JSON normalizado e a relação CSV.
          </p>
        ) : null}
        {leiaute === "resumo" ? (
          <p className="mt-3 rounded-controle border border-espera/40 bg-espera-tenue px-3 py-2 text-sm text-espera">
            Estes documentos chegaram em resumo (resNFe). O XML completo é buscado pela chave, na fila da SEFAZ.
          </p>
        ) : null}
      </Cartao>
      {resumo.dados ? <GradeKpis itens={indicadores} colunas={indicadores.length <= 3 ? 3 : indicadores.length <= 4 ? 4 : indicadores.length <= 5 ? 5 : 6} rotulo="Resumo do recorte" /> : null}

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
        colunasVisiveis={colunasVisiveis ?? undefined}
        altura="h-[max(320px,calc(100dvh-28rem))]"
        selecao={{
          chaves: selecao,
          aoMudar: setSelecao,
          totalNoFiltro: total ?? undefined,
        }}
        barraDeSelecao={({ quantidade }) => (
          // Com seleção ativa, a ação principal da tela passa a ser o lote:
          // uma primária só. A exclusão sai do lado do botão principal e vai
          // para o "⋯" — destrutiva, rara, e hoje vizinha de clique por engano.
          <div className="flex flex-wrap items-center gap-2">
            <div data-acao="primaria">
              <Botao
                variante="primaria"
                tamanho="sm"
                onClick={() => baixarSelecao("xml")}
                carregando={baixando}
                iconeEsquerda={<Icone nome="baixar" className="h-3.5 w-3.5" />}
              >
                Baixar {numero(quantidade)} XMLs
              </Botao>
            </div>
            <MenuSuspenso
              rotulo="Mais ações da seleção"
              icone="mais"
              tamanho="sm"
              dica="Mais ações da seleção"
              itens={[
                {
                  id: "csv",
                  rotulo: `Relação (CSV) das ${numero(quantidade)}`,
                  icone: "baixar",
                  aoClicar: () => baixarSelecao("csv"),
                },
                {
                  id: "excluir",
                  rotulo: `Excluir ${numero(quantidade)} documentos…`,
                  icone: "excluir",
                  tom: "perigo" as const,
                  separarAcima: true,
                  desabilitado: somenteLeitura,
                  motivo: somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined,
                  aoClicar: () => setExcluirLote(idsSelecionados),
                },
              ]}
            />
          </div>
        )}
        estados={{
          carregando: documentos.carregando,
          erro: documentos.erro,
          aoTentarNovamente: documentos.atualizar,
          vazioTitulo: pronto ? "Nenhum documento neste recorte" : "Escolha a competência para consultar",
          vazioInstrucao: pronto
            ? "Nenhuma nota foi capturada com esta combinação de competência, empresa e filtros. Se o recorte estiver certo, dispare a importação."
            : "A consulta precisa de uma competência mensal ou de um intervalo com início e fim.",
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
          <div className="flex min-w-0 flex-wrap items-end gap-2">
            <Busca
              rotulo="Buscar documento"
              rotuloVisivel
              placeholder="Chave, número, NSU ou parte"
              valor={busca.valor}
              aoMudar={busca.aoMudar}
              className="w-full sm:min-w-64 sm:flex-1"
            />
            <Combobox
              rotulo="Empresa"
              descricao="Digite o nome ou CNPJ. Lista e downloads ficam limitados à empresa escolhida."
              placeholder="Todas as empresas"
              valor={empresa ? String(empresa) : ""}
              aoMudar={(valor) => definir({ empresa: valor || null, doc: null, pagina: null })}
              opcoes={opcoesEmpresa}
              carregando={empresas.carregando}
              vazio="Nenhuma empresa encontrada pelo nome ou CNPJ."
              className="w-full sm:w-64 sm:flex-none"
            />
            <Popover
              rotulo="Filtros"
              icone="filtrar"
              contador={quantidadeFiltros}
              alinhamento="direita"
              largura="w-[min(92vw,42rem)]"
              dica="Filtrar documentos"
            >
              {(fechar) => (
                <div>
                  <PopoverCabecalho
                    titulo="Filtros"
                    acao={
                      filtroAtivo ? (
                        <button type="button" onClick={limparFiltros} className="text-xs font-medium text-acento underline-offset-4 hover:underline">
                          Limpar
                        </button>
                      ) : undefined
                    }
                  />
                  <div className="grid gap-3 p-3 sm:grid-cols-2">
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
                        { valor: "completo", rotulo: "XML completo" },
                        { valor: "resumo", rotulo: "Resumo pendente" },
                        { valor: "metadados", rotulo: "Metadados sem XML" },
                      ]}
                    />
                    <Entrada
                      rotulo="Valor mínimo"
                      type="number"
                      min={0}
                      numerico
                      value={valorMin}
                      onChange={(evento) => definir({ valor_min: evento.target.value || null })}
                    />
                    <Entrada
                      rotulo="Valor máximo"
                      type="number"
                      min={0}
                      numerico
                      value={valorMax}
                      onChange={(evento) => definir({ valor_max: evento.target.value || null })}
                    />
                  </div>
                  <div className="flex justify-end border-t border-traco px-3 py-2">
                    <Botao tamanho="sm" variante="secundaria" onClick={fechar}>Ver documentos</Botao>
                  </div>
                </div>
              )}
            </Popover>
            <MenuSuspenso
              rotulo="Exportar"
              variante="secundaria"
              itens={[
                { id: "xml", rotulo: "XMLs (ZIP)", icone: "documento", desabilitado: !pronto, motivo: !pronto ? "Informe o período" : undefined, aoClicar: () => estimarExportacao("xml") },
                { id: "csv", rotulo: "Relação (CSV)", icone: "baixar", desabilitado: !pronto, motivo: !pronto ? "Informe o período" : undefined, aoClicar: () => estimarExportacao("csv") },
              ]}
            />
            <MenuSuspenso
              rotulo="Mais ações da tabela"
              icone="mais"
              dica="Mais ações da tabela"
              itens={[
                {
                  id: "importar",
                  rotulo: "Importar XMLs de outro sistema…",
                  icone: "importacao",
                  desabilitado: somenteLeitura,
                  motivo: somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined,
                  aoClicar: () => setImportacaoXmlAberta(true),
                },
                {
                  id: "completar",
                  // Mesmo verbo da ficha: no singular é a ação do documento, no
                  // lote é esta. Ter um terceiro verbo aqui para a mesma ação
                  // era metade do problema de hierarquia que o dono reclamou.
                  rotulo: completandoXml ? "Buscando XMLs…" : ROTULO_ACAO_LOTE.buscarXml,
                  icone: "sincronizar",
                  desabilitado: somenteLeitura || completandoXml,
                  motivo: somenteLeitura ? MOTIVO_SOMENTE_LEITURA : undefined,
                  aoClicar: completarXmls,
                },
                { id: "colunas", rotulo: "Escolher colunas…", icone: "colunas", aoClicar: () => setColunasAbertas(true), separarAcima: true },
                {
                  id: "densidade",
                  rotulo: densidade === "compacta" ? "Usar linhas confortáveis" : "Usar linhas compactas",
                  icone: "menu",
                  aoClicar: () => setDensidade(densidade === "compacta" ? "confortavel" : "compacta"),
                },
              ]}
            />
          </div>
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
        hrefAcervo={hrefDoAcervo({}, ["doc"])}
        aoFechar={() => definir({ doc: null })}
        aoExcluir={somenteLeitura ? undefined : (detalhe) => setExcluirUm(detalhe)}
        somenteLeitura={somenteLeitura}
      />

      <ModalImportarXmls
        aberto={importacaoXmlAberta}
        aoFechar={() => setImportacaoXmlAberta(false)}
        aoConcluir={() => {
          documentos.atualizar();
          resumo.atualizar();
        }}
      />

      <Modal
        aberto={colunasAbertas}
        aoFechar={() => setColunasAbertas(false)}
        titulo="Escolher colunas"
        descricao="A preferência fica salva neste navegador."
        largura="media"
        rodape={
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Botao variante="sutil" onClick={() => setColunasVisiveis(colunas.map((coluna) => coluna.id))}>Mostrar todas</Botao>
            <Botao variante="secundaria" onClick={() => setColunasAbertas(false)}>Concluir</Botao>
          </div>
        }
      >
        <div className="grid gap-1 sm:grid-cols-2">
          {colunas.filter((coluna) => coluna.cabecalho).map((coluna) => (
            <Caixa
              key={coluna.id}
              compacta
              rotulo={coluna.cabecalho}
              checked={coluna.fixa || (colunasVisiveis ? colunasVisiveis.includes(coluna.id) : !coluna.ocultaPorPadrao)}
              disabled={coluna.fixa}
              onChange={(evento) => {
                if (coluna.fixa) return;
                const atuais = colunasVisiveis ?? colunas.filter((item) => item.fixa || !item.ocultaPorPadrao).map((item) => item.id);
                setColunasVisiveis(
                  evento.target.checked
                    ? colunas.map((item) => item.id).filter((id) => id === coluna.id || atuais.includes(id))
                    : atuais.filter((id) => id !== coluna.id)
                );
              }}
            />
          ))}
        </div>
      </Modal>

      <Modal
        aberto={exportacao !== null}
        aoFechar={() => setExportacao(null)}
        titulo={exportacao === "csv" ? "Exportar relação em CSV" : "Baixar XMLs do filtro"}
        descricao={
          empresaSelecionada
            ? `O download ficará restrito a ${empresaSelecionada.razao_social}. Confira o tamanho: períodos grandes podem levar alguns minutos.`
            : "Sem empresa escolhida, o download inclui todas as empresas do escritório que atendem aos filtros. Selecione uma empresa para limitar."
        }
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
            {exportacao === "xml" && estimativa.sem_xml_completo > 0 ? (
              // O aviso vem ANTES do clique: baixar 900 arquivos e só então
              // descobrir, abrindo o ZIP, que 140 eram resumo é o susto que
              // levou o contador a desconfiar do pacote inteiro.
              <div className="space-y-2 rounded-controle border border-espera/40 bg-espera-tenue px-3 py-2 text-sm leading-6 text-espera">
                <p>
                  {numero(estimativa.sem_xml_completo)}{" "}
                  {plural(estimativa.sem_xml_completo, "documento está", "documentos estão")} sem XML
                  completo (resumo, protocolo ou evento). O pacote leva{" "}
                  <strong>só XML de nota</strong>; o que ficou de fora vai para{" "}
                  <code>pendencias.csv</code> com o motivo e o que fazer.
                </p>
                <Caixa
                  compacta
                  rotulo="Incluir os incompletos numa pasta à parte (Fluxa/_sem-xml-completo/)"
                  checked={incluirIncompletos}
                  onChange={(evento) => setIncluirIncompletos(evento.target.checked)}
                />
              </div>
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
    case "competencia": {
      const dataA = a.competencia || a.data_emissao;
      const dataB = b.competencia || b.data_emissao;
      return new Date(dataA).getTime() - new Date(dataB).getTime();
    }
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
