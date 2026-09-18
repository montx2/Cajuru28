"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import {
  copiarTexto,
  dataCurta,
  dataHora,
  formatarCnpjCpf,
  mesAno,
  moeda,
} from "@/lib/format";
import { bytesParaTexto as bytesXml } from "@/lib/competencia";
import { ROTULO_TIPO, type DocumentoDetalhe } from "@/lib/types";
import { Icone } from "./icons";
import { Esqueleto } from "./ui";
import { useToast } from "./Toast";

/** Realce simples de XML: tags, atributos e valores em cores distintas. */
function realcarXml(xml: string): React.ReactNode[] {
  const partes = xml.split(/(<[^>]+>)/g).filter(Boolean);
  return partes.map((parte, i) => {
    if (!parte.startsWith("<")) {
      return (
        <span key={i} className="text-amber-100">
          {parte}
        </span>
      );
    }
    const tokens = parte.split(/("[^"]*")/g).filter(Boolean);
    return (
      <span key={i} className="text-emerald-300">
        {tokens.map((t, j) =>
          t.startsWith('"') ? (
            <span key={j} className="text-sky-300">
              {t}
            </span>
          ) : (
            <span key={j}>{t}</span>
          )
        )}
      </span>
    );
  });
}

function Linha({ rotulo, valor, mono }: { rotulo: string; valor: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 py-2">
      <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">{rotulo}</span>
      <span className={`text-right text-sm text-ink ${mono ? "font-mono text-xs" : ""}`}>{valor}</span>
    </div>
  );
}

export function DocumentoDrawer({
  documentoId,
  aoFechar,
}: {
  documentoId: number | null;
  aoFechar: () => void;
}) {
  const toast = useToast();
  const [doc, setDoc] = useState<DocumentoDetalhe | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [mostrarXml, setMostrarXml] = useState(false);
  const [xml, setXml] = useState<string | null>(null);
  const [carregandoXml, setCarregandoXml] = useState(false);

  const carregar = useCallback(async (id: number) => {
    setCarregando(true);
    setErro(null);
    setMostrarXml(false);
    setXml(null);
    try {
      setDoc(await api.detalheDocumento(id));
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível abrir o documento.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    if (documentoId) carregar(documentoId);
    else setDoc(null);
  }, [documentoId, carregar]);

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (e.key === "Escape") aoFechar();
    };
    if (documentoId) {
      window.addEventListener("keydown", tecla);
      document.body.style.overflow = "hidden";
    }
    return () => {
      window.removeEventListener("keydown", tecla);
      document.body.style.overflow = "";
    };
  }, [documentoId, aoFechar]);

  async function verXml() {
    if (!doc || !documentoId) return;
    if (mostrarXml) {
      setMostrarXml(false);
      return;
    }
    setMostrarXml(true);
    if (xml !== null) return;
    setCarregandoXml(true);
    try {
      const texto = await api.obterXmlTexto(documentoId);
      setXml(texto.length > 200_000 ? texto.slice(0, 200_000) + "\n<!-- …cortado para exibição -->" : texto);
    } catch {
      setXml(null);
      toast.erro("Não foi possível ler o XML.");
      setMostrarXml(false);
    } finally {
      setCarregandoXml(false);
    }
  }

  async function copiar(chave: string) {
    const ok = await copiarTexto(chave);
    if (ok) toast.sucesso("Chave de acesso copiada.");
    else toast.erro("Não foi possível copiar.");
  }

  if (!documentoId) return null;
  const cancelada = doc?.status === "cancelada";

  return (
    <div className="no-print fixed inset-0 z-50">
      <div className="animate-fade-in absolute inset-0 bg-ink/50" onClick={aoFechar} />
      <aside className="animate-slide-in-right absolute inset-y-0 right-0 flex w-full max-w-lg flex-col bg-surface shadow-pop">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <p className="font-serif text-lg font-semibold text-ink">Detalhe do documento</p>
          <button type="button" onClick={aoFechar} className="btn-icon" aria-label="Fechar">
            <Icone nome="x" className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {carregando || !doc ? (
            <div className="space-y-3">
              <Esqueleto className="h-28" />
              <Esqueleto className="h-40" />
              <Esqueleto className="h-24" />
            </div>
          ) : erro ? (
            <p className="rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
              {erro}
            </p>
          ) : (
            <>
              {/* cabeçalho tipo DANFE */}
              <div className={`rounded-card border p-4 ${cancelada ? "border-danger/40 bg-danger-soft/50" : "border-line bg-bg"}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="badge-ok">{ROTULO_TIPO[doc.tipo] ?? doc.tipo}</span>
                  <span className="badge-neutral">{doc.direcao === "tomada" ? "Tomada" : "Prestada"}</span>
                  {cancelada ? (
                    <span className="badge-danger">Cancelada</span>
                  ) : doc.leiaute === "resumo" ? (
                    <span className="badge-warn">Só resumo</span>
                  ) : (
                    <span className="badge-ok">XML completo</span>
                  )}
                </div>
                <p className="mt-3 font-serif text-3xl font-semibold text-ink">{moeda(doc.valor_total)}</p>
                <p className="mt-1 text-sm text-ink-muted">
                  Nº {doc.numero ?? "—"}
                  {doc.serie ? ` · Série ${doc.serie}` : ""} · Emitida em {dataCurta(doc.data_emissao)} ·
                  Competência {mesAno(doc.competencia ?? doc.data_emissao)}
                </p>
                {cancelada && doc.motivo_cancelamento && (
                  <p className="mt-2 text-xs text-danger">
                    Cancelada{doc.cancelado_em ? ` em ${dataHora(doc.cancelado_em)}` : ""}: {doc.motivo_cancelamento}
                  </p>
                )}
              </div>

              {/* partes */}
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div className="rounded-card border border-line p-3">
                  <p className="label">Emitente</p>
                  <p className="truncate text-sm font-semibold text-ink" title={doc.emitente_nome ?? ""}>
                    {doc.emitente_nome ?? "—"}
                  </p>
                  <p className="font-mono text-xs text-ink-muted">{formatarCnpjCpf(doc.emitente_documento)}</p>
                </div>
                <div className="rounded-card border border-line p-3">
                  <p className="label">Destinatário</p>
                  <p className="truncate text-sm font-semibold text-ink" title={doc.destinatario_nome ?? ""}>
                    {doc.destinatario_nome ?? "—"}
                  </p>
                  <p className="font-mono text-xs text-ink-muted">
                    {doc.destinatario_documento ? formatarCnpjCpf(doc.destinatario_documento) : "—"}
                  </p>
                </div>
              </div>

              {/* chave */}
              <div className="mt-3 rounded-card border border-line p-3">
                <p className="label">Chave de acesso</p>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 break-all font-mono text-xs text-ink">{doc.chave_acesso}</code>
                  <button type="button" onClick={() => copiar(doc.chave_acesso)} className="btn-icon flex-none" title="Copiar chave">
                    <Icone nome="copiar" className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {/* ficha */}
              <div className="mt-3 divide-y divide-line/70 rounded-card border border-line px-4">
                <Linha rotulo="Empresa" valor={doc.empresa_razao_social} />
                <Linha rotulo="CNPJ" valor={formatarCnpjCpf(doc.empresa_cnpj)} mono />
                <Linha rotulo="NSU" valor={doc.nsu ?? "—"} mono />
                <Linha rotulo="Importado em" valor={dataHora(doc.importado_em)} />
                <Linha
                  rotulo="Origem"
                  valor={
                    doc.execucao_id ? (
                      <Link
                        href={`/dashboard/importacoes?execucao=${doc.execucao_id}`}
                        className="link"
                        onClick={aoFechar}
                      >
                        execução #{doc.execucao_id}
                      </Link>
                    ) : (
                      "—"
                    )
                  }
                />
              </div>

              {/* XML */}
              <div className="mt-4">
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={!doc.xml_disponivel}
                    onClick={() => api.baixarXmlDocumento(doc.id, `${doc.chave_acesso}.xml`).catch(() => toast.erro("O download não começou."))}
                    className="btn-primary btn-sm"
                  >
                    <Icone nome="baixar" className="h-4 w-4" /> Baixar XML
                    {doc.xml_bytes ? ` (${bytesXml(doc.xml_bytes)})` : ""}
                  </button>
                  <button
                    type="button"
                    disabled={!doc.xml_disponivel}
                    onClick={verXml}
                    className="btn-ghost btn-sm"
                  >
                    <Icone nome="codigo" className="h-4 w-4" />
                    {mostrarXml ? "Ocultar código" : "Ver código"}
                  </button>
                </div>
                {!doc.xml_disponivel && (
                  <p className="mt-2 text-xs text-warn">
                    O arquivo XML não está no disco — apenas os dados da nota estão guardados.
                  </p>
                )}
                {mostrarXml && (
                  <div className="mt-3">
                    {carregandoXml ? (
                      <Esqueleto className="h-48" />
                    ) : xml ? (
                      <pre className="xml-code max-h-96 whitespace-pre-wrap break-all">{realcarXml(xml)}</pre>
                    ) : null}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
