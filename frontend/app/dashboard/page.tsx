"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { Empresa, ItemImportacaoLote, TipoDocumentoFiscal } from "@/lib/types";

const RÓTULO_TIPO: Record<TipoDocumentoFiscal, string> = {
  nfse: "NFS-e",
  nfe: "NFe",
  cte: "CT-e",
};

const RÓTULO_STATUS_LOTE: Record<ItemImportacaoLote["status"], string> = {
  enfileirada: "Enfileirada",
  em_cooldown: "Aguardando (sem novidade há pouco)",
  sem_certificado: "Sem certificado ativo",
};

export default function VisaoGeralPage() {
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [tipo, setTipo] = useState<TipoDocumentoFiscal>("nfse");
  const [disparando, setDisparando] = useState(false);
  const [resultado, setResultado] = useState<ItemImportacaoLote[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api.listarEmpresas().then(setEmpresas).catch(() => {});
  }, []);

  async function dispararLote() {
    setDisparando(true);
    setErro(null);
    setResultado(null);
    try {
      const itens = await api.solicitarImportacaoEmLote(tipo);
      setResultado(itens);
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível disparar a importação.");
    } finally {
      setDisparando(false);
    }
  }

  return (
    <div>
      <p className="font-serif text-3xl text-ink">{empresas.length}</p>
      <p className="mb-8 text-sm text-ink-muted">
        {empresas.length === 1 ? "empresa cadastrada" : "empresas cadastradas"} —{" "}
        <Link href="/dashboard/empresas" className="text-accent hover:underline">
          gerenciar
        </Link>
      </p>

      <div className="border border-line bg-surface p-6">
        <p className="mb-1 text-base font-medium text-ink">Importar de todas as empresas</p>
        <p className="mb-4 text-sm text-ink-muted">
          Dispara a importação para cada empresa ativa. Empresas sem certificado, ou que já
          checaram o portal recentemente sem nada novo, ficam de fora — sem tentar duas vezes à toa.
        </p>

        <div className="flex items-center gap-3">
          <select
            value={tipo}
            onChange={(e) => setTipo(e.target.value as TipoDocumentoFiscal)}
            className="border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          >
            <option value="nfse">NFS-e</option>
            <option value="nfe">NFe</option>
            <option value="cte">CT-e</option>
          </select>

          <button
            onClick={dispararLote}
            disabled={disparando || empresas.length === 0}
            className="bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {disparando ? "Disparando…" : `Importar ${RÓTULO_TIPO[tipo]} de todas`}
          </button>
        </div>

        {erro && (
          <p className="mt-4 border border-danger-soft bg-danger-soft px-3 py-2 text-sm text-danger">
            {erro}
          </p>
        )}

        {resultado && (
          <table className="mt-5 w-full border-t border-line text-sm">
            <thead>
              <tr className="border-b border-line text-left text-ink-muted">
                <th className="py-2 font-normal">Empresa</th>
                <th className="py-2 font-normal">Situação</th>
              </tr>
            </thead>
            <tbody>
              {resultado.map((item) => (
                <tr key={item.empresa_id} className="border-b border-line last:border-0">
                  <td className="py-2 text-ink">{item.razao_social}</td>
                  <td className="py-2 text-ink-muted">
                    {RÓTULO_STATUS_LOTE[item.status]}
                    {item.status === "enfileirada" && item.execucao_id && (
                      <>
                        {" — "}
                        <Link
                          href={`/dashboard/importacoes?execucao=${item.execucao_id}`}
                          className="text-accent hover:underline"
                        >
                          acompanhar
                        </Link>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
