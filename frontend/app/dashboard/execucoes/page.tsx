"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { dataHora, numero, tempoRelativo } from "@/lib/format";
import type { CentralExecucoes, TipoDocumentoFiscal } from "@/lib/types";
import { Icone } from "@/components/icons";
import { useToast } from "@/components/Toast";
import { Esqueleto, EstadoVazio, TituloSecao } from "@/components/ui";

const ROTULO_TIPO: Record<string, string> = { nfse: "NFS-e", nfe: "NFe", cte: "CT-e" };

function SeloStatus({ status }: { status: string }) {
  const mapa: Record<string, string> = {
    em_andamento: "badge-info",
    aguardando: "badge-warn",
    concluida: "badge-ok",
    erro: "badge-danger",
  };
  const rotulo: Record<string, string> = {
    em_andamento: "Em andamento",
    aguardando: "Aguardando janela",
    concluida: "Concluída",
    erro: "Erro",
  };
  return <span className={mapa[status] ?? "badge-info"}>{rotulo[status] ?? status}</span>;
}

/**
 * Execuções — a central do que o sistema está fazendo.
 *
 * Progressive disclosure na prática: o resumo primeiro (empresa, o que
 * está acontecendo, quanto já coletou); o detalhe técnico (NSU, avisos,
 * motivo exato da espera) só quando o operador pedir, expandindo a linha.
 */
