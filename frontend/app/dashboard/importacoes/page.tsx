"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { StatusDot } from "@/components/StatusDot";
import { CompetenciaPicker } from "@/components/CompetenciaPicker";
import { emQuanto, paraAPI, horaLocal } from "@/lib/competencia";
import {
  ROTULO_STATUS_LOTE,
  ROTULO_TIPO,
  TIPOS,
  type EstadoSincronizacao,
  type ExecucaoImportacao,
  type ItemImportacaoLote,
  type ResumoSincronizacao,
  type TipoDocumentoFiscal,
} from "@/lib/types";

type ResultadoLote = { tipo: string; itens: ItemImportacaoLote[] } | { tipo: string; erro: string };

function formatarHora(iso: string): string {
  return new Date(iso).toLocaleString("pt-BR");
}

function Ficha({ rotulo, valor, tom = "padrao" }: { rotulo: string; valor: string; tom?: "padrao" | "ok" | "espera" | "alerta" }) {
  const cor =
    tom === "ok" ? "text-accent" : tom === "espera" ? "text-warn" : tom === "alerta" ? "text-danger" : "text-ink";
  return (
    <div className="border border-line bg-surface px-4 py-3">
      <p className={`font-mono text-lg ${cor}`}>{valor}</p>
      <p className="text-xs text-ink-muted">{rotulo}</p>
    </div>
  );
}

