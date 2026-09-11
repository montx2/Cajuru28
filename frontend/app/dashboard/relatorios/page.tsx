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
import type { ConferenciaCompetencia, FechamentoMensal } from "@/lib/types";

/**
 * Fechamento mensal: o mapa contábil empresa × tipo do mês.
 * Imprimível (só o relatório sai no papel) e exportável em CSV e ZIP.
 */

const ROTULO_STATUS_CONFERENCIA: Record<string, string> = {
  ok: "Conferida",
  parcial: "Mês aberto",
  precisa_conferir: "Precisa varrer",
  pendente: "Pendente",
  aguardando: "Aguardando janela",
  rodando: "Rodando",
  sem_certificado: "Sem certificado",
  certificado_vencido: "Certificado vencido",
  sem_uf: "Sem UF",
  erro: "Erro",
  risco: "Risco",
};

function CardConferencia({
  conferencia,
  competencia,
}: {
  conferencia: ConferenciaCompetencia | null;
  competencia: string | null;
}) {
  if (!conferencia) return <Esqueleto className="mt-4 h-28" />;

  const pendencias = conferencia.itens.filter((item) => item.status !== "ok").slice(0, 6);
  const visual = conferencia.ok
    ? "border-accent/30 bg-accent-soft"
    : conferencia.status === "critico"
      ? "border-danger/30 bg-danger-soft"
      : "border-warn/30 bg-warn-soft";
  const icone = conferencia.ok ? "checkCirculo" : conferencia.status === "critico" ? "xCirculo" : "alerta";
  const corIcone = conferencia.ok ? "text-accent-deep" : conferencia.status === "critico" ? "text-danger" : "text-warn";

  return (
    <section className={`card mt-4 border p-5 ${visual}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 gap-3">
          <span className={`mt-0.5 inline-flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-surface ${corIcone}`}>
            <Icone nome={icone} className="h-5 w-5" />
          </span>
          <div className="min-w-0">
            <p className="font-serif text-lg font-semibold text-ink">
              {conferencia.ok ? "Competência pronta para fechar" : "Conferência da competência"}
            </p>
            <p className="mt-1 text-sm text-ink-muted">{conferencia.mensagem}</p>
            <p className="mt-2 text-xs text-ink-muted">
              {numero(conferencia.documentos)} documento(s) · {conferencia.itens_ok}/{conferencia.itens_total} fontes conferidas
              {conferencia.sem_xml_completo > 0 ? ` · ${conferencia.sem_xml_completo} XML(s) só em resumo` : ""}
            </p>
          </div>
        </div>
        <Link
          href={`/dashboard/importacoes${competencia ? `?competencia=${competencia}` : ""}`}
          className={conferencia.ok ? "btn-ghost btn-sm" : "btn-primary btn-sm"}
        >
          {conferencia.ok ? "Ver importações" : "Puxar / conferir agora"}
        </Link>
      </div>

      {pendencias.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-xs font-semibold text-ink-muted hover:text-ink">
            Ver pontos pendentes
          </summary>
          <ul className="mt-3 space-y-2">
            {pendencias.map((item) => (
              <li key={`${item.empresa_id}-${item.tipo}`} className="rounded-lg bg-surface px-3 py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-ink">{item.razao_social}</span>
                  <span className="badge-neutral">{ROTULO_STATUS_CONFERENCIA[item.status] ?? item.status}</span>
                  <span className="font-mono text-xs uppercase text-ink-faint">{item.tipo}</span>
                </div>
                <p className="mt-1 text-xs text-ink-muted">{item.mensagem}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export default function RelatoriosPage() {
  const toast = useToast();
  const [competencia, setCompetencia] = useState<string | null>(mesAtual());
  const [fechamento, setFechamento] = useState<FechamentoMensal | null>(null);
  const [conferencia, setConferencia] = useState<ConferenciaCompetencia | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [baixando, setBaixando] = useState(false);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const competenciaApi = paraAPI(competencia);
      const [fechamentoResposta, conferenciaResposta] = await Promise.all([
        api.fechamento(competenciaApi),
        api.conferirCompetencia({ competencia: competenciaApi }),
      ]);
      setFechamento(fechamentoResposta);
      setConferencia(conferenciaResposta);
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
          <h1 className="page-title">Fechamento mensal</h1>
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
              rotulo="Empresas"
              valor={`${t.empresas_com_documento}/${t.empresas_total}`}
              detalhe="com documento no mês"
              icone="empresa"
              tom={t.empresas_com_documento < t.empresas_total ? "alerta" : "ok"}
            />
            <KpiCard
              rotulo="XML completo"
              valor={numero(t.sem_xml)}
              detalhe={t.sem_xml > 0 ? "a completar" : "todos ok"}
              icone="relogio"
              tom={t.sem_xml > 0 ? "alerta" : "ok"}
              href="/dashboard/documentos"
            />
          </div>

          <CardConferencia conferencia={conferencia} competencia={competencia} />

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
