"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { limparToken } from "@/lib/auth";
import { limparCachePapel } from "@/lib/papel";
import { iniciais } from "@/lib/format";
import type { AlertasResposta, UsuarioAtual } from "@/lib/types";
import { Icone } from "./icons";
import { SeloNivel } from "./ui";

/**
 * Barra superior: busca global (chave/emitente/número), sino de alertas com
 * prévia e menu do usuário. Fixa no topo em todas as telas do painel.
 */
export function Topbar({ aoAbrirMenu }: { aoAbrirMenu: () => void }) {
  const router = useRouter();
  const [busca, setBusca] = useState("");
  const [usuario, setUsuario] = useState<UsuarioAtual | null>(null);
  const [alertas, setAlertas] = useState<AlertasResposta | null>(null);
  const [sinoAberto, setSinoAberto] = useState(false);
  const [menuAberto, setMenuAberto] = useState(false);
  const campoBusca = useRef<HTMLInputElement>(null);
  const sinoRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.quemSouEu().then(setUsuario).catch(() => {});
    const carregar = () => api.alertas().then(setAlertas).catch(() => {});
    carregar();
    const intervalo = setInterval(carregar, 60_000);
    return () => clearInterval(intervalo);
  }, []);

  // Ctrl/⌘+K foca a busca; fecha painéis ao clicar fora.
  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        campoBusca.current?.focus();
      }
      if (e.key === "Escape") {
        setSinoAberto(false);
        setMenuAberto(false);
      }
    };
    const clique = (e: MouseEvent) => {
      if (sinoRef.current && !sinoRef.current.contains(e.target as Node)) {
        setSinoAberto(false);
        setMenuAberto(false);
      }
    };
    window.addEventListener("keydown", tecla);
    window.addEventListener("mousedown", clique);
    return () => {
      window.removeEventListener("keydown", tecla);
      window.removeEventListener("mousedown", clique);
    };
  }, []);

  function pesquisar(e: React.FormEvent) {
    e.preventDefault();
    const termo = busca.trim();
    router.push(termo ? `/dashboard/documentos?busca=${encodeURIComponent(termo)}` : "/dashboard/documentos");
  }

  const previos = (alertas?.itens ?? []).slice(0, 5);

  return (
    <header className="no-print sticky top-0 z-20 border-b border-line bg-surface/90 backdrop-blur">
      <div className="flex h-16 items-center gap-3 px-4 sm:px-6">
        <button
          type="button"
          onClick={aoAbrirMenu}
          className="btn-icon lg:hidden"
          aria-label="Abrir menu"
        >
          <Icone nome="menu" className="h-6 w-6" />
        </button>

        <form onSubmit={pesquisar} className="relative hidden max-w-md flex-1 sm:block">
          <Icone
            nome="busca"
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
          />
          <input
            ref={campoBusca}
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            placeholder="Busca fiscal — chave, número, emitente, CNPJ…  (Ctrl+K)"
            className="input pl-9"
          />
        </form>
        <div className="flex-1 sm:hidden" />

        <div ref={sinoRef} className="relative flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              setSinoAberto((v) => !v);
              setMenuAberto(false);
            }}
            className="btn-icon relative"
            aria-label="Alertas"
            title="Central de alertas"
          >
            <Icone nome="sino" className="h-5 w-5" />
            {(alertas?.total ?? 0) > 0 && (
              <span
                className={`absolute -right-0.5 -top-0.5 rounded-pill px-1.5 py-px font-mono text-[10px] font-bold text-white ${
                  (alertas?.criticos ?? 0) > 0 ? "bg-danger" : "bg-warn"
                }`}
              >
                {alertas?.total}
              </span>
            )}
          </button>

          {sinoAberto && (
            <div className="animate-fade-in absolute right-0 top-11 w-96 max-w-[90vw] overflow-hidden rounded-card border border-line bg-surface shadow-pop">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <p className="text-sm font-semibold text-ink">
                  Alertas
                  {(alertas?.total ?? 0) > 0 && (
                    <span className="ml-2 text-xs font-normal text-ink-muted">
                      {alertas?.criticos} crítico(s) · {alertas?.atencao} atenção
                    </span>
                  )}
                </p>
                <Link
                  href="/dashboard/atencao"
                  onClick={() => setSinoAberto(false)}
                  className="link text-xs font-semibold"
                >
                  ver tudo
                </Link>
              </div>
              {previos.length === 0 ? (
                <p className="px-4 py-6 text-center text-sm text-ink-muted">
                  Nenhum alerta — tudo sob controle. ✨
                </p>
              ) : (
                <ul className="max-h-80 divide-y divide-line/70 overflow-y-auto">
                  {previos.map((a) => (
                    <li key={a.id}>
                      <Link
                        href={a.acao_href ?? "/dashboard/atencao"}
                        onClick={() => setSinoAberto(false)}
                        className="block px-4 py-3 hover:bg-bg"
                      >
                        <span className="flex items-center gap-2">
                          <SeloNivel nivel={a.nivel} />
                        </span>
                        <span className="mt-1 block text-sm font-medium text-ink">{a.titulo}</span>
                        <span className="mt-0.5 line-clamp-2 block text-xs text-ink-muted">
                          {a.detalhe}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <button
            type="button"
            onClick={() => {
              setMenuAberto((v) => !v);
              setSinoAberto(false);
            }}
            className="flex items-center gap-2.5 rounded-lg px-2 py-1.5 hover:bg-bg"
            aria-label="Menu do usuário"
          >
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-accent-bright to-accent-deep text-xs font-bold text-white">
              {iniciais(usuario?.nome)}
            </span>
            <span className="hidden text-left md:block">
              <span className="block max-w-32 truncate text-sm font-semibold leading-tight text-ink">
                {usuario?.nome ?? "…"}
              </span>
              <span className="block max-w-32 truncate text-xs leading-tight text-ink-muted">
                {usuario?.escritorio_nome ?? ""}
              </span>
            </span>
            <Icone nome="chevronBaixo" className="h-4 w-4 text-ink-faint" />
          </button>

          {menuAberto && (
            <div className="animate-fade-in absolute right-0 top-11 w-60 overflow-hidden rounded-card border border-line bg-surface shadow-pop">
              <div className="border-b border-line px-4 py-3">
                <p className="truncate text-sm font-semibold text-ink">{usuario?.nome}</p>
                <p className="truncate text-xs text-ink-muted">{usuario?.email}</p>
              </div>
              <Link
                href="/dashboard/configuracoes"
                onClick={() => setMenuAberto(false)}
                className="flex items-center gap-2 px-4 py-2.5 text-sm text-ink hover:bg-bg"
              >
                <Icone nome="engrenagem" className="h-4 w-4" /> Configurações
              </Link>
              <button
                type="button"
                onClick={() => {
                  limparToken();
                  limparCachePapel();
                  router.push("/login");
                }}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-danger hover:bg-danger-soft"
              >
                <Icone nome="sair" className="h-4 w-4" /> Sair
              </button>
            </div>
          )}
        </div>
      </div>
      {/* busca no mobile */}
      <form onSubmit={pesquisar} className="relative px-4 pb-3 sm:hidden">
        <Icone
          nome="busca"
          className="pointer-events-none absolute left-7 top-1/2 h-4 w-4 -translate-y-[calc(50%+6px)] text-ink-faint"
        />
        <input
          value={busca}
          onChange={(e) => setBusca(e.target.value)}
          placeholder="Buscar documentos…"
          className="input pl-9"
        />
      </form>
    </header>
  );
}