export default function ExecucoesPage() {
  const toast = useToast();
  const [dados, setDados] = useState<CentralExecucoes | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [expandida, setExpandida] = useState<number | null>(null);
  const [reprocessando, setReprocessando] = useState<number | null>(null);

  const carregar = useCallback(
    async (silencioso = false) => {
      if (!silencioso) setCarregando(true);
      try {
        setDados(await api.centralExecucoes(30));
      } catch {
        if (!silencioso) toast.erro("Não foi possível carregar as execuções.");
      } finally {
        setCarregando(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    carregar();
    const intervalo = setInterval(() => carregar(true), 15_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  async function reprocessar(empresaId: number, tipo: string) {
    setReprocessando(empresaId);
    try {
      await api.solicitarImportacao(empresaId, tipo as TipoDocumentoFiscal);
      toast.sucesso("Varredura reenfileirada — a fila cuida do resto.");
      carregar(true);
    } catch (e) {
      toast.erro(e instanceof Error ? e.message : "Falha ao reenfileirar.");
    } finally {
      setReprocessando(null);
    }
  }

  if (carregando && !dados) {
    return (
      <div className="space-y-4">
        <Esqueleto className="h-10 w-64" />
        <Esqueleto className="h-40" />
        <Esqueleto className="h-64" />
      </div>
    );
  }
  if (!dados) return null;

  return (
    <div className="animate-fade-up space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-serif text-3xl font-semibold text-ink">Execuções</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Tudo que o sistema está fazendo — resumo primeiro, detalhe técnico por clique.
          </p>
        </div>
        <div className="flex items-center gap-3 text-xs text-ink-faint">
          <span className="pulso-andamento inline-block h-1.5 w-1.5 rounded-full bg-accent-bright" />
          atualiza a cada 15 s
        </div>
      </div>

      {/* ---- Agora ---- */}
      <section>
        <TituloSecao
          titulo="Agora"
          subtitulo={
            dados.agora.length
              ? `${dados.agora.length} varredura(s) em curso ou esperando janela`
              : undefined
          }
        />
        {dados.agora.length === 0 ? (
          <EstadoVazio
            icone="atividade"
            titulo="Nada rodando neste instante"
            texto="O agendador dispara cada empresa na sua janela oficial de consumo. As próximas estão listadas abaixo."
          />
        ) : (
          <ul className="grid gap-3 lg:grid-cols-2">
            {dados.agora.map((e) => {
              const aberta = expandida === e.execucao_id;
              return (
                <li key={e.execucao_id} className="card card-pad">
                  <button
                    type="button"
                    onClick={() => setExpandida(aberta ? null : e.execucao_id)}
                    className="flex w-full items-start gap-3 text-left"
                  >
                    <span
                      className={`inline-block h-2.5 w-2.5 flex-none rounded-full ${
                        e.status === "em_andamento" ? "pulso-andamento bg-info" : "bg-warn"
                      } mt-1.5`}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <Link
                          href={`/dashboard/empresa?id=${e.empresa_id}`}
                          className="truncate text-sm font-semibold text-ink hover:underline"
                        >
                          {e.razao_social}
                        </Link>
                        <span className="badge-info">{ROTULO_TIPO[e.tipo] ?? e.tipo}</span>
                        <SeloStatus status={e.status} />
                      </span>
                      <span className="mt-1 block text-sm text-ink-muted">
                        {e.status === "em_andamento" ? (
                          <>
                            Consultando a fonte fiscal · <strong>{numero(e.documentos_importados)}</strong>{" "}
                            documento(s) · desde {tempoRelativo(e.iniciado_em)}
                          </>
                        ) : (
                          <>
                            Aguardando janela oficial
                            {e.aguardando_ate ? ` · retoma ${tempoRelativo(e.aguardando_ate)}` : ""}
                          </>
                        )}
                      </span>
                    </span>
                    <Icone
                      nome={aberta ? "chevronBaixo" : "chevronDireita"}
                      className="h-4 w-4 flex-none text-ink-faint"
                    />
                  </button>

                  {aberta && (
                    <div className="mt-3 space-y-1.5 border-t border-line pt-3 font-mono text-xs text-ink-muted">
                      <p>execução #{e.execucao_id}</p>
                      {e.ultimo_nsu && <p>último NSU: {e.ultimo_nsu}</p>}
                      {e.iniciado_em && <p>início: {dataHora(e.iniciado_em)}</p>}
                      {e.aguardando_ate && <p>retoma em: {dataHora(e.aguardando_ate)}</p>}
                      {e.motivo_espera && <p className="whitespace-pre-wrap">{e.motivo_espera}</p>}
                      {e.mensagem_erro && <p className="text-danger">{e.mensagem_erro}</p>}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* ---- Próximas janelas ---- */}
      {dados.proximas.length > 0 && (
        <section>
          <TituloSecao
            titulo="Próximas janelas"
            subtitulo="Quem volta a ser consultado e quando — a fila se organiza sozinha"
          />
          <div className="card overflow-x-auto">
            <table className="tabela">
              <thead>
                <tr>
                  <th>Empresa</th>
                  <th>Tipo</th>
                  <th>Motivo</th>
                  <th>Pendência</th>
                  <th className="text-right">Consulta em</th>
                </tr>
              </thead>
              <tbody>
                {dados.proximas.map((p) => (
                  <tr key={`${p.empresa_id}-${p.tipo}`}>
                    <td className="max-w-64 truncate">
                      <Link href={`/dashboard/empresa?id=${p.empresa_id}`} className="hover:underline">
                        {p.razao_social}
                      </Link>
                    </td>
                    <td>{ROTULO_TIPO[p.tipo] ?? p.tipo}</td>
                    <td>
                      {p.bloqueada ? (
                        <span className="badge-warn">Bloqueio SEFAZ (656)</span>
                      ) : (
                        <span className="badge-info">Janela de 1 h</span>
                      )}
                    </td>
                    <td className="font-mono">
                      {p.pendencia > 0 ? numero(p.pendencia) : "—"}
                    </td>
                    <td className="text-right font-mono" title={dataHora(p.proxima_consulta_em)}>
                      {tempoRelativo(p.proxima_consulta_em)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ---- Erros ---- */}
      {dados.erros.length > 0 && (
        <section>
          <TituloSecao
            titulo="Falhas recentes"
            subtitulo="Itens isolados — uma falha nunca parou as outras 9.999"
          />
          <div className="card overflow-x-auto">
            <table className="tabela">
              <thead>
                <tr>
                  <th>Empresa</th>
                  <th>Tipo</th>
                  <th>Motivo</th>
                  <th className="text-right">Quando</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {dados.erros.map((e) => (
                  <tr key={e.id}>
                    <td className="max-w-56 truncate">
                      <Link href={`/dashboard/empresa?id=${e.empresa_id}`} className="hover:underline">
                        {e.empresa_razao_social}
                      </Link>
                    </td>
                    <td>{ROTULO_TIPO[e.tipo] ?? e.tipo}</td>
                    <td className="max-w-96">
                      <span className="line-clamp-1 text-danger" title={e.mensagem_erro ?? ""}>
                        {e.mensagem_erro ?? "—"}
                      </span>
                    </td>
                    <td className="text-right font-mono" title={dataHora(e.iniciado_em)}>
                      {tempoRelativo(e.iniciado_em)}
                    </td>
                    <td className="text-right">
                      <button
                        type="button"
                        onClick={() => reprocessar(e.empresa_id, e.tipo)}
                        disabled={reprocessando === e.empresa_id}
                        className="btn-ghost btn-sm"
                      >
                        <Icone nome="atualizar" className="h-4 w-4" />
                        Reprocessar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ---- Recentes ---- */}
      <section>
        <TituloSecao titulo="Histórico recente" subtitulo="Últimas varreduras concluídas" />
        {dados.recentes.length === 0 ? (
          <EstadoVazio
            icone="importacao"
            titulo="Sem histórico ainda"
            texto="Assim que a primeira varredura terminar, ela aparece aqui com tudo que coletou."
          />
        ) : (
          <div className="card overflow-x-auto">
            <table className="tabela">
              <thead>
                <tr>
                  <th>Empresa</th>
                  <th>Tipo</th>
                  <th>Status</th>
                  <th className="text-right">Documentos</th>
                  <th className="text-right">Cancelados</th>
                  <th className="text-right">Finalizada</th>
                </tr>
              </thead>
              <tbody>
                {dados.recentes.map((e) => (
                  <tr key={e.id}>
                    <td className="max-w-64 truncate">
                      <Link href={`/dashboard/empresa?id=${e.empresa_id}`} className="hover:underline">
                        {e.empresa_razao_social}
                      </Link>
                    </td>
                    <td>{ROTULO_TIPO[e.tipo] ?? e.tipo}</td>
                    <td>
                      <SeloStatus status={e.status} />
                    </td>
                    <td className="text-right font-mono">{numero(e.documentos_importados)}</td>
                    <td className="text-right font-mono">{numero(e.documentos_cancelados)}</td>
                    <td className="text-right font-mono" title={dataHora(e.finalizado_em)}>
                      {tempoRelativo(e.finalizado_em)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
