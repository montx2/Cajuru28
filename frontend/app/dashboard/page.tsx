"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { CompetenciaPicker } from "@/components/CompetenciaPicker";
import { horaLocal, paraAPI } from "@/lib/competencia";
import {
  ROTULO_STATUS_LOTE,
  ROTULO_TIPO,
  type Empresa,
  type ItemImportacaoLote,
  type ResumoSincronizacao,
  type TipoDocumentoFiscal,
} from "@/lib/types";

export default function VisaoGeralPage() {
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [tipo, setTipo] = useState<TipoDocumentoFiscal>("nfse");
  const [competencia, setCompetencia] = useState<string | null>(null);
  const [saude, setSaude] = useState<ResumoSincronizacao | null>(null);
  const [disparando, setDisparando] = useState(false);
  const [resultado, setResultado] = useState<ItemImportacaoLote[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api.listarEmpresas().then(setEmpresas).catch(() => {});
    api.resumoSincronizacao().then(setSaude).catch(() => {});
  }, []);

  async function dispararLote() {
    setDisparando(true);
    setErro(null);
    setResultado(null);
    try {
      const itens = await api.solicitarImportacaoEmLote(tipo, {
        competencia: paraAPI(competencia),
      });
      setResultado(itens);
      api.resumoSincronizacao().then(setSaude).catch(() => {});
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
          Dispara a importação para cada empresa ativa. Empresas sem certificado, ou dentro da
          janela de 1 hora que a SEFAZ exige, ficam de fora — e são retomadas sozinhas na hora certa.
        </p>

        {saude && (
          <div className="mb-5 flex flex-wrap gap-x-6 gap-y-2 border-y border-line py-3 text-sm">
            <span className="text-accent">{saude.em_dia} em dia</span>
            <span className="text-ink-muted">
              {saude.com_pendencia} com documento novo
            </span>
            <span className="text-warn">
              {saude.aguardando_janela + saude.bloqueadas_sefaz} na janela da SEFAZ
            </span>
            <span className="text-ink-muted">{saude.em_andamento} varrendo agora</span>
            <span className="ml-auto text-xs text-ink-muted">
              {saude.sincronismo_automatico
                ? `automático a cada ${saude.intervalo_minutos} min`
                : "automático desligado"}{" "}
              · {saude.documentos_no_banco.toLocaleString("pt-BR")} documentos no banco
            </span>
          </div>
        )}

        <div className="flex flex-wrap items-end gap-3">
          <select
            value={tipo}
            onChange={(e) => setTipo(e.target.value as TipoDocumentoFiscal)}
            className="border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          >
            <option value="nfse">NFS-e</option>
            <option value="nfe">NFe</option>
            <option value="cte">CT-e</option>
          </select>

          <div>
            <p className="mb-2 text-xs uppercase text-ink-muted">Competência</p>
            <CompetenciaPicker valor={competencia} aoMudar={setCompetencia} />
          </div>

          <button
            onClick={dispararLote}
            disabled={disparando || empresas.length === 0}
            className="bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {disparando ? "Disparando…" : `Importar ${ROTULO_TIPO[tipo]} de todas`}
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
                    {ROTULO_STATUS_LOTE[item.status] ?? item.status}
                    {item.mensagem ? (
                      <span className="ml-1 text-xs text-ink-muted" title={item.mensagem}>
                        — {item.mensagem.slice(0, 90)}
                      </span>
                    ) : null}
                    {item.disponivel_em ? (
                      <span className="ml-1 text-xs text-warn">
                        retoma {horaLocal(item.disponivel_em)}
                      </span>
                    ) : null}
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
