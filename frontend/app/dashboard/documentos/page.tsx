"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError, type FiltrosExportacao, type FiltrosDocumentos } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import { PeriodoPicker } from "@/components/PeriodoPicker";
import { DocumentoDrawer } from "@/components/DocumentoDrawer";
import { BuscaInput } from "@/components/Busca";
import { Icone } from "@/components/icons";
import { bytesParaTexto } from "@/lib/competencia";
import {
  erroDoPeriodo,
  paraFiltro,
  periodoDaURL,
  periodoValido,
  rotuloPeriodo,
  sufixoArquivo,
  type Periodo,
} from "@/lib/periodo";
import {
  ROTULO_TIPO,
  type DirecaoDocumento,
  type DocumentoFiscal,
  type Empresa,
  type EstimativaExportacao,
  type ResumoDocumentos,
  type StatusDocumentoFiscal,
  type TipoDocumentoFiscal,
} from "@/lib/types";

const PAGINA = 500;

function formatarData(valor: string | null | undefined): string {
  if (!valor) return "—";
  const data = new Date(valor);
  return Number.isNaN(data.getTime()) ? "—" : data.toLocaleDateString("pt-BR");
}

function truncarChave(chave: string): string {
  return `${chave.slice(0, 8)}…${chave.slice(-6)}`;
}

/**
 * Documentos — lista, filtra, exclui e baixa os XMLs importados.
 *
 * O `Suspense` é exigência do Next para páginas que leem parâmetros da URL em
 * renderização do cliente: o casco da página é pré-renderizado e só a
 * parte que depende da URL entra no cliente.
 */
export default function DocumentosPage() {
  return (
    <Suspense fallback={<p className="text-sm text-ink-muted">Carregando…</p>}>
      <ConteudoDocumentos />
    </Suspense>
  );
}

