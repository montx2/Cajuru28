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
  const [selecionadas, setSelecionadas] = useState<Set<number>>(new Set());
  const [modoSelecao, setModoSelecao] = useState(false);

  useEffect(() => {
    api.listarEmpresas().then(setEmpresas).catch(() => {});
    api.resumoSincronizacao().then(setSaude).catch(() => {});
  }, []);

  function alternarEmpresa(id: number) {
    setSelecionadas((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(id)) proximo.delete(id);
      else proximo.add(id);
      return proximo;
    });
  }

  function selecionarTodas() {
    if (selecionadas.size === empresas.length) {
      setSelecionadas(new Set());
    } else {
      setSelecionadas(new Set(empresas.map((e) => e.id)));
    }
  }

  async function dispararLote() {
    setDisparando(true);
    setErro(null);
    setResultado(null);
    try {
      const empresa_ids = modoSelecao && selecionadas.size > 0 ? [...selecionadas].join(",") : undefined;
      const itens = await api.solicitarImportacaoEmLote(tipo, {
        competencia: paraAPI(competencia),
        empresa_ids,
      });
      setResultado(itens);
      api.resumoSincronizacao().then(setSaude).catch(() => {});
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível disparar a importação.");
    } finally {
      setDisparando(false);
    }
  }

  const totalSelecionadas = selecionadas.size;
  const textoBotao = modoSelecao
    ? totalSelecionadas > 0
      ? `Importar ${ROTULO_TIPO[tipo]} de ${totalSelecionadas} selecionada(s)`
      : `Selecione empresas acima`
    : `Importar ${ROTULO_TIPO[tipo]} de todas`;

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
        <div className="mb-1 flex items-center justify-between">
          <p className="text-base font-medium text-ink">
            {modoSelecao ? "Importar de empresas selecionadas" : "Importar de todas as empresas"}
          </p>
          <button
            type="button"
            onClick={() => {
              setModoSelecao(!modoSelecao);
              setSelecionadas(new Set());
            }}
            className="text-xs text-accent hover:underline"
          >
            {modoSelecao ? "← voltar para todas" : "Selecionar quais empresas →"}
          </button>
        </div>
        <p className="mb-4 text-sm text-ink-muted">
          {modoSelecao
            ? "Marque apenas as empresas que você quer importar agora. Ideal quando você tem muitas empresas mas só precisa de algumas."
            : "Dispara a importação para cada empresa ativa. Empresas sem certificado, ou dentro da janela de 1 hora que a SEFAZ exige, ficam de fora — e são retomadas sozinhas na hora certa."}
        </p>

        {saude && (
          <div className="mb-5 flex flex-wrap gap-x-6 gap-y-2 border-y border-line py-3 text-sm">
            <span className="text-accent">{saude.em_dia} em dia</span>
            <span className="text-ink-muted">{saude.com_pendencia} com documento novo</span>
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

        {modoSelecao && empresas.length > 0 && (
          <div className="mb-5 border border-line bg-bg p-4">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-sm font-medium text-ink">
                Empresas ({totalSelecionadas} de {empresas.length} selecionadas)
              </p>
              <button
                type="button"
                onClick={selecionarTodas}
                className="text-xs text-accent hover:underline"
              >
                {selecionadas.size === empresas.length ? "Desmarcar todas" : "Marcar todas"}
              </button>
            </div>
            <div className="max-h-48 overflow-y-auto space-y-1">
              {empresas.map((emp) => (
                <label
                  key={emp.id}
                  className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-surface cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={selecionadas.has(emp.id)}
                    onChange={() => alternarEmpresa(emp.id)}
                    className="accent-accent"
                  />
                  <span className="text-sm text-ink">{emp.razao_social}</span>
                  <span className="ml-auto text-xs font-mono text-ink-muted">{emp.cnpj_cpf}</span>
                </label>
              ))}
            </div>
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
            disabled={disparando || empresas.length === 0 || (modoSelecao && totalSelecionadas === 0)}
            className="bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {disparando ? "Disparando…" : textoBotao}
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
