"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DocumentoFiscal, Empresa, TipoDocumentoFiscal } from "@/lib/types";

const FORMATADOR_MOEDA = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

function formatarData(iso: string): string {
  return new Date(iso).toLocaleDateString("pt-BR");
}

function truncarChave(chave: string): string {
  return `${chave.slice(0, 8)}…${chave.slice(-6)}`;
}

export default function DocumentosPage() {
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [empresaId, setEmpresaId] = useState<number | null>(null);
  const [tipo, setTipo] = useState<TipoDocumentoFiscal | "">("");
  const [documentos, setDocumentos] = useState<DocumentoFiscal[]>([]);
  const [carregando, setCarregando] = useState(false);

  useEffect(() => {
    api.listarEmpresas().then((lista) => {
      setEmpresas(lista);
      if (lista.length > 0) setEmpresaId(lista[0].id);
    });
  }, []);

  useEffect(() => {
    if (empresaId === null) return;
    setCarregando(true);
    api
      .listarDocumentos(empresaId, tipo ? { tipo } : undefined)
      .then(setDocumentos)
      .finally(() => setCarregando(false));
  }, [empresaId, tipo]);

  const total = documentos.reduce((soma, doc) => soma + doc.valor_total, 0);

  return (
    <div>
      <p className="mb-6 font-serif text-2xl text-ink">Documentos</p>

      <div className="mb-5 flex gap-3">
        <select
          value={empresaId ?? ""}
          onChange={(e) => setEmpresaId(Number(e.target.value))}
          className="border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        >
          {empresas.map((empresa) => (
            <option key={empresa.id} value={empresa.id}>
              {empresa.razao_social}
            </option>
          ))}
        </select>

        <select
          value={tipo}
          onChange={(e) => setTipo(e.target.value as TipoDocumentoFiscal | "")}
          className="border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
        >
          <option value="">Todos os tipos</option>
          <option value="nfse">NFS-e</option>
          <option value="nfe">NFe</option>
          <option value="cte">CT-e</option>
        </select>
      </div>

      {carregando ? (
        <p className="text-sm text-ink-muted">Carregando…</p>
      ) : documentos.length === 0 ? (
        <div className="border border-line bg-surface p-8 text-center">
          <p className="text-sm text-ink-muted">Nenhum documento importado ainda para este filtro.</p>
        </div>
      ) : (
        <>
          <table className="w-full border-t border-line text-sm">
            <thead>
              <tr className="border-b border-line text-left text-ink-muted">
                <th className="py-2 font-normal">Chave de acesso</th>
                <th className="py-2 font-normal">Tipo</th>
                <th className="py-2 font-normal">Direção</th>
                <th className="py-2 font-normal">Emissão</th>
                <th className="py-2 text-right font-normal">Valor</th>
                <th className="py-2 text-right font-normal">Arquivo</th>
              </tr>
            </thead>
            <tbody>
              {documentos.map((doc) => (
                <tr key={doc.id} className="border-b border-line last:border-0">
                  <td className="py-3 font-mono text-ink" title={doc.chave_acesso}>
                    {truncarChave(doc.chave_acesso)}
                  </td>
                  <td className="py-3 uppercase text-ink-muted">{doc.tipo}</td>
                  <td className="py-3 text-ink-muted">
                    {doc.direcao === "tomada" ? "Tomada" : "Prestada"}
                  </td>
                  <td className="py-3 text-ink-muted">{formatarData(doc.data_emissao)}</td>
                  <td className="py-3 text-right font-mono text-ink">
                    {FORMATADOR_MOEDA.format(doc.valor_total)}
                  </td>
                  <td className="py-3 text-right">
                    <button
                      type="button"
                      onClick={() =>
                        api.baixarXmlDocumento(doc.id, `${doc.chave_acesso}.xml`).catch(() => {})
                      }
                      className="text-accent hover:underline"
                    >
                      XML
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-right text-sm text-ink-muted">
            {documentos.length} documentos — total{" "}
            <span className="font-mono text-ink">{FORMATADOR_MOEDA.format(total)}</span>
          </p>
        </>
      )}
    </div>
  );
}
