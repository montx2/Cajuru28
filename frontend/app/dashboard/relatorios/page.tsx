"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { CompetenciaPicker } from "@/components/CompetenciaPicker";
import { Icone } from "@/components/icons";
import { useToast } from "@/components/Toast";
import { Esqueleto, KpiCard, TituloSecao } from "@/components/ui";
import { formatarCnpjCpf, moeda, numero } from "@/lib/format";
import { mesAtual, paraAPI } from "@/lib/competencia";
import type { FechamentoMensal } from "@/lib/types";

/**
 * Fechamento mensal: o mapa contábil empresa × tipo do mês.
 * Imprimível (só o relatório sai no papel) e exportável em CSV e ZIP.
 */
export default function RelatoriosPage() {
  const toast = useToast();
  const [competencia, setCompetencia] = useState<string | null>(mesAtual());
  const [fechamento, setFechamento] = useState<FechamentoMensal | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [baixando, setBaixando] = useState(false);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      setFechamento(await api.fechamento(paraAPI(competencia)));
    } catch (e) {
      toast.erro(e instanceof ApiError ? e.message : "Não foi possível carregar o fechamento.");
    } finally {
      setCarregando(false);
    }
  }, [competencia, toast]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  async function baixarCsv() {
    if (!fechamento) return;
    setBaixando(true);
    try {
      await api.baixarFechamentoCsv(paraAPI(competencia));
      toast.sucesso("CSV do fechamento baixado.");
    } catch {
      toast.erro("O download não começou.");
    } finally {
      setBaixando(false);
    }
  }

  async function baixarZip() {
    if (!fechamento) return;
    setBaixando(true);
    try {
      await api.baixarZip(
        { competencia: paraAPI(competencia) },
        `NotasFlow_${fechamento.competencia.replace("/", "-")}.zip`
      );
      toast.sucesso("Download do ZIP iniciado.");
    } catch (e) {
      toast.erro(e instanceof ApiError ? e.message : "O download não começou.");
    } finally {
      setBaixando(false);
    }
  }

  const t = fechamento?.totais;

  return (
    <div className="animate-fade-up">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-serif text-3xl font-semibold text-ink">Fechamento mensal</h1>
          <p className="mt-1 text-sm text-ink-muted">
            O mapa empresa × tipo do mês — para conferir antes de enviar ao cliente.
          </p>
        </div>
        <div className="no-print flex flex-wrap items-end gap-2">
          <div>
            <p className="label">Competência</p>
            <CompetenciaPicker valor={competencia} aoMudar={setCompetencia} />
          </div>
          <button type="button" onClick={baixarCsv} disabled={baixando || !fechamento} className="btn-ghost btn-sm">
            <Icone nome="baixar" className="h-4 w-4" /> CSV
          </button>
          <button type="button" onClick={baixarZip} disabled={baixando || !fechamento} className="btn-ghost btn-sm">
            <Icone nome="pasta" className="h-4 w-4" /> ZIP do mês
          </button>
          <button type="button" onClick={() => window.print()} className="btn-ghost btn-sm" title="Imprimir relatório">
            <Icone nome="imprimir" className="h-4 w-4" />
          </button>
        </div>
      </div>

      {carregando || !fechamento || !t ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <Esqueleto className="h-28" />
            <Esqueleto className="h-28" />
            <Esqueleto className="h-28" />
            <Esqueleto className="h-28" />
          </div>
          <Esqueleto className="h-64" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
            <KpiCard
              rotulo={`Documentos em ${fechamento.competencia}`}
              valor={numero(t.documentos)}
              detalhe={t.por_tipo ? `NFS-e ${t.por_tipo.nfse?.qtd ?? 0} · NFe ${t.por_tipo.nfe?.qtd ?? 0} · CT-e ${t.por_tipo.cte?.qtd ?? 0}` : undefined}
              icone="documento"
              tom="ok"
            />
            <KpiCard
              rotulo="Valor líquido"
              valor={moeda(t.valor)}
              detalhe={`${t.canceladas} cancelada(s) excluídas`}
              icone="moeda"
              tom="padrao"
            />
            <KpiCard
              rotulo="Empresas com documento"
              valor={`${t.empresas_com_documento}/${t.empresas_total}`}
              detalhe="no mês selecionado"
              icone="empresa"
              tom={t.empresas_com_documento < t.empresas_total ? "alerta" : "ok"}
            />
            <KpiCard
              rotulo="Pendências"
              valor={numero(t.sem_xml)}
              detalhe={t.sem_xml > 0 ? "aguardando XML completo" : "nenhuma"}
              icone="relogio"
              tom={t.sem_xml > 0 ? "alerta" : "ok"}
              href="/dashboard/documentos"
            />
          </div>

          <section className="card-pad mt-4">
            <TituloSecao
              titulo={`Mapa de ${fechamento.competencia}`}
              subtitulo={`${fechamento.inicio.split("-").reverse().join("/")} a ${fechamento.fim.split("-").reverse().join("/")}`}
            />
            <div className="overflow-x-auto">
              <table className="tabela">
                <thead>
                  <tr>
                    <th>Empresa</th>
                    <th className="text-right">NFS-e</th>
                    <th className="text-right">NFe</th>
                    <th className="text-right">CT-e</th>
                    <th className="text-right">Total</th>
                    <th className="text-right">Valor líquido</th>
                    <th className="text-right">Cancel.</th>
                    <th className="text-right">Sem XML</th>
                  </tr>
                </thead>
                <tbody>
                  {fechamento.empresas.map((e) => (
                    <tr key={e.empresa_id}>
                      <td>
                        <Link href={`/dashboard/empresa?id=${e.empresa_id}`} className="link font-medium">
                          {e.razao_social}
                        </Link>
                        <span className="block font-mono text-[11px] text-ink-faint">
                          {formatarCnpjCpf(e.cnpj)} · {e.uf}
                        </span>
                      </td>
                      {(["nfse", "nfe", "cte"] as const).map((tipo) => (
                        <td key={tipo} className="text-right font-mono text-xs">
                          {e.por_tipo[tipo]?.qtd ? (
                            <>
                              <span className="text-ink">{numero(e.por_tipo[tipo].qtd)}</span>
                              <span className="block text-[11px] text-ink-faint">
                                {moeda(e.por_tipo[tipo].valor)}
                              </span>
                            </>
                          ) : (
                            <span className="text-ink-faint">–</span>
                          )}
                        </td>
                      ))}
                      <td className="text-right font-mono font-semibold text-ink">
                        {e.total > 0 ? numero(e.total) : <span className="font-normal text-ink-faint">–</span>}
                      </td>
                      <td className="text-right font-mono text-ink">{e.total > 0 ? moeda(e.valor) : "–"}</td>
                      <td className="text-right font-mono">
                        {e.canceladas > 0 ? <span className="text-danger">{e.canceladas}</span> : <span className="text-ink-faint">–</span>}
                      </td>
                      <td className="text-right font-mono">
                        {e.sem_xml > 0 ? <span className="text-warn">{e.sem_xml}</span> : <span className="text-ink-faint">–</span>}
                      </td>
                    </tr>
                  ))}
                  <tr className="bg-bg font-semibold">
                    <td className="text-ink">TOTAL</td>
                    {(["nfse", "nfe", "cte"] as const).map((tipo) => (
                      <td key={tipo} className="text-right font-mono text-xs text-ink">
                        {numero(t.por_tipo[tipo]?.qtd ?? 0)}
                      </td>
                    ))}
                    <td className="text-right font-mono text-ink">{numero(t.documentos)}</td>
                    <td className="text-right font-mono text-ink">{moeda(t.valor)}</td>
                    <td className="text-right font-mono text-ink">{t.canceladas}</td>
                    <td className="text-right font-mono text-ink">{t.sem_xml}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            {fechamento.empresas.length === 0 && (
              <p className="py-8 text-center text-sm text-ink-muted">
                Nenhuma empresa cadastrada.{" "}
                <Link href="/dashboard/empresas" className="link">
                  Cadastrar →
                </Link>
              </p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