function ConteudoDocumentos() {
  const searchParams = useSearchParams();

  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [empresaId, setEmpresaId] = useState<number | "todas">("todas");
  const [tipo, setTipo] = useState<TipoDocumentoFiscal | "">("");
  const [direcao, setDirecao] = useState<DirecaoDocumento | "">("");
  const [statusDoc, setStatusDoc] = useState<StatusDocumentoFiscal | "">("");
  const [leiaute, setLeiaute] = useState<"" | "completo" | "resumo">("");
  // Período obrigatório. A tela abre no mês corrente (ou no que a URL pedir),
  // nunca em "todos os períodos" — abrir sem recorte era o que despejava o
  // acervo inteiro e fazia o filtro parecer quebrado.
  const [periodo, setPeriodo] = useState<Periodo>(() => periodoDaURL(searchParams));
  const [valorMin, setValorMin] = useState("");
  const [valorMax, setValorMax] = useState("");
  // A busca global da barra superior chega por `?busca=`.
  const [busca, setBusca] = useState(searchParams.get("busca") || "");
  const [termoBusca, setTermoBusca] = useState(searchParams.get("busca") || "");
  const [filtrosAvancados, setFiltrosAvancados] = useState(false);
  const [docAberto, setDocAberto] = useState<number | null>(null);
  const { somenteLeitura } = usePapel();

  const [documentos, setDocumentos] = useState<DocumentoFiscal[]>([]);
  const [resumo, setResumo] = useState<ResumoDocumentos | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selecionados, setSelecionados] = useState<Set<number>>(new Set());
  const [estimativa, setEstimativa] = useState<EstimativaExportacao | null>(null);
  const [baixando, setBaixando] = useState(false);
  const [excluindo, setExcluindo] = useState(false);
  const [mensagem, setMensagem] = useState<string | null>(null);

  useEffect(() => {
    api.listarEmpresas().then(setEmpresas).catch(() => {});
  }, []);

  const resetarLista = useCallback(() => {
    setOffset(0);
    setDocumentos([]);
    setSelecionados(new Set());
  }, []);

  const periodoOk = periodoValido(periodo);
  const avisoPeriodo = erroDoPeriodo(periodo);

  // Uma única definição de filtro para a tela, para o contador, para CSV e para
  // o ZIP — é o que faz "12 documentos na tela" virar "12 arquivos no ZIP".
  // O período entra sempre como intervalo de datas: uma forma só, igual à que
  // a API aplica sobre a data de emissão.
  const filtros = useMemo<FiltrosDocumentos>(
    () => ({
      ...(empresaId === "todas" ? {} : { empresa_id: empresaId }),
      ...(tipo ? { tipo } : {}),
      ...(direcao ? { direcao } : {}),
      ...(statusDoc ? { status: statusDoc } : {}),
      ...(leiaute ? { leiaute } : {}),
      ...paraFiltro(periodo),
      ...(termoBusca ? { busca: termoBusca } : {}),
      ...(valorMin ? { valor_min: valorMin } : {}),
      ...(valorMax ? { valor_max: valorMax } : {}),
    }),
    [empresaId, tipo, direcao, statusDoc, leiaute, periodo, termoBusca, valorMin, valorMax]
  );

  const carregar = useCallback(async (paginaOffset = offset) => {
    // Sem período completo não se consulta: a API recusaria, e pedir para nada
    // só encheria a tela de erro enquanto a pessoa ainda está digitando a data.
    if (!periodoValido(periodo)) {
      setDocumentos([]);
      setResumo(null);
      setEstimativa(null);
      return;
    }
    setCarregando(true);
    try {
      const [lista, agregado, estimado] = await Promise.all([
        api.listarDocumentos({ ...filtros, limit: PAGINA, offset: paginaOffset }),
        api.resumoDocumentos(filtros),
        api.estimarExportacao(filtros),
      ]);
      setDocumentos((atual) => (paginaOffset === 0 ? lista : [...atual, ...lista]));
      setResumo(agregado);
      setEstimativa(estimado);
    } catch (e) {
      setMensagem(e instanceof ApiError ? e.message : "Não foi possível listar os documentos.");
    } finally {
      setCarregando(false);
    }
  }, [filtros, offset, periodo]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  async function recarregarPrimeiraPagina() {
    setOffset(0);
    await carregar(0);
  }

  async function baixarTudo() {
    setBaixando(true);
    setMensagem(null);
    try {
      await api.baixarZip(
        filtros as FiltrosExportacao,
        `NotasFlow_${sufixoArquivo(periodo)}.zip`
      );
      setMensagem("Download iniciado — o ZIP traz os XMLs disponíveis, a relação em CSV e um LEIA-ME.");
    } catch (e) {
      setMensagem(e instanceof ApiError ? e.message : "O download não começou.");
    } finally {
      setBaixando(false);
    }
  }

  async function baixarCsv() {
    setBaixando(true);
    setMensagem(null);
    try {
      await api.baixarCsvDocumentos(
        filtros as FiltrosExportacao,
        `NotasFlow_relacao_${sufixoArquivo(periodo)}.csv`
      );
      setMensagem("CSV iniciado — a relação usa os mesmos filtros da tela.");
    } catch (e) {
      setMensagem(e instanceof ApiError ? e.message : "O CSV não começou.");
    } finally {
      setBaixando(false);
    }
  }

  async function baixarSelecionados() {
    if (selecionados.size === 0) return;
    setBaixando(true);
    setMensagem(null);
    try {
      await api.baixarZip(
        { documento_ids: [...selecionados].join(",") },
        `NotasFlow_selecao_${selecionados.size}.zip`
      );
    } catch (e) {
      setMensagem(e instanceof ApiError ? e.message : "O download não começou.");
    } finally {
      setBaixando(false);
    }
  }

  async function excluirDocumento(id: number) {
    if (somenteLeitura) return;
    const doc = documentos.find((item) => item.id === id);
    if (!window.confirm(`Excluir definitivamente o documento ${doc?.numero ?? doc?.chave_acesso ?? id}?`)) return;
    setExcluindo(true);
    setMensagem(null);
    try {
      const resposta = await api.excluirDocumento(id);
      setMensagem(`${resposta.excluidos} documento excluído. ${resposta.arquivos_removidos} arquivo(s) removido(s) do disco.`);
      setDocAberto(null);
      await recarregarPrimeiraPagina();
    } catch (e) {
      setMensagem(e instanceof ApiError ? e.message : "Não foi possível excluir o documento.");
    } finally {
      setExcluindo(false);
    }
  }

  async function excluirSelecionados() {
    if (somenteLeitura || selecionados.size === 0) return;
    const ids = [...selecionados];
    if (!window.confirm(`Excluir definitivamente ${ids.length} documento(s) selecionado(s)?`)) return;
    setExcluindo(true);
    setMensagem(null);
    try {
      const resposta = await api.excluirDocumentos(ids);
      setMensagem(`${resposta.excluidos} documento(s) excluído(s). ${resposta.arquivos_removidos} arquivo(s) removido(s) do disco.`);
      setSelecionados(new Set());
      await recarregarPrimeiraPagina();
    } catch (e) {
      setMensagem(e instanceof ApiError ? e.message : "Não foi possível excluir a seleção.");
    } finally {
      setExcluindo(false);
    }
  }

  async function completarResumos() {
    setMensagem(null);
    try {
      const resposta = await api.completarXmls(empresaId === "todas" ? undefined : empresaId);
      setMensagem(resposta.aviso);
    } catch (e) {
      setMensagem(e instanceof ApiError ? e.message : "Não foi possível agendar a complementação.");
    }
  }

  function alternar(id: number) {
    setSelecionados((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(id)) proximo.delete(id);
      else proximo.add(id);
      return proximo;
    });
  }

  function alternarTodos() {
    setSelecionados((atual) =>
      atual.size === documentos.length ? new Set() : new Set(documentos.map((d) => d.id))
    );
  }

  function limparFiltros() {
    resetarLista();
    setEmpresaId("todas");
    setTipo("");
    setDirecao("");
    setStatusDoc("");
    setLeiaute("");
    // O período NÃO é limpo: ele é obrigatório, e zerá-lo deixaria a tela sem
    // poder consultar nada. "Limpar" tira os filtros opcionais e mantém o mês.
    setValorMin("");
    setValorMax("");
    setBusca("");
    setTermoBusca("");
  }

  // A busca da tela aplica sozinha após uma pausa na digitação — ninguém
  // precisa apertar "Buscar" — e Enter continua aplicando na hora.
  const aplicarBusca = useCallback((termo: string) => {
    resetarLista();
    setTermoBusca(termo);
  }, [resetarLista]);

  const filtrosAtivos =
    (empresaId !== "todas" ? 1 : 0) +
    (tipo ? 1 : 0) +
    (direcao ? 1 : 0) +
    (statusDoc ? 1 : 0) +
    (leiaute ? 1 : 0) +
    (termoBusca ? 1 : 0) +
    (valorMin ? 1 : 0) +
    (valorMax ? 1 : 0);

  const semXmlCompleto = resumo?.por_tipo ? documentos.filter((d) => d.leiaute === "resumo").length : 0;
  const periodoRotulo = rotuloPeriodo(periodo);

  return (
    <div className="animate-fade-up">
      <div className="page-header">
        <div>
          <p className="page-kicker">Acervo fiscal</p>
          <h1 className="page-title">Documentos</h1>
          <p className="page-description">
            {periodoRotulo} · {resumo ? `${resumo.total} documento(s), ${resumo.canceladas} cancelada(s)` : "Lendo o acervo…"}
          </p>
        </div>
        <Link
          href={`/dashboard/importacoes?data_inicio=${periodo.inicio}&data_fim=${periodo.fim}`}
          className="btn-primary btn-sm"
        >
          <Icone nome="importacao" className="h-3.5 w-3.5" /> Importar notas
        </Link>
      </div>

      <div className="filter-bar">
        <div className="w-full sm:w-auto sm:min-w-80 sm:flex-1">
          <p className="label">Busca</p>
          <BuscaInput
            valor={busca}
            aoMudar={setBusca}
            aoBuscar={aplicarBusca}
            atraso={500}
            placeholder="chave, número, NSU, emitente ou destinatário"
            ariaLabel="Buscar documentos"
          />
        </div>

        <div>
          <p className="label">Empresa</p>
          <select
            value={empresaId === "todas" ? "todas" : String(empresaId)}
            onChange={(e) => {
              resetarLista();
              setEmpresaId(e.target.value === "todas" ? "todas" : Number(e.target.value));
            }}
            className="input"
          >
            <option value="todas">Todas as empresas</option>
            {empresas.map((empresa) => (
              <option key={empresa.id} value={empresa.id}>
                {empresa.razao_social}
              </option>
            ))}
          </select>
        </div>

        <div>
          <p className="label">Tipo</p>
          <select
            value={tipo}
            onChange={(e) => {
              resetarLista();
              setTipo(e.target.value as TipoDocumentoFiscal | "");
            }}
            className="input"
          >
            <option value="">Todos os tipos</option>
            {(Object.keys(ROTULO_TIPO) as TipoDocumentoFiscal[]).map((chave) => (
              <option key={chave} value={chave}>
                {ROTULO_TIPO[chave]}
              </option>
            ))}
          </select>
        </div>

        <div>
          <p className="label">Direção</p>
          <select
            value={direcao}
            onChange={(e) => {
              resetarLista();
              setDirecao(e.target.value as DirecaoDocumento | "");
            }}
            className="input"
          >
            <option value="">Tomadas e prestadas</option>
            <option value="tomada">Tomadas/recebidas</option>
            <option value="prestada">Prestadas/emitidas</option>
          </select>
        </div>

        <div>
          <p className="label">Situação</p>
          <select
            value={statusDoc}
            onChange={(e) => {
              resetarLista();
              setStatusDoc(e.target.value as StatusDocumentoFiscal | "");
            }}
            className="input"
          >
            <option value="">Normais e canceladas</option>
            <option value="normal">Normais</option>
            <option value="cancelada">Canceladas</option>
          </select>
        </div>

        <div>
          <p className="label">
            Período <span className="text-danger">*</span>
          </p>
          <PeriodoPicker
            valor={periodo}
            aoMudar={(valor) => {
              resetarLista();
              setPeriodo(valor);
            }}
            idPrefixo="documentos"
          />
          {avisoPeriodo && <p className="mt-1 text-xs text-danger">{avisoPeriodo}</p>}
        </div>

        <button type="button" onClick={() => setFiltrosAvancados((valor) => !valor)} className="btn-ghost btn-sm self-end">
          <Icone nome="filtro" className="h-3.5 w-3.5" />
          {filtrosAvancados ? "Ocultar filtros" : "Mais filtros"}
        </button>
        <button type="button" onClick={limparFiltros} className="btn-ghost btn-sm self-end">
          <Icone nome="x" className="h-3.5 w-3.5" />
          {filtrosAtivos > 0 ? `Limpar (${filtrosAtivos})` : "Limpar"}
        </button>
      </div>

      {filtrosAvancados && (
        <div className="card mb-6 grid gap-4 p-4 sm:grid-cols-3 sm:p-5">
          <div>
            <label className="label">XML</label>
            <select
              value={leiaute}
              onChange={(e) => {
                resetarLista();
                setLeiaute(e.target.value as "" | "completo" | "resumo");
              }}
              className="input"
            >
              <option value="">Completos e resumos</option>
              <option value="completo">Somente XML completo</option>
              <option value="resumo">Somente resumo</option>
            </select>
          </div>
          <div>
            <label className="label">Valor mínimo</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={valorMin}
              onChange={(e) => {
                resetarLista();
                setValorMin(e.target.value);
              }}
              placeholder="0,00"
              className="input"
            />
          </div>
          <div>
            <label className="label">Valor máximo</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={valorMax}
              onChange={(e) => {
                resetarLista();
                setValorMax(e.target.value);
              }}
              placeholder="9999,99"
              className="input"
            />
          </div>
          <p className="text-xs leading-5 text-ink-muted sm:col-span-3">
            O período fica no filtro principal e vale para tudo — inclusive ZIP e CSV, que baixam exatamente o
            que está na tela. Aqui ficam os recortes extras: valor, XML pendente, direção e canceladas.
          </p>
        </div>
      )}

      <div className="card mb-6 flex flex-wrap items-center gap-2 p-3 sm:p-4">
        <button
          type="button"
          onClick={baixarTudo}
          disabled={baixando || (estimativa?.documentos ?? 0) === 0}
          className="btn-primary btn-sm"
        >
          <Icone nome="baixar" className="h-3.5 w-3.5" />
          {baixando ? "Preparando…" : `Baixar XMLs (${estimativa?.documentos ?? 0})`}
        </button>
        <button
          type="button"
          onClick={baixarCsv}
          disabled={baixando || (estimativa?.documentos ?? 0) === 0}
          className="btn-ghost btn-sm"
        >
          Baixar CSV
        </button>
        <button
          type="button"
          onClick={baixarSelecionados}
          disabled={baixando || selecionados.size === 0}
          className="btn-ghost btn-sm"
        >
          Baixar seleção ({selecionados.size})
        </button>
        {!somenteLeitura && (
          <button
            type="button"
            onClick={excluirSelecionados}
            disabled={excluindo || selecionados.size === 0}
            className="btn-ghost btn-sm text-danger"
          >
            Excluir seleção ({selecionados.size})
          </button>
        )}
        {estimativa && (
          <span className="text-xs text-ink-muted">
            {estimativa.documentos} documento(s) · ~{bytesParaTexto(estimativa.estimado_bytes)} ·{" "}
            {estimativa.empresas} empresa(s) · ZIP com XMLs + relação.csv
          </span>
        )}
        {semXmlCompleto > 0 && !somenteLeitura && (
          <button
            type="button"
            onClick={completarResumos}
            className="ml-auto text-xs text-warn hover:underline"
            title="A SEFAZ entrega primeiro o resumo (resNFe). O sistema busca o XML completo pela chave, respeitando as janelas oficiais e 20 consultas/hora."
          >
            {semXmlCompleto} carregado(s) só com resumo → buscar XML completo
          </button>
        )}
      </div>

      {mensagem && (
        <p className="mb-4 flex items-center gap-2 rounded-xl border border-warn/20 bg-warn-soft/65 px-3 py-2.5 text-sm text-ink"><Icone nome="info" className="h-4 w-4 flex-none text-warn" />{mensagem}</p>
      )}

      <div className="mb-5 flex flex-wrap gap-2 text-xs text-ink-muted">
        <span className="rounded-full border border-line px-3 py-1">Total: {resumo?.total ?? "—"}</span>
        <span className="rounded-full border border-line px-3 py-1">Normais: {resumo?.normais ?? "—"}</span>
        <span className="rounded-full border border-line px-3 py-1">Canceladas: {resumo?.canceladas ?? "—"}</span>
        {Object.entries(resumo?.por_tipo ?? {}).map(([chave, valor]) => (
          <span key={chave} className="rounded-full border border-line px-3 py-1">
            {ROTULO_TIPO[chave as TipoDocumentoFiscal] ?? chave}: {valor}
          </span>
        ))}
      </div>

      {!periodoOk ? (
        <div className="empty-state">
          <p className="font-display text-base font-extrabold text-ink">Informe o período</p>
          <p className="mt-1 text-xs text-ink-muted">
            {avisoPeriodo} Use os atalhos de mês para preencher o mês inteiro de uma vez.
          </p>
        </div>
      ) : carregando && documentos.length === 0 ? (
        <p className="text-sm text-ink-muted">Carregando…</p>
      ) : documentos.length === 0 ? (
        <div className="empty-state">
          <p className="font-display text-base font-extrabold text-ink">
            Nenhum documento em {periodoRotulo}
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            Se o período for antigo, rode a importação em{" "}
            <Link
              href={`/dashboard/importacoes?data_inicio=${periodo.inicio}&data_fim=${periodo.fim}`}
              className="text-accent hover:underline"
            >
              Importações
            </Link>{" "}
            — a SEFAZ entrega os documentos na ordem de chegada (por NSU) e o sistema guarda apenas os
            emitidos dentro do período que você pedir.
          </p>
        </div>
      ) : (
        <div className="table-shell">
        <table className="tabela">
          <thead className="sticky top-28 bg-surface sm:top-16">
            <tr className="border-b border-line text-left text-ink-muted">
              <th className="py-2 font-normal">
                <input
                  type="checkbox"
                  checked={selecionados.size === documentos.length && documentos.length > 0}
                  onChange={alternarTodos}
                  className="accent-accent"
                  aria-label="Selecionar todos"
                />
              </th>
              <th className="py-2 font-normal">Chave / partes</th>
              <th className="py-2 font-normal">Nº / série</th>
              <th className="py-2 font-normal">Competência</th>
              <th className="py-2 font-normal">Situação</th>
              <th className="py-2 text-right font-normal">Valor</th>
              <th className="py-2 text-right font-normal">Ações</th>
            </tr>
          </thead>
          <tbody>
            {documentos.map((doc) => (
              <tr
                key={doc.id}
                onClick={() => setDocAberto(doc.id)}
                title="Clique para ver o detalhe"
                className={`clicavel border-b border-line last:border-0 ${
                  doc.status === "cancelada" ? "bg-danger-soft/40" : ""
                }`}
              >
                <td className="py-3" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={selecionados.has(doc.id)}
                    onChange={() => alternar(doc.id)}
                    className="accent-accent"
                    aria-label={`Selecionar ${doc.chave_acesso}`}
                  />
                </td>
                <td className="py-3 text-ink">
                  <span className="font-mono" title={doc.chave_acesso}>
                    {truncarChave(doc.chave_acesso)}
                  </span>
                  <span className="ml-2 uppercase text-ink-muted">{doc.tipo}</span>
                  <span className="ml-2 text-xs text-ink-muted">{doc.direcao === "prestada" ? "prestada" : "tomada"}</span>
                  <p className="text-xs text-ink-muted">
                    Emit.: {doc.emitente_nome ?? doc.emitente_documento ?? "não informado"} · {formatarData(doc.data_emissao)}
                  </p>
                  {doc.destinatario_nome && <p className="text-xs text-ink-muted">Dest.: {doc.destinatario_nome}</p>}
                </td>
                <td className="py-3 font-mono text-xs text-ink-muted">
                  {doc.numero ?? "—"}
                  {doc.serie ? ` · ${doc.serie}` : ""}
                  {doc.nsu ? <p>NSU {doc.nsu}</p> : null}
                </td>
                <td className="py-3 font-mono text-xs text-ink">
                  {doc.competencia ? formatarData(doc.competencia).slice(3) : "—"}
                </td>
                <td className="py-3">
                  {doc.status === "cancelada" ? (
                    <span className="text-xs font-medium text-danger" title={doc.motivo_cancelamento ?? ""}>
                      CANCELADA
                      {doc.cancelado_em ? ` em ${formatarData(doc.cancelado_em)}` : ""}
                    </span>
                  ) : doc.leiaute === "resumo" ? (
                    <span className="text-xs text-warn" title="A SEFAZ ainda só devolveu o resumo oficial (resNFe). Use 'buscar XML completo'.">
                      resumo
                    </span>
                  ) : (
                    <span className="text-xs text-ink-muted">Normal</span>
                  )}
                </td>
                <td className={`py-3 text-right font-mono ${doc.status === "cancelada" ? "text-ink-muted line-through" : "text-ink"}`}>
                  {new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(
                    doc.valor_total
                  )}
                </td>
                <td className="py-3 text-right" onClick={(e) => e.stopPropagation()}>
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => api.baixarXmlDocumento(doc.id, `${doc.chave_acesso}.xml`).catch(() => {})}
                      className="text-accent hover:underline"
                    >
                      XML
                    </button>
                    {!somenteLeitura && (
                      <button
                        type="button"
                        onClick={() => excluirDocumento(doc.id)}
                        disabled={excluindo}
                        className="text-danger hover:underline disabled:opacity-50"
                      >
                        Excluir
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      <DocumentoDrawer documentoId={docAberto} aoFechar={() => setDocAberto(null)} />

      <div className="mt-4 flex items-center justify-between text-sm text-ink-muted">
        <span>
          mostrando {documentos.length}
          {resumo ? ` de ${resumo.total}` : ""} no filtro
        </span>
        {documentos.length < (resumo?.total ?? 0) && (
          <button
            type="button"
            onClick={() => setOffset((atual) => atual + PAGINA)}
            title="Carrega a próxima página sem sair do mês"
            disabled={carregando}
            className="text-accent hover:underline disabled:opacity-50"
          >
            carregar mais {Math.min(PAGINA, (resumo?.total ?? 0) - documentos.length)}
          </button>
        )}
      </div>
    </div>
  );
}