export default function ImportacoesPage() {
  const searchParams = useSearchParams();
  const execucaoDestacada = searchParams.get("execucao");

  const [competencia, setCompetencia] = useState<string | null>(
    searchParams.get("competencia") || null
  );
  const [tipoLote, setTipoLote] = useState<TipoDocumentoFiscal | "todos">("todos");
  const [execucoes, setExecucoes] = useState<ExecucaoImportacao[]>([]);
  const [estados, setEstados] = useState<EstadoSincronizacao[]>([]);
  const [resumo, setResumo] = useState<ResumoSincronizacao | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [disparando, setDisparando] = useState(false);
  const [resultadoLote, setResultadoLote] = useState<ResultadoLote[] | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const agoraRef = useRef(Date.now());

  const carregar = useCallback(async () => {
    try {
      const [lista, estado, agregado] = await Promise.all([
        api.listarExecucoes(),
        api.estadoSincronizacao(),
        api.resumoSincronizacao(),
      ]);
      agoraRef.current = Date.now();
      setExecucoes(lista);
      setEstados(estado);
      setResumo(agregado);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    carregar();
    // Enquanto houver execução em andamento, atualiza sozinho — ninguém fica
    // apertando F5 para ver se já terminou.
    const intervalo = setInterval(carregar, 5000);
    const relogio = setInterval(() => setTick((n) => n + 1), 30_000);
    return () => {
      clearInterval(intervalo);
      clearInterval(relogio);
    };
  }, [carregar]);

  const tiposDoLote: TipoDocumentoFiscal[] = tipoLote === "todos" ? TIPOS : [tipoLote];

  async function sincronizarAgora(forcar = false) {
    setDisparando(true);
    setAviso(null);
    setResultadoLote(null);
    try {
      const respostaLote = (tipo: TipoDocumentoFiscal) =>
        api.solicitarImportacaoEmLote(tipo, { competencia: paraAPI(competencia), forcar });
      const respostas = await Promise.all(
        tiposDoLote.map(async (tipo) => {
          try {
            return { tipo, itens: await respostaLote(tipo) };
          } catch (e) {
            return { tipo, erro: e instanceof ApiError ? e.message : "falha inesperada" };
          }
        })
      );
      setResultadoLote(respostas);
      if (forcar) setAviso("Consulta forçada: a SEFAZ pode renovar o bloqueio de 1 hora de quem consultou fora da janela.");
      await carregar();
    } finally {
      setDisparando(false);
    }
  }

  async function puxarAgora(estado: EstadoSincronizacao) {
    setAviso(null);
    try {
      const execucao = await api.solicitarImportacao(estado.empresa_id, estado.tipo as TipoDocumentoFiscal, {
        competencia: paraAPI(competencia),
      });
      setAviso(`Enfileirado para ${estado.razao_social} (${ROTULO_TIPO[estado.tipo as TipoDocumentoFiscal]}) — execução #${execucao.id}.`);
      await carregar();
    } catch (e) {
      if (e instanceof ApiError && e.ehAguardo) {
        // É a janela de consumo: aviso neutro, não erro vermelho.
        setAviso(e.message);
      } else {
        setAviso(e instanceof ApiError ? e.message : "Não foi possível enfileirar agora.");
      }
    }
  }

  const estadosPorEmpresa = useMemo(() => {
    const mapa = new Map<number, EstadoSincronizacao[]>();
    for (const estado of estados) {
      const lista = mapa.get(estado.empresa_id) ?? [];
      lista.push(estado);
      mapa.set(estado.empresa_id, lista);
    }
    return [...mapa.entries()].sort((a, b) => a[1][0].razao_social.localeCompare(b[1][0].razao_social));
  }, [estados]);

  const aguardando = estados.filter((e) => (e.bloqueado_ate ?? e.proxima_consulta_em ?? null) !== null);
  void tick; // os contadores regressivos dependem deste tick

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-serif text-2xl text-ink">Importações</p>
          <p className="mt-1 text-sm text-ink-muted">
            {resumo?.sincronismo_automatico
              ? `O sistema consulta a SEFAZ sozinho a cada ${resumo.intervalo_minutos} min, em dia com a janela oficial de 1 hora.`
              : "Sincronismo automático desligado — dispare as consultas por aqui."}
          </p>
        </div>
        <Link
          href={`/dashboard/documentos${competencia ? `?competencia=${competencia}` : ""}`}
          className="border border-line px-3 py-2 text-sm text-accent hover:border-accent"
        >
          Baixar os XMLs de {competencia ? competencia.split("-").reverse().join("/") : "todos os períodos"} →
        </Link>
      </div>

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Ficha rotulo="no ponto (em dia)" valor={String(resumo?.em_dia ?? 0)} tom="ok" />
        <Ficha rotulo="com documento novo" valor={String(resumo?.com_pendencia ?? 0)} />
        <Ficha rotulo="varrendo agora" valor={String(resumo?.em_andamento ?? 0)} tom="espera" />
        <Ficha rotulo="na janela da SEFAZ" valor={String((resumo?.aguardando_janela ?? 0) + (resumo?.bloqueadas_sefaz ?? 0))} tom="espera" />
        <Ficha rotulo="documentos no banco" valor={String(resumo?.documentos_no_banco ?? 0)} />
      </div>

      <div className="mb-8 border border-line bg-surface p-5">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
          <div>
            <p className="mb-2 text-xs uppercase text-ink-muted">Competência</p>
            <CompetenciaPicker valor={competencia} aoMudar={setCompetencia} />
          </div>
          <div>
            <p className="mb-2 text-xs uppercase text-ink-muted">O que puxar</p>
            <select
              value={tipoLote}
              onChange={(e) => setTipoLote(e.target.value as TipoDocumentoFiscal | "todos")}
              className="border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            >
              <option value="todos">NFS-e + NFe + CT-e</option>
              {TIPOS.map((tipo) => (
                <option key={tipo} value={tipo}>
                  {ROTULO_TIPO[tipo]}
                </option>
              ))}
            </select>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={disparando}
              onClick={() => sincronizarAgora(false)}
              className="bg-accent px-4 py-2 text-sm text-white hover:opacity-90 disabled:opacity-50"
            >
              {disparando ? "Disparando…" : "Sincronizar todas agora"}
            </button>
            <button
              type="button"
              disabled={disparando}
              onClick={() => sincronizarAgora(true)}
              className="border border-line px-3 py-2 text-sm text-ink-muted hover:border-accent hover:text-ink disabled:opacity-50"
              title="Atravessa a janela de 1 hora da SEFAZ. Só se você tiver certeza — renovar o bloqueio atrasa todas as consultas."
            >
              Forçar
            </button>
          </div>
          <p className="max-w-sm text-xs text-ink-muted">
            A competência <span className="text-ink">não</span> limita o que é baixado — a SEFAZ só anda por
            NSU, então baixar tudo é o que garante que nenhuma nota se perca. O mês escolhe o que é
            contado e o que entra no ZIP.
          </p>
        </div>

        {aviso && (
          <p className="mt-4 border-l-2 border-warn bg-warn-soft px-3 py-2 text-sm text-ink">{aviso}</p>
        )}

        {resultadoLote && (
          <div className="mt-4 space-y-3">
            {resultadoLote.map((bloco) =>
              "erro" in bloco ? (
                <p key={bloco.tipo} className="text-sm text-danger">
                  {ROTULO_TIPO[bloco.tipo as TipoDocumentoFiscal]}: {bloco.erro}
                </p>
              ) : (
                <div key={bloco.tipo} className="text-sm">
                  <p className="mb-1 text-ink-muted">{ROTULO_TIPO[bloco.tipo as TipoDocumentoFiscal]}</p>
                  {bloco.itens.length === 0 ? (
                    <p className="text-ink-muted">Nenhuma empresa ativa para este tipo.</p>
                  ) : (
                    <ul className="space-y-1">
                      {bloco.itens.map((item) => (
                        <li key={`${item.empresa_id}-${item.status}`} className="flex flex-wrap items-baseline gap-2">
                          <span
                            className={
                              item.status === "enfileirada"
                                ? "text-accent"
                                : item.status === "sem_certificado" || item.status === "sem_uf" || item.status === "fila_indisponivel"
                                  ? "text-danger"
                                  : "text-warn"
                            }
                          >
                            {item.status === "enfileirada" ? "●" : "○"}
                          </span>
                          <span className="text-ink">{item.razao_social}</span>
                          <span className="text-xs text-ink-muted">
                            {ROTULO_STATUS_LOTE[item.status] ?? item.status}
                            {item.disponivel_em ? ` · retoma ${horaLocal(item.disponivel_em)}` : ""}
                          </span>
                          {item.mensagem ? (
                            <span className="w-full text-xs text-ink-muted sm:w-auto">{item.mensagem}</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            )}
          </div>
        )}
      </div>

      <section className="mb-10">
        <div className="mb-3 flex items-baseline justify-between">
          <p className="text-base font-medium text-ink">De onde cada empresa está</p>
          {aguardando.length === 0 && !carregando && (
            <p className="text-xs text-accent">Nada para fazer aqui — nenhuma consulta está atrasada.</p>
          )}
        </div>
        {carregando ? (
          <p className="text-sm text-ink-muted">Carregando…</p>
        ) : estadosPorEmpresa.length === 0 ? (
          <div className="border border-line bg-surface p-8 text-center">
            <p className="text-sm text-ink-muted">Cadastre uma empresa com certificado para começar.</p>
          </div>
        ) : (
          <div className="overflow-x-auto border-t border-line">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-ink-muted">
                  <th className="py-2 pr-3 font-normal">Empresa</th>
                  <th className="py-2 pr-3 font-normal">Tipo</th>
                  <th className="py-2 pr-3 text-right font-normal">Cursor (último NSU)</th>
                  <th className="py-2 pr-3 text-right font-normal">Faltando</th>
                  <th className="py-2 pr-3 font-normal">Situação</th>
                  <th className="py-2 text-right font-normal">Ação</th>
                </tr>
              </thead>
              <tbody>
                {estadosPorEmpresa.map(([empresaId, lista]) =>
                  lista.map((estado, indice) => (
                    <tr key={`${empresaId}-${estado.tipo}`} className="border-b border-line last:border-0">
                      {indice === 0 && (
                        <td rowSpan={lista.length} className="py-3 pr-3 align-top text-ink">
                          {estado.razao_social}
                          {!estado.sincronizar_automaticamente && (
                            <p className="text-xs text-warn">automático desligado</p>
                          )}
                        </td>
                      )}
                      <td className="py-3 pr-3 text-ink-muted">{ROTULO_TIPO[estado.tipo as TipoDocumentoFiscal] ?? estado.tipo}</td>
                      <td className="py-3 pr-3 text-right font-mono text-ink">
                        {Number(estado.ultimo_nsu).toLocaleString("pt-BR")}
                        {estado.max_nsu ? (
                          <span className="text-ink-muted"> / {Number(estado.max_nsu).toLocaleString("pt-BR")}</span>
                        ) : null}
                      </td>
                      <td className="py-3 pr-3 text-right font-mono text-ink-muted">
                        {estado.pendencia > 0 ? estado.pendencia : "–"}
                      </td>
                      <td className="py-3 pr-3">
                        {estado.em_andamento ? (
                          <span className="text-warn">varrendo…</span>
                        ) : estado.bloqueado_ate ? (
                          <span className="text-warn" title={estado.motivo_bloqueio ?? ""}>
                            bloqueada pela SEFAZ · tenta sozinha {horaLocal(estado.bloqueado_ate)}
                            {estado.bloqueios_seguidos > 1 ? ` (${estado.bloqueios_seguidos}ª vez)` : ""}
                          </span>
                        ) : estado.em_dia ? (
                          <span className="text-accent">em dia ✔</span>
                        ) : estado.proxima_consulta_em ? (
                          <span className="text-ink-muted">
                            espera {emQuanto(estado.proxima_consulta_em, agoraRef.current) ?? "acabando"}
                          </span>
                        ) : (
                          <span className="text-ink-muted">nunca consultado</span>
                        )}
                        {estado.risco_documento_fora_da_distribuicao && (
                          <p className="text-xs text-danger">
                            ⚠ {estado.dias_sem_varrer} dias sem varrer com documento faltando — a SEFAZ só
                            entrega os últimos ~3 meses, então o que passou pode já ter saído da
                            distribuição.
                          </p>
                        )}
                      </td>
                      <td className="py-3 text-right">
                        <button
                          type="button"
                          onClick={() => puxarAgora(estado)}
                          disabled={estado.em_andamento}
                          className="text-accent hover:underline disabled:text-ink-muted disabled:no-underline"
                        >
                          puxar agora
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
        {aguardando.length > 0 && (
          <p className="mt-2 text-xs text-ink-muted">
            “bloqueada pela SEFAZ” não é falha: é a janela oficial de 1 hora entre consultas do mesmo CNPJ.
            O sistema retoma sozinho na hora certa e você não precisa ficar clicando — clique antes da hora
            é o que zera o cronômetro do bloqueio.
          </p>
        )}
      </section>

      <section>
        <p className="mb-3 text-base font-medium text-ink">Execuções</p>
        {carregando ? (
          <p className="text-sm text-ink-muted">Carregando…</p>
        ) : execucoes.length === 0 ? (
          <div className="border border-line bg-surface p-8 text-center">
            <p className="text-sm text-ink-muted">
              Nenhuma importação disparada ainda. Use “Sincronizar todas agora” acima.
            </p>
          </div>
        ) : (
          <table className="w-full border-t border-line text-sm">
            <thead>
              <tr className="border-b border-line text-left text-ink-muted">
                <th className="py-2 font-normal">Empresa</th>
                <th className="py-2 font-normal">Tipo</th>
                <th className="py-2 font-normal">Status</th>
                <th className="py-2 font-normal">Período</th>
                <th className="py-2 text-right font-normal">Notas</th>
                <th className="py-2 text-right font-normal">Canceladas</th>
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
                    {execucao.tentativas ? (
                      <span className="ml-2 text-xs text-ink-muted">tentativa {execucao.tentativas}</span>
                    ) : null}
                    {execucao.status === "erro" && execucao.mensagem_erro && (
                      <p className="mt-1 max-w-md text-xs text-danger" title={execucao.mensagem_erro}>
                        {execucao.mensagem_erro.length > 160
                          ? `${execucao.mensagem_erro.slice(0, 160)}…`
                          : execucao.mensagem_erro}
                      </p>
                    )}
                    {execucao.status === "aguardando" && (execucao.mensagem_erro || execucao.bloqueado_ate) && (
                      <p className="mt-1 max-w-md text-xs text-warn" title={execucao.mensagem_erro ?? ""}>
                        {execucao.mensagem_erro?.length
                          ? execucao.mensagem_erro.slice(0, 200)
                          : `retoma ${horaLocal(execucao.bloqueado_ate)}`}
                      </p>
                    )}
                    {execucao.aviso && (
                      <p className="mt-1 max-w-md text-xs text-ink-muted" title={execucao.aviso}>
                        {execucao.aviso.split("\n")[0]}
                      </p>
                    )}
                  </td>
                  <td className="py-3 font-mono text-xs text-ink-muted">
                    {execucao.data_inicio
                      ? `${execucao.data_inicio.split("-").reverse().join("/")}–${(execucao.data_fim ?? "").split("-").reverse().join("/")}`
                      : "todos"}
                  </td>
                  <td className="py-3 text-right font-mono text-ink">{execucao.documentos_importados}</td>
                  <td className="py-3 text-right font-mono text-ink">
                    {execucao.documentos_cancelados > 0 ? (
                      <span className="text-danger">{execucao.documentos_cancelados}</span>
                    ) : (
                      <span className="text-ink-muted">–</span>
                    )}
                  </td>
                  <td className="py-3 text-right text-ink-muted" title={formatarHora(execucao.iniciado_em)}>
                    {horaLocal(execucao.iniciado_em)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
