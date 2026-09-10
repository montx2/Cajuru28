"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { bytesParaTexto } from "@/lib/competencia";
import type { InfoSistema, ResumoCertificado } from "@/lib/types";

export default function ConfiguracoesPage() {
  const [info, setInfo] = useState<InfoSistema | null>(null);
  const [certificados, setCertificados] = useState<ResumoCertificado[]>([]);
  const [saude, setSaude] = useState<{ problemas: string[]; disco_livre_bytes: number | null } | null>(null);

  const carregar = useCallback(() => {
    api.infoSistema().then(setInfo).catch(() => setInfo(null));
    api.resumoCertificados().then(setCertificados).catch(() => setCertificados([]));
    api.saudeDetalhada().then(setSaude).catch(() => setSaude(null));
  }, []);

  useEffect(() => {
    carregar();
    const intervalo = setInterval(carregar, 30_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  const vencidos = certificados.filter((item) => item.vencido);
  const vencendo = certificados.filter((item) => item.vence_em_breve && !item.vencido);

  return (
    <div className="max-w-5xl">
      <h1 className="text-2xl font-semibold text-ink">Configurações</h1>
      <p className="mt-1 text-sm text-ink-muted">Diagnóstico da implantação Docker e dos certificados.</p>

      <section className="mt-6 border border-line bg-surface p-6">
        <p className="font-medium text-ink">Estado dos serviços</p>
        <div className="mt-3 flex flex-wrap gap-6 text-sm text-ink-muted">
          <span>API: <strong className={saude?.problemas.length ? "text-danger" : "text-accent"}>{saude?.problemas.length ? "atenção" : "funcionando"}</strong></span>
          <span>Banco: <strong className="text-ink">{info?.banco ?? "verificando…"}</strong></span>
          <span>Fila: <strong className="text-ink">{info?.fila.modo ?? "verificando…"}</strong></span>
          {saude?.disco_livre_bytes != null && <span>Disco livre: <strong className="text-ink">{bytesParaTexto(saude.disco_livre_bytes)}</strong></span>}
        </div>
        {saude?.problemas.map((problema) => <p key={problema} className="mt-2 text-sm text-danger">{problema}</p>)}
        <p className="mt-4 text-xs text-ink-muted">Atualizações, logs e backups são administrados no servidor com Docker Compose. Proteja os volumes <code>db_data</code>, <code>certificados</code> e <code>xml_saida</code>.</p>
      </section>

      <section className="mt-6 border border-line bg-surface p-6">
        <p className="font-medium text-ink">Certificados digitais</p>
        <p className="mt-1 text-sm text-ink-muted">{certificados.filter((c) => c.tem_certificado).length} de {certificados.length} empresas com certificado A1.</p>
        {(vencidos.length > 0 || vencendo.length > 0) && <p className="mt-2 text-sm text-warn">Revise certificados vencidos ou próximos do vencimento.</p>}
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-line text-left text-ink-muted"><th className="py-2 font-normal">Empresa</th><th className="py-2 font-normal">Validade</th><th className="py-2 text-right font-normal">Situação</th></tr></thead>
            <tbody>{certificados.map((certificado) => (
              <tr key={certificado.empresa_id} className="border-b border-line last:border-0">
                <td className="py-2 text-ink">{certificado.razao_social}</td>
                <td className="py-2 font-mono text-xs text-ink-muted">{certificado.validade ? certificado.validade.split("-").reverse().join("/") : "—"}</td>
                <td className={`py-2 text-right ${certificado.vencido ? "text-danger" : certificado.vence_em_breve ? "text-warn" : "text-accent"}`}>{!certificado.tem_certificado ? "sem certificado" : certificado.vencido ? "vencido" : certificado.vence_em_breve ? `vence em ${certificado.dias_para_vencer} dias` : "válido"}</td>
              </tr>
            ))}</tbody>
          </table>
          {!certificados.length && <p className="py-4 text-sm text-ink-muted">Nenhuma empresa cadastrada.</p>}
        </div>
      </section>
    </div>
  );
}
