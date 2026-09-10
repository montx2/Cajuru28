"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { usePapel } from "@/lib/papel";
import { dataHora } from "@/lib/format";
import { ROTULO_ACAO, type RegistroAuditoria } from "@/lib/types";
import { Icone } from "@/components/icons";
import { Esqueleto, EstadoVazio, TituloSecao } from "@/components/ui";

/**
 * Trilha de auditoria: quem fez o quê, quando.
 * "Quem baixou o ZIP de agosto?" — a resposta mora aqui.
 */
export default function AuditoriaPage() {
  const { podeOperar } = usePapel();
  const [registros, setRegistros] = useState<RegistroAuditoria[]>([]);
  const [acoes, setAcoes] = useState<string[]>([]);
  const [acao, setAcao] = useState("");
  const [busca, setBusca] = useState("");
  const [termo, setTermo] = useState("");
  const [carregando, setCarregando] = useState(true);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      const [lista, distintas] = await Promise.all([
        api.auditoria({ acao: acao || undefined, busca: termo || undefined, limite: 200 }),
        api.acoesAuditoria(),
      ]);
      setRegistros(lista);
      setAcoes(distintas);
    } catch {
      setRegistros([]);
    } finally {
      setCarregando(false);
    }
  }, [acao, termo]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  if (!podeOperar) {
    return (
      <EstadoVazio
        icone="escudo"
        titulo="Acesso restrito"
        texto="A trilha de auditoria é visível para administradores e operadores."
      />
    );
  }

  return (
    <div className="animate-fade-up max-w-5xl">
      <div className="mb-6">
        <h1 className="font-serif text-3xl font-semibold text-ink">Auditoria</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Cada login, cadastro, disparo e download — com nome, hora e detalhe.
        </p>
      </div>

      <div className="card-pad mb-4 flex flex-wrap items-end gap-3">
        <div>
          <p className="label">Ação</p>
          <select value={acao} onChange={(e) => setAcao(e.target.value)} className="input">
            <option value="">Todas as ações</option>
            {acoes.map((a) => (
              <option key={a} value={a}>
                {ROTULO_ACAO[a] ?? a}
              </option>
            ))}
          </select>
        </div>
        <div className="min-w-52 flex-1">
          <p className="label">Busca</p>
          <div className="flex gap-2">
            <input
              value={busca}
              onChange={(e) => setBusca(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && setTermo(busca.trim())}
              placeholder="email, entidade ou detalhe…"
              className="input"
            />
            <button type="button" onClick={() => setTermo(busca.trim())} className="btn-ghost btn-sm">
              <Icone nome="busca" className="h-4 w-4" />
            </button>
          </div>
        </div>
        <button type="button" onClick={carregar} className="btn-ghost btn-sm" title="Atualizar">
          <Icone nome="atualizar" className="h-4 w-4" />
        </button>
      </div>

      {carregando ? (
        <div className="space-y-3">
          <Esqueleto className="h-16" />
          <Esqueleto className="h-16" />
          <Esqueleto className="h-16" />
        </div>
      ) : registros.length === 0 ? (
        <EstadoVazio
          icone="olho"
          titulo="Nada por aqui"
          texto="Nenhum registro para este filtro. As ações da equipe aparecem aqui automaticamente."
        />
      ) : (
        <section className="card-pad">
          <TituloSecao titulo={`${registros.length} registro(s)`} subtitulo="Do mais recente ao mais antigo" />
          <div className="overflow-x-auto">
            <table className="tabela">
              <thead>
                <tr>
                  <th>Quando</th>
                  <th>Quem</th>
                  <th>Ação</th>
                  <th>Detalhe</th>
                </tr>
              </thead>
              <tbody>
                {registros.map((r) => (
                  <tr key={r.id}>
                    <td className="whitespace-nowrap font-mono text-xs text-ink-muted">
                      {dataHora(r.quando)}
                    </td>
                    <td className="max-w-48 truncate text-ink" title={r.usuario_email}>
                      {r.usuario_email || "—"}
                    </td>
                    <td>
                      <span className="badge-neutral">{ROTULO_ACAO[r.acao] ?? r.acao}</span>
                      {r.entidade && (
                        <span className="ml-1 font-mono text-[11px] text-ink-faint">
                          {r.entidade}
                          {r.entidade_id ? `#${r.entidade_id}` : ""}
                        </span>
                      )}
                    </td>
                    <td className="max-w-md truncate text-xs text-ink-muted" title={r.detalhe ?? ""}>
                      {r.detalhe ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
