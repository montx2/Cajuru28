"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { Icone } from "@/components/icons";
import { Esqueleto, EstadoVazio, SeloNivel, TituloSecao } from "@/components/ui";
import { ROTULO_CATEGORIA_ALERTA, type AlertasResposta, type NivelAlerta } from "@/lib/types";

const CHAVE_LIDAS = "notasflow_atencao_lidas";

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
  { id: "atencao", rotulo: "Importantes" },
  { id: "info", rotulo: "Informativas" },
];

/**
 * Precisa da sua atenção — a lista operacional principal.
 *
 * O objetivo é transformar centenas de informações do sistema numa lista
 * CURTA de ações realmente necessárias, ordenada por gravidade. Cada item
 * tem o botão que resolve: o operador nunca precisa procurar onde agir.
 */
export default function AtencaoPage() {
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
    salvarLidas(new Set([...lidas, id]));
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
    <div className="max-w-5xl">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title">Precisa da sua atenção</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {dados ? (
              <>
                <span className="font-semibold text-danger">{dados.criticos} crítico(s)</span>
                {" · "}
                <span className="font-semibold text-warn">{dados.atencao} importante(s)</span>
                {" · "}
                <span>{dados.infos} informativa(s)</span>
                {" — "}
                {dados.total === 0
                  ? "a automação cuida de tudo."
                  : "resolva de cima para baixo."}
              </>
            ) : (
              "Lendo o estado do sistema…"
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <button type="button" onClick={() => setMostrarLidas((v) => !v)} className="btn-ghost btn-sm">
            {mostrarLidas ? "Ocultar lidas" : "Mostrar lidas"}
          </button>
          <button type="button" onClick={marcarTodas} className="btn-ghost btn-sm">
            Marcar todas como lidas
          </button>
          <button type="button" onClick={carregar} className="btn-ghost btn-sm">
            <Icone nome="atualizar" className="h-4 w-4" /> Atualizar
          </button>
        </div>
      </div>

      {carregando && !dados ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Esqueleto key={i} className="h-24" />
          ))}
        </div>
      ) : !dados ? (
        <EstadoVazio
          icone="alerta"
          titulo="Não foi possível ler os alertas"
          texto="Verifique se a API está respondendo e tente atualizar."
          acao={
            <button type="button" onClick={carregar} className="btn-primary btn-sm">
              Tentar de novo
            </button>
          }
        />
      ) : visiveis.length === 0 ? (
        <EstadoVazio
          icone="checkCirculo"
          titulo="Nada precisa de você agora"
          texto="Quando algo exigir ação — certificado vencendo, empresa parada, fila acumulada — aparece aqui, já com o caminho da resolução."
        />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-2">
            {FILTROS.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFiltro(f.id)}
                className={filtro === f.id ? "btn-primary btn-sm" : "btn-ghost btn-sm"}
              >
                {f.rotulo}
                <span className="ml-1.5 font-mono text-xs opacity-70">{contagem(f.id)}</span>
              </button>
            ))}
          </div>

          <ul className="space-y-3">
            {visiveis.map((a) => {
              const lida = lidas.has(a.id);
              return (
                <li
                  key={a.id}
                  className={`card card-pad ${lida ? "opacity-55" : ""} ${
                    a.nivel === "critico" ? "border-l-4 border-l-danger" : a.nivel === "atencao" ? "border-l-4 border-l-warn" : "border-l-4 border-l-info"
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <SeloNivel nivel={a.nivel} />
                        <span className="badge-info">
                          {ROTULO_CATEGORIA_ALERTA[a.categoria] ?? a.categoria}
                        </span>
                        {a.empresa_razao_social && (
                          <span className="text-xs text-ink-faint">{a.empresa_razao_social}</span>
                        )}
                      </div>
                      <p className="mt-2 font-medium text-ink">{a.titulo}</p>
                      <p className="mt-1 text-sm leading-relaxed text-ink-muted">{a.detalhe}</p>
                    </div>
                    <div className="flex flex-none items-center gap-2">
                      {a.acao_rotulo && a.acao_href && (
                        <Link href={a.acao_href} className="btn-primary btn-sm">
                          {a.acao_rotulo}
                        </Link>
                      )}
                      {!lida && (
                        <button
                          type="button"
                          onClick={() => marcarComoLida(a.id)}
                          className="btn-ghost btn-sm"
                          title="Esconder este item neste navegador (o problema continua sendo monitorado)"
                        >
                          <Icone nome="check" className="h-4 w-4" />
                        </button>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>

          <p className="text-xs text-ink-faint">
            Os alertas são computados a partir do estado real do sistema — quando o
            problema se resolve, o item some sozinho na próxima leitura.
          </p>
        </div>
      )}
    </div>
  );
}
