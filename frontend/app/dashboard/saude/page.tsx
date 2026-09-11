"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { dataHora, numero, tempoRelativo } from "@/lib/format";
import type { BackupsResposta, PainelOperacional } from "@/lib/types";
import { Icone } from "@/components/icons";
import { useToast } from "@/components/Toast";
import { Esqueleto, EstadoVazio, TituloSecao } from "@/components/ui";

const ROTULO_COMPONENTE: Record<string, string> = {
  api: "API",
  banco: "Banco de dados",
  fila: "Fila (Redis)",
  worker: "Worker de importação",
  agendador: "Agendador (beat)",
};

function SeloComponente({ status }: { status: string }) {
  const mapa: Record<string, { classe: string; icone: string; rotulo: string }> = {
    ok: { classe: "badge-ok", icone: "checkCirculo", rotulo: "OK" },
    atencao: { classe: "badge-warn", icone: "alerta", rotulo: "Atenção" },
    erro: { classe: "badge-danger", icone: "xCirculo", rotulo: "Problema" },
    desconhecido: { classe: "badge-neutral", icone: "info", rotulo: "Sem sinal" },
    desligado: { classe: "badge-neutral", icone: "relogio", rotulo: "Desligado" },
  };
  const v = mapa[status] ?? mapa.desconhecido;
  return (
    <span className={v.classe}>
      <Icone nome={v.icone} className="h-3.5 w-3.5" /> {v.rotulo}
    </span>
  );
}

