"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Icone } from "@/components/icons";
import { Esqueleto, EstadoVazio, SeloNivel, TituloSecao } from "@/components/ui";
import { ROTULO_CATEGORIA_ALERTA, type AlertasResposta, type NivelAlerta } from "@/lib/types";

const CHAVE_LIDAS = "notasflow_alertas_lidas";

function lerLidas(): Set<string> {
  try {
    const bruto = window.localStorage.getItem(CHAVE_LIDAS);
    const lista = bruto ? JSON.parse(bruto) : [];
    return new Set(Array.isArray(lista) ? lista : []);
  } catch {
    return new Set();
  }
}

type Filtro = "todas" | NivelAlerta;

const FILTROS: { id: Filtro; rotulo: string }[] = [
  { id: "todas", rotulo: "Todas" },
  { id: "critico", rotulo: "Críticos" },
  { id: "atencao", rotulo: "Atenção" },
  { id: "info", rotulo: "Info" },
];

/**
 * Central de alertas: tudo que precisa de olho humano.
 * "Marcar como lida" só esconde aqui no navegador — se o problema persistir,
 * o alerta continua existindo (e volta a aparecer numa nova leitura geral).
 */
export default function AlertasPage() {
  const [dados, setDados] = useState<AlertasResposta | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [filtro, setFiltro] = useState<Filtro>("todas");
  const [lidas, setLidas] = useState<Set<string>>(new Set());
  const [mostrarLidas, setMostrarLidas] = useState(false);

  useEffect(() => {
    setLidas(lerLidas());
  }, []);

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      setDados(await api.alertas());
    } catch {
      setDados(null);
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    carregar();
    const intervalo = setInterval(carregar, 60_000);
    return () => clearInterval(intervalo);
  }, [carregar]);

  function salvarLidas(novo: Set<string>) {
    setLidas(novo);
    try {
      window.localStorage.setItem(CHAVE_LIDAS, JSON.stringify([...novo].slice(-200)));
    } catch {}
  }

  function marcarComoLida(id: string) {
    const novo = new Set(lidas);
    novo.add(id);
    salvarLidas(novo);
  }

  function marcarTodas() {
    salvarLidas(new Set([...lidas, ...(dados?.itens.map((a) => a.id) ?? [])]));
  }

  const visiveis = useMemo(() => {
    const itens = dados?.itens ?? [];
    return itens.filter((a) => {
      if (!mostrarLidas && lidas.has(a.id)) return false;
      if (filtro !== "todas" && a.nivel !== filtro) return false;
      return true;
    });
  }, [dados, filtro, lidas, mostrarLidas]);

  const contagem = (f: Filtro) =>
    (dados?.itens ?? []).filter((a) => (f === "todas" ? true : a.nivel === f)).length;

  return (
    <div className="animate-fade-up max-w-4xl">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-serif text-3xl font-semibold text-ink">Central de alertas</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {dados ? (
              <>
                <span className="font-semibold text-danger">{dados.criticos} crítico(s)</span>
                {" · "}
                <span className="font-semibold text-warn">{dados.atencao} atenção</span>
                {" · "}
                <span>{dados.infos} informativo(s)</span>
              </>
            ) : (
              "Lendo o estado do sistema…"
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => setMostrarLidas((v) => !v)}
            className="btn-ghost btn-sm"
          >
            {mostrarLidas ? "Ocultar lidas" : "Mostrar lidas"}
          </button>
          <button type="button" onClick={marcarTodas} className="btn-ghost btn-sm">
            <Icone nome="check" className="h-4 w-4" /> Marcar todas como lidas
          </button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {FILTROS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFiltro(f.id)}
            className={
              filtro === f.id
                ? "rounded-pill bg-ink px-4 py-1.5 text-sm font-semibold text-white"
                : "rounded-pill border border-line bg-surface px-4 py-1.5 text-sm text-ink-muted hover:border-accent hover:text-ink"
            }
          >
            {f.rotulo} ({contagem(f.id)})
          </button>
        ))}
      </div>

      {carregando && !dados ? (
        <div className="space-y-3">
          <Esqueleto className="h-24" />
          <Esqueleto className="h-24" />
          <Esqueleto className="h-24" />
        </div>
      ) : visiveis.length === 0 ? (
        <EstadoVazio
          icone="checkCirculo"
          titulo={dados?.total ? "Tudo lido. Nada pendente. ✨" : "Nenhum alerta — tudo sob controle ✨"}
          texto={
            dados?.total
              ? "Os alertas marcados como lidos ficam ocultos. Eles continuam existindo enquanto o motivo persistir."
              : "Certificados válidos, SEFAZ em dia, disco saudável. Volte ao trabalho tranquilo."
          }
          acao={
            <Link href="/dashboard" className="btn-primary btn-sm">
              Voltar à visão geral
            </Link>
          }
        />
      ) : (
        <ul className="space-y-3">
          {visiveis.map((a) => (
            <li
              key={a.id}
              className={`card-pad border-l-4 ${
                a.nivel === "critico"
                  ? "border-l-danger"
                  : a.nivel === "atencao"
                    ? "border-l-warn"
                    : "border-l-info"
              }`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <SeloNivel nivel={a.nivel} />
                <span className="badge-neutral">
                  {ROTULO_CATEGORIA_ALERTA[a.categoria] ?? a.categoria}
                </span>
                {lidas.has(a.id) && <span className="badge-neutral">lida</span>}
              </div>
              <p className="mt-2 font-semibold text-ink">{a.titulo}</p>
              <p className="mt-1 text-sm leading-relaxed text-ink-muted">{a.detalhe}</p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {a.acao_href && (
                  <Link href={a.acao_href} className="btn-primary btn-sm">
                    {a.acao_rotulo ?? "Abrir"} <Icone nome="setaDireita" className="h-3.5 w-3.5" />
                  </Link>
                )}
                {!lidas.has(a.id) && (
                  <button
                    type="button"
                    onClick={() => marcarComoLida(a.id)}
                    className="btn-ghost btn-sm"
                  >
                    Marcar como lida
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <section className="card-pad mt-6">
        <TituloSecao titulo="Como os alertas funcionam" />
        <p className="text-sm leading-relaxed text-ink-muted">
          Os alertas são calculados na hora a partir do estado real — validade dos certificados,
          janelas da SEFAZ, cursor de NSU e espaço em disco. Não há caixa de entrada para limpar:
          quando o problema se resolve, o alerta desaparece sozinho na próxima leitura.
        </p>
      </section>
    </div>
  );
}
