"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { limparCachePapel } from "@/lib/papel";
import { iniciais } from "@/lib/format";
import type { AlertasResposta, UsuarioAtual } from "@/lib/types";
import { Icone } from "./icons";
import { SeloNivel } from "./ui";

const TITULOS: Record<string, string> = {
  "/dashboard": "Visão geral",
  "/dashboard/atencao": "Atenção",
  "/dashboard/execucoes": "Execuções",
  "/dashboard/documentos": "Documentos",
  "/dashboard/importacoes": "Importações",
  "/dashboard/empresas": "Empresas",
  "/dashboard/empresa": "Empresa",
  "/dashboard/certificados": "Certificados",
  "/dashboard/relatorios": "Fechamento",
  "/dashboard/saude": "Saúde do sistema",
  "/dashboard/configuracoes": "Configurações",
  "/dashboard/auditoria": "Auditoria",
};

/** Barra de contexto: navegação móvel, busca global e somente ações pessoais. */
export function Topbar({ aoAbrirMenu }: { aoAbrirMenu: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const [busca, setBusca] = useState("");
  const [usuario, setUsuario] = useState<UsuarioAtual | null>(null);
  const [alertas, setAlertas] = useState<AlertasResposta | null>(null);
  const [sinoAberto, setSinoAberto] = useState(false);
  const [menuAberto, setMenuAberto] = useState(false);
  const campoBusca = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const carregarAlertas = useCallback(() => api.alertas().then(setAlertas).catch(() => {}), []);

  useEffect(() => {
    api.quemSouEu().then(setUsuario).catch(() => {});
    carregarAlertas();
    const intervalo = window.setInterval(carregarAlertas, 60_000);
    return () => window.clearInterval(intervalo);
  }, [carregarAlertas]);

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        campoBusca.current?.focus();
      }
      if (e.key === "Escape") {
        setSinoAberto(false);
        setMenuAberto(false);
        campoBusca.current?.blur();
      }
    };
    const clique = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
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

  const previos = (alertas?.itens ?? []).slice(0, 4);
  const titulo = TITULOS[pathname] ?? "NotasFlow";

  return (
    <header className="no-print sticky top-0 z-20 border-b border-white/65 bg-bg/85 backdrop-blur-xl backdrop-saturate-150">
      <div className="mx-auto flex h-16 max-w-[1600px] items-center gap-3 px-4 sm:px-7 lg:px-9 xl:px-11">
        <button type="button" onClick={aoAbrirMenu} className="btn-icon lg:hidden" aria-label="Abrir menu">
          <Icone nome="menu" className="h-5 w-5" />
        </button>

        <div className="hidden min-w-[148px] lg:block">
          <p className="text-[10px] font-extrabold uppercase tracking-[.13em] text-ink-faint">Operação fiscal</p>
          <p className="truncate text-sm font-extrabold text-ink">{titulo}</p>
        </div>

        <form onSubmit={pesquisar} className="relative hidden max-w-[520px] flex-1 sm:block">
          <Icone nome="busca" className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            ref={campoBusca}
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            placeholder="Buscar por chave, número, emitente ou CNPJ"
            className="input h-10 pl-10 pr-16"
            aria-label="Busca fiscal"
          />
          <span className="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 rounded-md border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink-faint md:block">⌘ K</span>
        </form>
        <div className="flex-1 sm:hidden">
          <p className="truncate text-sm font-bold text-ink">{titulo}</p>
        </div>

        <div className="hidden xl:flex items-center gap-2 border-r border-line pr-4 text-[11px] font-semibold text-ink-muted">
          <span className="pulso-andamento h-1.5 w-1.5 rounded-full bg-accent" />
          Automação ativa
        </div>

        <div ref={menuRef} className="relative flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              setSinoAberto((valor) => !valor);
              setMenuAberto(false);
            }}
            className="btn-icon relative"
            aria-label="Abrir alertas"
            aria-expanded={sinoAberto}
          >
            <Icone nome="sino" className="h-[18px] w-[18px]" />
            {(alertas?.total ?? 0) > 0 && (
              <span className={`absolute right-1 top-1 h-2 w-2 rounded-full ring-2 ring-bg ${
                (alertas?.criticos ?? 0) > 0 ? "bg-danger" : "bg-warn"
              }`} />
            )}
          </button>

          <button
            type="button"
            onClick={() => {
              setMenuAberto((valor) => !valor);
              setSinoAberto(false);
            }}
            className="group flex items-center gap-2 rounded-xl border border-transparent py-1 pl-1 pr-2 transition-colors hover:border-line hover:bg-surface"
            aria-label="Menu do usuário"
            aria-expanded={menuAberto}
          >
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-accent-bright to-accent-deep text-[11px] font-extrabold text-white shadow-sm">
              {iniciais(usuario?.nome)}
            </span>
            <span className="hidden max-w-28 text-left md:block">
              <span className="block truncate text-xs font-bold leading-tight text-ink">{usuario?.nome ?? "…"}</span>
              <span className="mt-0.5 block truncate text-[10px] leading-tight text-ink-faint">{usuario?.escritorio_nome ?? ""}</span>
            </span>
            <Icone nome="chevronBaixo" className="hidden h-3.5 w-3.5 text-ink-faint md:block" />
          </button>

          {sinoAberto && (
            <div className="animate-scale-in absolute right-0 top-12 w-[380px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-card border border-white/80 bg-surface/95 shadow-pop backdrop-blur-xl">
              <div className="flex items-center justify-between border-b border-line px-4 py-3.5">
                <div>
                  <p className="text-sm font-extrabold text-ink">Atenção</p>
                  <p className="mt-0.5 text-[11px] text-ink-muted">
                    {(alertas?.total ?? 0) ? `${alertas?.total} item(ns) monitorado(s)` : "Nenhuma pendência agora"}
                  </p>
                </div>
                <Link href="/dashboard/atencao" onClick={() => setSinoAberto(false)} className="link text-xs">Ver lista</Link>
              </div>
              {previos.length === 0 ? (
                <div className="px-4 py-8 text-center">
                  <Icone nome="checkCirculo" className="mx-auto h-6 w-6 text-accent" />
                  <p className="mt-2 text-sm font-bold text-ink">Tudo em ordem</p>
                  <p className="mt-1 text-xs text-ink-muted">A automação segue monitorando por você.</p>
                </div>
              ) : (
                <ul className="divide-y divide-line/70">
                  {previos.map((alerta) => (
                    <li key={alerta.id}>
                      <Link href={alerta.acao_href ?? "/dashboard/atencao"} onClick={() => setSinoAberto(false)} className="block px-4 py-3 transition-colors hover:bg-surface-2">
                        <span className="flex items-center justify-between gap-3"><SeloNivel nivel={alerta.nivel} /><Icone nome="chevronDireita" className="h-3.5 w-3.5 text-ink-faint" /></span>
                        <span className="mt-2 block text-sm font-bold text-ink">{alerta.titulo}</span>
                        <span className="mt-1 line-clamp-2 block text-xs leading-5 text-ink-muted">{alerta.detalhe}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {menuAberto && (
            <div className="animate-scale-in absolute right-0 top-12 w-64 overflow-hidden rounded-card border border-white/80 bg-surface/95 shadow-pop backdrop-blur-xl">
              <div className="border-b border-line px-4 py-3.5">
                <p className="truncate text-sm font-extrabold text-ink">{usuario?.nome}</p>
                <p className="mt-1 truncate text-xs text-ink-muted">{usuario?.email}</p>
              </div>
              <Link href="/dashboard/configuracoes" onClick={() => setMenuAberto(false)} className="flex items-center gap-2.5 px-4 py-3 text-sm font-semibold text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink">
                <Icone nome="engrenagem" className="h-4 w-4" /> Configurações
              </Link>
              <button
                type="button"
                onClick={async () => {
                  try {
                    await api.logout();
                  } finally {
                    limparCachePapel();
                    router.push("/login");
                  }
                }}
                className="flex w-full items-center gap-2.5 border-t border-line px-4 py-3 text-sm font-bold text-danger transition-colors hover:bg-danger-soft/60"
              >
                <Icone nome="sair" className="h-4 w-4" /> Sair
              </button>
            </div>
          )}
        </div>
      </div>

      <form onSubmit={pesquisar} className="relative px-4 pb-3 sm:hidden">
        <Icone nome="busca" className="pointer-events-none absolute left-7 top-1/2 h-4 w-4 -translate-y-[calc(50%+6px)] text-ink-faint" />
        <input value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar documentos…" className="input h-10 pl-10" aria-label="Busca fiscal" />
      </form>
    </header>
  );
}
