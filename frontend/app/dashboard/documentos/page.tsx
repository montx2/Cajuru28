"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError, type FiltrosExportacao } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import { CompetenciaPicker } from "@/components/CompetenciaPicker";
import { DocumentoDrawer } from "@/components/DocumentoDrawer";
import { Icone } from "@/components/icons";
import { bytesParaTexto, paraAPI, rotulo as rotuloMes } from "@/lib/competencia";
import {
  ROTULO_TIPO,
  type DirecaoDocumento,
  type DocumentoFiscal,
  type Empresa,
  type EstimativaExportacao,
  type ResumoDocumentos,
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
 * Documentos — lista, filtra e baixa os XMLs importados.
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
  const [competencia, setCompetencia] = useState<string | null>(
    searchParams.get("competencia") || null
  );
  const [somenteResumo, setSomenteResumo] = useState(false);
  // A busca global da barra superior chega por `?busca=`.
  const [busca, setBusca] = useState(searchParams.get("busca") || "");
  const [termoBusca, setTermoBusca] = useState(searchParams.get("busca") || "");
  const [aba, setAba] = useState<DirecaoDocumento | "todas" | "cancelada">("todas");
  const [docAberto, setDocAberto] = useState<number | null>(null);
  const { somenteLeitura } = usePapel();

  const [documentos, setDocumentos] = useState<DocumentoFiscal[]>([]);
  const [resumo, setResumo] = useState<ResumoDocumentos | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selecionados, setSelecionados] = useState<Set<number>>(new Set());
  const [estimativa, setEstimativa] = useState<EstimativaExportacao | null>(null);
  const [baixando, setBaixando] = useState(false);
  const [mensagem, setMensagem] = useState<string | null>(null);

  useEffect(() => {
    api.listarEmpresas().then(setEmpresas).catch(() => {});
  }, []);

  // Uma única definição de filtro para a tela, para o contador e para o ZIP —
  // é o que faz "12 documentos na tela" virar "12 arquivos no ZIP".
  const filtros = useMemo(() => {
    const competenciaAPI = competencia ? paraAPI(competencia) : undefined;
    return {
      ...(empresaId === "todas" ? {} : { empresa_id: empresaId }),
      ...(tipo ? { tipo } : {}),
      ...(competenciaAPI ? { competencia: competenciaAPI } : {}),
      ...(somenteResumo ? { leiaute: "resumo" as const } : {}),
      ...(termoBusca ? { busca: termoBusca } : {}),
    };
  }, [empresaId, tipo, competencia, somenteResumo, termoBusca]);

  useEffect(() => {
    setSelecionados(new Set());
  }, [filtros]);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const [lista, agregado, estimado] = await Promise.all([
        api.listarDocumentos({ ...filtros, limit: PAGINA, offset }),
        api.resumoDocumentos({
          empresa_id: empresaId === "todas" ? undefined : empresaId,
          competencia: filtros.competencia,
        }),
        api.estimarExportacao(filtros),
      ]);
      setDocumentos((atual) => (offset === 0 ? lista : [...atual, ...lista]));
      setResumo(agregado);
      setEstimativa(estimado);
    } catch (e) {
      setMensagem(e instanceof ApiError ? e.message : "Não foi possível listar os documentos.");
    } finally {
      setCarregando(false);
    }
  }, [filtros, offset, empresaId]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  async function baixarTudo() {
    setBaixando(true);
    setMensagem(null);
    try {
      await api.baixarZip(
        filtros as FiltrosExportacao,
        `NotasFlow_${competencia ?? "todos"}.zip`
      );
      setMensagem("Download iniciado — o ZIP traz os XMLs, a relação em CSV e um LEIA-ME.");
    } catch (e) {
      setMensagem(e instanceof ApiError ? e.message : "O download não começou.");
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

  const tomadas = documentos.filter((d) => d.direcao === "tomada" && d.status !== "cancelada");
  const prestadas = documentos.filter((d) => d.direcao === "prestada" && d.status !== "cancelada");
  const canceladas = documentos.filter((d) => d.status === "cancelada");
  const grupos: Record<typeof aba, DocumentoFiscal[]> = {
    todas: documentos,
    tomada: tomadas,
    prestada: prestadas,
    cancelada: canceladas,
  };
  const visiveis = grupos[aba];
  const semXmlCompleto = documentos.filter((d) => d.leiaute === "resumo").length;

  return (
    <div className="animate-fade-up">
      <div className="page-header">
        <div>
          <p className="page-kicker">Acervo fiscal</p>
          <h1 className="page-title">Documentos</h1>
          <p className="page-description">
            {rotuloMes(competencia)} · {resumo ? `${resumo.total} documento(s), ${resumo.canceladas} cancelada(s)` : "Lendo o acervo…"}
          </p>
        </div>
        <Link href={`/dashboard/importacoes${competencia ? `?competencia=${competencia}` : ""}`} className="btn-primary btn-sm">
          <Icone nome="importacao" className="h-3.5 w-3.5" /> Importar notas
        </Link>
      </div>

      <div className="filter-bar">
        <div>
          <p className="mb-2 text-xs uppercase text-ink-muted">Empresa</p>
          <select
            value={empresaId === "todas" ? "todas" : String(empresaId)}
            onChange={(e) =>
              setEmpresaId(e.target.value === "todas" ? "todas" : Number(e.target.value))
            }
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
          <p className="mb-2 text-xs uppercase text-ink-muted">Tipo</p>
          <select
            value={tipo}
            onChange={(e) => setTipo(e.target.value as TipoDocumentoFiscal | "")}
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
          <p className="mb-2 text-xs uppercase text-ink-muted">Competência</p>
          <CompetenciaPicker valor={competencia} aoMudar={setCompetencia} />
        </div>

        <div>
          <p className="mb-2 text-xs uppercase text-ink-muted">Busca</p>
          <div className="flex gap-2">
            <input
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") setTermoBusca(busca.trim());
              }}
              placeholder="chave, número ou emitente"
              className="input w-64"
            />
            <button
              type="button"
              onClick={() => setTermoBusca(busca.trim())}
              className="btn-ghost btn-sm"
            >
              Buscar
            </button>
          </div>
        </div>

        <label className="flex items-center gap-2 pb-2 text-sm text-ink-muted">
          <input
            type="checkbox"
            checked={somenteResumo}
            onChange={(e) => setSomenteResumo(e.target.checked)}
            className="accent-accent"
          />
          só quem veio em resumo
        </label>
      </div>

      <div className="card mb-6 flex flex-wrap items-center gap-2 p-3 sm:p-4">
        <button
          type="button"
          onClick={baixarTudo}
          disabled={baixando || (estimativa?.documentos ?? 0) === 0}
          className="btn-primary btn-sm"
        >
          <Icone nome="baixar" className="h-3.5 w-3.5" />
          {baixando ? "Preparando ZIP…" : `Baixar XMLs (${estimativa?.documentos ?? 0})`}
        </button>
        <button
          type="button"
          onClick={baixarSelecionados}
          disabled={baixando || selecionados.size === 0}
          className="btn-ghost btn-sm"
        >
          Baixar seleção ({selecionados.size})
        </button>
        {estimativa && (
          <span className="text-xs text-ink-muted">
            {estimativa.documentos} arquivo(s) · ~{bytesParaTexto(estimativa.estimado_bytes)} ·{" "}
            {estimativa.empresas} empresa(s) · ZIP com XMLs + relação.csv
          </span>
        )}
        {semXmlCompleto > 0 && !somenteLeitura && (
          <button
            type="button"
            onClick={completarResumos}
            className="ml-auto text-xs text-warn hover:underline"
            title="A SEFAZ entrega primeiro o resumo (resNFe). O sistema busca o XML completo pela chave, respeitando as 20 consultas/hora."
          >
            {semXmlCompleto} só com resumo → buscar XML completo
          </button>
        )}
      </div>

      {mensagem && (
        <p className="mb-4 flex items-center gap-2 rounded-xl border border-warn/20 bg-warn-soft/65 px-3 py-2.5 text-sm text-ink"><Icone nome="info" className="h-4 w-4 flex-none text-warn" />{mensagem}</p>
      )}

      <div className="tabs mb-5 w-fit max-w-full">
        {(
          [
            ["todas", `Todas (${grupos.todas.length})`],
            ["tomada", `Tomadas (${tomadas.length})`],
            ["prestada", `Prestadas (${prestadas.length})`],
            ["cancelada", `Canceladas (${canceladas.length})`],
          ] as const
        ).map(([id, rotuloAba]) => (
          <button key={id} type="button" onClick={() => setAba(id)} className={`tab ${aba === id ? "tab-active" : ""}`}>
            {rotuloAba}
          </button>
        ))}
      </div>

      {carregando && documentos.length === 0 ? (
        <p className="text-sm text-ink-muted">Carregando…</p>
      ) : visiveis.length === 0 ? (
        <div className="empty-state">
          <p className="font-display text-base font-extrabold text-ink">Nenhum documento neste filtro</p>
          <p className="mt-1 text-xs text-ink-muted">
            Se o mês for antigo, rode a importação em{" "}
            <Link href="/dashboard/importacoes" className="text-accent hover:underline">
              Importações
            </Link>{" "}
            — a SEFAZ entrega os documentos na ordem de chegada (por NSU), e a competência filtra o que já
            está guardado.
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
                  checked={selecionados.size === visiveis.length && visiveis.length > 0}
                  onChange={alternarTodos}
                  className="accent-accent"
                  aria-label="Selecionar todos"
                />
              </th>
              <th className="py-2 font-normal">Chave / emitente</th>
              <th className="py-2 font-normal">Nº / série</th>
              <th className="py-2 font-normal">Competência</th>
              <th className="py-2 font-normal">Situação</th>
              <th className="py-2 text-right font-normal">Valor</th>
              <th className="py-2 text-right font-normal">Arquivo</th>
            </tr>
          </thead>
          <tbody>
            {visiveis.map((doc) => (
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
                  <p className="text-xs text-ink-muted">
                    {doc.emitente_nome ?? "emitente não informado"} · {formatarData(doc.data_emissao)}
                  </p>
                </td>
                <td className="py-3 font-mono text-xs text-ink-muted">
                  {doc.numero ?? "—"}
                  {doc.serie ? ` · ${doc.serie}` : ""}
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
                    <span className="text-xs text-warn" title="A SEFAZ ainda só devolveu o resumo oficial (resNFe). O XML completo chega na próxima rodada.">
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
                  <button
                    type="button"
                    onClick={() => api.baixarXmlDocumento(doc.id, `${doc.chave_acesso}.xml`).catch(() => {})}
                    className="text-accent hover:underline"
                  >
                    XML
                  </button>
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