function bytesLegiveis(valor: number | null | undefined): string {
  if (!valor) return "—";
  const unidades = ["B", "KB", "MB", "GB", "TB"];
  let v = valor;
  let i = 0;
  while (v >= 1024 && i < unidades.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toLocaleString("pt-BR", { maximumFractionDigits: 1 })} ${unidades[i]}`;
}

/**
 * Saúde do sistema — a tela onde o operador confia (ou não) na máquina.
 *
 * Dois blocos: os componentes de fundo (alguém está trabalhando?) e a
 * saúde do backup (se o disco morrer amanhã, quanto se perde?). O teste de
 * restauração é o botão mais importante daqui — backup sem teste é esperança.
 */
export default function SaudePage() {
  const toast = useToast();
  const [painel, setPainel] = useState<PainelOperacional | null>(null);
  const [backups, setBackups] = useState<BackupsResposta | null>(null);
  const [diagnostico, setDiagnostico] = useState<{
    ok: boolean;
    problemas: string[];
    disco_livre_bytes: number | null;
  } | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [executando, setExecutando] = useState(false);
  const [testando, setTestando] = useState<number | null>(null);

  const carregar = useCallback(
    async (silencioso = false) => {
      if (!silencioso) setCarregando(true);
      try {
        const [p, b, d] = await Promise.all([
          api.painelOperacional(),
          api.backups(),
          api.saudeDetalhada().catch(() => null),
        ]);
        setPainel(p);
        setBackups(b);
        if (d) setDiagnostico(d);
      } catch {
        if (!silencioso) toast.erro("Não foi possível carregar a saúde do sistema.");
      } finally {
        setCarregando(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    carregar();
    const intervalo = setInterval(() => carregar(true), 60_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  async function executarBackup() {
    setExecutando(true);
    try {
      await api.executarBackup();
      toast.sucesso("Backup disparado em plano de fundo — acompanhe o resultado abaixo.");
      setTimeout(() => carregar(true), 4000);
    } catch (e) {
      toast.erro(e instanceof Error ? e.message : "Falha ao disparar backup.");
    } finally {
      setExecutando(false);
    }
  }

  async function testarRestauracao(id: number) {
    setTestando(id);
    try {
      const r = await api.testarBackup(id);
      if (r.ok) toast.sucesso(r.detalhe);
      else toast.erro(r.detalhe);
      carregar(true);
    } catch (e) {
      toast.erro(e instanceof Error ? e.message : "Falha no teste.");
    } finally {
      setTestando(null);
    }
  }

  if (carregando && !painel) {
    return (
      <div className="space-y-4">
        <Esqueleto className="h-10 w-72" />
        <Esqueleto className="h-48" />
        <Esqueleto className="h-64" />
      </div>
    );
  }

  const saude = backups?.saude;

  return (
    <div className="animate-fade-up space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-serif text-3xl font-semibold text-ink">Saúde do sistema</h1>
          <p className="mt-1 text-sm text-ink-muted">
            A máquina trabalhando sozinha só é boa se você puder confiar nela.
          </p>
        </div>
        <button type="button" onClick={() => carregar()} className="btn-ghost btn-sm">
          <Icone nome="atualizar" className="h-4 w-4" /> Atualizar
        </button>
      </div>

      {/* ---- componentes ---- */}
      <section>
        <TituloSecao
          titulo="Componentes"
          subtitulo="Quem mantém a automação de pé"
          acao={
            <Link href="/dashboard/execucoes" className="link text-xs font-semibold">
              ver execuções →
            </Link>
          }
        />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {(painel?.componentes ?? []).map((c) => (
            <div key={c.nome} className="card card-pad">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-semibold text-ink">{ROTULO_COMPONENTE[c.nome] ?? c.nome}</p>
                <SeloComponente status={c.status} />
              </div>
              <p className="mt-2 text-xs leading-relaxed text-ink-muted">{c.detalhe}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ---- diagnóstico do volume ---- */}
      {diagnostico && (
        <section>
          <TituloSecao titulo="Diagnóstico do ambiente" />
          {diagnostico.ok ? (
            <div className="card card-pad flex items-center gap-3">
              <Icone nome="checkCirculo" className="h-6 w-6 flex-none text-accent" />
              <p className="text-sm text-ink">
                Banco, cofre de senhas e volume de dados saudáveis
                {diagnostico.disco_livre_bytes !== null && (
                  <> · {bytesLegiveis(diagnostico.disco_livre_bytes)} livres em disco</>
                )}
                .
              </p>
            </div>
          ) : (
            <ul className="space-y-2">
              {diagnostico.problemas.map((p, i) => (
                <li key={i} className="card card-pad flex items-start gap-3 border-l-4 border-l-danger">
                  <Icone nome="alerta" className="mt-0.5 h-5 w-5 flex-none text-danger" />
                  <p className="text-sm text-ink">{p}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* ---- backup ---- */}
      <section>
        <TituloSecao
          titulo="Saúde do backup"
          subtitulo="Banco + manifesto + espelho de XMLs, com teste de restauração"
          acao={
            <button
              type="button"
              onClick={executarBackup}
              disabled={executando || !saude?.ativo}
              className="btn-primary btn-sm"
            >
              <Icone nome="hd" className="h-4 w-4" />
              {executando ? "Disparando…" : "Executar agora"}
            </button>
          }
        />
        {!saude ? (
          <Esqueleto className="h-32" />
        ) : !saude.ativo ? (
          <EstadoVazio
            icone="hd"
            titulo="Backup desativado"
            texto="Ative o BACKUP_ATIVO no ambiente para o agendamento diário funcionar."
          />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="card card-pad">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  Último backup
                </p>
                {saude.ultimo_ok_em ? (
                  <>
                    <p className="mt-1 font-serif text-xl font-semibold text-accent">✓ {tempoRelativo(saude.ultimo_ok_em)}</p>
                    <p className="mt-0.5 text-xs text-ink-faint">
                      {dataHora(saude.ultimo_ok_em)} · {bytesLegiveis(saude.ultimo_ok_tamanho_bytes)}
                    </p>
                  </>
                ) : (
                  <>
                    <p className="mt-1 font-serif text-xl font-semibold text-warn">Nunca</p>
                    <p className="mt-0.5 text-xs text-ink-faint">dispare o primeiro agora</p>
                  </>
                )}
              </div>
              <div className="card card-pad">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  Próximo backup
                </p>
                <p className="mt-1 font-serif text-xl font-semibold text-ink">
                  {saude.proximo_previsto_em ? dataHora(saude.proximo_previsto_em) : "—"}
                </p>
                <p className="mt-0.5 text-xs text-ink-faint">
                  agendado diariamente · retenção de {saude.retencao} pacotes
                </p>
              </div>
              <div className="card card-pad">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  Último teste de restauração
                </p>
                {saude.ultimo_teste_em ? (
                  <>
                    <p className={`mt-1 font-serif text-xl font-semibold ${saude.ultimo_teste_ok ? "text-accent" : "text-danger"}`}>
                      {saude.ultimo_teste_ok ? "✓ Passou" : "✗ Falhou"}
                    </p>
                    <p className="mt-0.5 text-xs text-ink-faint">{dataHora(saude.ultimo_teste_em)}</p>
                  </>
                ) : (
                  <>
                    <p className="mt-1 font-serif text-xl font-semibold text-ink-muted">Nunca testado</p>
                    <p className="mt-0.5 text-xs text-ink-faint">use o botão ao lado de um backup</p>
                  </>
                )}
              </div>
              <div className={`card card-pad ${saude.atrasado ? "border-l-4 border-l-danger" : ""}`}>
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  Situação
                </p>
                <p className={`mt-1 font-serif text-xl font-semibold ${saude.atrasado ? "text-danger" : "text-accent"}`}>
                  {saude.atrasado ? "Atrasado" : "Em dia"}
                </p>
                <p className="mt-0.5 text-xs text-ink-faint">
                  espelho de XMLs: {bytesLegiveis(saude.tamanho_total_bytes)}
                </p>
              </div>
            </div>

            {backups && backups.registros.length > 0 && (
              <div className="card mt-3 overflow-x-auto">
                <table className="tabela">
                  <thead>
                    <tr>
                      <th>Quando</th>
                      <th>Origem</th>
                      <th>Status</th>
                      <th className="text-right">Tamanho</th>
                      <th className="text-right">Conteúdo</th>
                      <th className="text-right">Restauração</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {backups.registros.map((b) => (
                      <tr key={b.id}>
                        <td className="whitespace-nowrap" title={dataHora(b.iniciado_em)}>
                          {tempoRelativo(b.iniciado_em)}
                        </td>
                        <td className="text-xs text-ink-muted">{b.tipo}</td>
                        <td>
                          {b.status === "ok" ? (
                            <span className="badge-ok">ok</span>
                          ) : b.status === "erro" ? (
                            <span className="badge-danger" title={b.erro ?? ""}>
                              erro
                            </span>
                          ) : (
                            <span className="badge-info">em andamento</span>
                          )}
                        </td>
                        <td className="text-right font-mono text-xs">{bytesLegiveis(b.tamanho_bytes)}</td>
                        <td className="text-right font-mono text-xs">
                          {numero(b.documentos)} docs · {numero(b.empresas)} empr.
                        </td>
                        <td className="text-right text-xs">
                          {b.restauracao_testada_em ? (
                            <span className={b.restauracao_ok ? "text-accent" : "text-danger"}>
                              {b.restauracao_ok ? "testado ✓" : "falhou ✗"}{" "}
                              <span className="text-ink-faint">({tempoRelativo(b.restauracao_testada_em)})</span>
                            </span>
                          ) : (
                            <span className="text-ink-faint">—</span>
                          )}
                        </td>
                        <td className="text-right">
                          {b.status === "ok" && (
                            <button
                              type="button"
                              onClick={() => testarRestauracao(b.id)}
                              disabled={testando === b.id}
                              className="btn-ghost btn-sm"
                            >
                              <Icone nome="escudo" className="h-4 w-4" />
                              {testando === b.id ? "Testando…" : "Testar"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="mt-3 text-xs text-ink-faint">
              O teste de restauração extrai o pacote, recria o schema num banco de
              prova, recarrega os registros e confere as contagens — é o "isto aqui
              volta" comprovado, não presumido.
            </p>
          </>
        )}
      </section>
    </div>
  );
}
