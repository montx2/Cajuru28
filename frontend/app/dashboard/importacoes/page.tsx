"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { StatusDot } from "@/components/StatusDot";
import type { ExecucaoImportacao } from "@/lib/types";

function formatarHora(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR");
}

export default function ImportacoesPage() {
  const searchParams = useSearchParams();
  const execucaoDestacada = searchParams.get("execucao");

  const [execucoes, setExecucoes] = useState<ExecucaoImportacao[]>([]);
  const [carregando, setCarregando] = useState(true);

  useEffect(() => {
    let ativo = true;

    async function carregar() {
      const dados = await api.listarExecucoes();
      if (ativo) {
        setExecucoes(dados);
        setCarregando(false);
      }
    }

    carregar();
    // Enquanto houver execução em andamento, atualiza sozinho a cada 4s —
    // evita ficar apertando F5 pra ver se já terminou.
    const intervalo = setInterval(carregar, 4000);
    return () => {
      ativo = false;
      clearInterval(intervalo);
    };
  }, []);

  return (
    <div>
      <p className="mb-6 font-serif text-2xl text-ink">Importações</p>

      {carregando ? (
        <p className="text-sm text-ink-muted">Carregando…</p>
      ) : execucoes.length === 0 ? (
        <div className="border border-line bg-surface p-8 text-center">
          <p className="text-sm text-ink-muted">
            Nenhuma importação disparada ainda. Vá em Empresas ou na Visão geral para começar.
          </p>
        </div>
      ) : (
        <table className="w-full border-t border-line text-sm">
          <thead>
            <tr className="border-b border-line text-left text-ink-muted">
              <th className="py-2 font-normal">Empresa</th>
              <th className="py-2 font-normal">Tipo</th>
              <th className="py-2 font-normal">Status</th>
              <th className="py-2 text-right font-normal">Notas</th>
              <th className="py-2 text-right font-normal">Início</th>
            </tr>
          </thead>
          <tbody>
            {execucoes.map((execucao) => (
              <tr
                key={execucao.id}
                className={`border-b border-line last:border-0 ${
                  String(execucao.id) === execucaoDestacada ? "bg-accent-soft" : ""
                }`}
              >
                <td className="py-3 text-ink">{execucao.empresa_razao_social ?? `#${execucao.empresa_id}`}</td>
                <td className="py-3 uppercase text-ink-muted">{execucao.tipo}</td>
                <td className="py-3">
                  <StatusDot status={execucao.status} />
                </td>
                <td className="py-3 text-right font-mono text-ink">{execucao.documentos_importados}</td>
                <td className="py-3 text-right text-ink-muted">{formatarHora(execucao.iniciado_em)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
