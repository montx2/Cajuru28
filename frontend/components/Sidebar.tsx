"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { limparCachePapel, usePapel } from "@/lib/papel";
import { api } from "@/lib/api";
import { Icone, Logomarca } from "./icons";

const NAV_VISAO_GERAL = [
  { href: "/dashboard", rotulo: "Visão geral", icone: "dashboard", exato: true },
  { href: "/dashboard/atencao", rotulo: "Atenção", icone: "alerta", seloAtencao: true },
  { href: "/dashboard/execucoes", rotulo: "Execuções", icone: "atividade" },
];

const NAV_FISCAL = [
  { href: "/dashboard/documentos", rotulo: "Documentos", icone: "documento" },
  { href: "/dashboard/importacoes", rotulo: "Importações", icone: "importacao" },
  { href: "/dashboard/empresas", rotulo: "Empresas", icone: "empresa" },
  { href: "/dashboard/certificados", rotulo: "Certificados", icone: "escudo" },
  { href: "/dashboard/relatorios", rotulo: "Fechamento", icone: "grafico" },
];

const NAV_SISTEMA = [
  { href: "/dashboard/saude", rotulo: "Saúde do sistema", icone: "hd" },
  { href: "/dashboard/configuracoes", rotulo: "Configurações", icone: "engrenagem" },
  { href: "/dashboard/auditoria", rotulo: "Auditoria", icone: "olho", minPapel: "operador" },
];

type ItemNav = {
  href: string;
  rotulo: string;
  icone: string;
  exato?: boolean;
  minPapel?: string;
  seloAtencao?: boolean;
};

function visivel(minPapel: string | undefined, papel: string): boolean {
  if (!minPapel) return true;
  if (minPapel === "admin") return papel === "admin";
  if (minPapel === "operador") return papel === "admin" || papel === "operador";
  return true;
}

function GrupoNav({
  titulo,
  itens,
  ativo,
  aoFechar,
  papel,
  criticos,
  total,
}: {
  titulo: string;
  itens: ItemNav[];
  ativo: (href: string, exato?: boolean) => boolean;
  aoFechar: () => void;
  papel: string;
  criticos: number;
  total: number;
}) {
  return (
    <div className="mb-5 last:mb-0">
      <p className="px-3 pb-2 text-[10px] font-bold uppercase tracking-[.16em] text-white/30">{titulo}</p>
      {itens
        .filter((item) => visivel(item.minPapel, papel))
        .map((item) => (
          <Link
            key={item.href}
            href={item.href}
            onClick={aoFechar}
            className={`nav-item ${ativo(item.href, item.exato) ? "nav-item-ativo" : ""}`}
          >
            <Icone nome={item.icone} className="h-[18px] w-[18px] flex-none" strokeWidth={1.75} />
            <span className="flex-1">{item.rotulo}</span>
            {item.seloAtencao && total > 0 && (
              <span
                className={`min-w-5 rounded-pill px-1.5 py-0.5 text-center font-mono text-[10px] font-bold ${
                  criticos > 0 ? "bg-danger text-white" : "bg-gold text-sidebar"
                }`}
              >
                {total > 99 ? "99+" : total}
              </span>
            )}
          </Link>
        ))}
    </div>
  );
}

/** Navegação reduzida: status e caminhos de operação em vez de menus de SaaS. */
export function Sidebar({ aberto, aoFechar }: { aberto: boolean; aoFechar: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { papel } = usePapel();
  const [criticos, setCriticos] = useState(0);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    let vivo = true;
    const carregar = () =>
      api
        .contagemAlertas()
        .then((contagem) => {
          if (vivo) {
            setCriticos(contagem.criticos);
            setTotal(contagem.total);
          }
        })
        .catch(() => {});
    carregar();
    const intervalo = window.setInterval(carregar, 60_000);
    return () => {
      vivo = false;
      window.clearInterval(intervalo);
    };
  }, []);

  const ativo = (href: string, exato?: boolean) =>
    exato ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);

  async function sair() {
    try {
      await api.logout();
    } finally {
      limparCachePapel();
      router.push("/login");
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={aoFechar}
        aria-label="Fechar menu"
        className={`no-print fixed inset-0 z-30 bg-ink/35 backdrop-blur-[2px] transition-opacity lg:hidden ${
          aberto ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <aside
        className={`no-print fixed inset-y-0 left-0 z-40 flex w-[256px] flex-none flex-col overflow-hidden border-r border-sidebar-line bg-sidebar transition-transform duration-300 ease-out lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${
          aberto ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="pointer-events-none absolute inset-x-0 top-0 h-48 bg-[radial-gradient(ellipse_at_top,rgba(91,197,148,.16),transparent_68%)]" />

        <Link href="/dashboard" onClick={aoFechar} className="relative flex items-center gap-3 px-5 pb-6 pt-6">
          <Logomarca className="h-10 w-10 rounded-[14px] text-lg" />
          <span>
            <span className="block font-display text-[18px] font-extrabold leading-tight tracking-tight text-white">NotasFlow</span>
            <span className="mt-0.5 block text-[10px] font-bold uppercase tracking-[.14em] text-white/42">Operação fiscal</span>
          </span>
        </Link>

        <div className="relative mx-3 mb-5 flex items-center gap-2 rounded-[10px] border border-white/[.07] bg-white/[.035] px-3 py-2 text-[10px] font-bold uppercase tracking-[.1em] text-white/48">
          <span className="h-1.5 w-1.5 rounded-full bg-accent-bright" />
          Ambiente privado
        </div>

        <nav className="relative flex-1 overflow-y-auto px-3 pb-5">
          <GrupoNav titulo="Visão geral" itens={NAV_VISAO_GERAL} ativo={ativo} aoFechar={aoFechar} papel={papel} criticos={criticos} total={total} />
          <GrupoNav titulo="Fiscal" itens={NAV_FISCAL} ativo={ativo} aoFechar={aoFechar} papel={papel} criticos={criticos} total={total} />
          <GrupoNav titulo="Ambiente" itens={NAV_SISTEMA} ativo={ativo} aoFechar={aoFechar} papel={papel} criticos={criticos} total={total} />
        </nav>

        <div className="relative border-t border-sidebar-line px-3 py-4">
          <div className="mb-2 flex items-center gap-2 px-3 text-[10px] font-semibold text-white/42">
            <span className="pulso-andamento inline-block h-1.5 w-1.5 rounded-full bg-accent-bright" />
            MONITORAMENTO ATIVO
          </div>
          <button type="button" onClick={sair} className="nav-item mb-0 w-full">
            <Icone nome="sair" className="h-[18px] w-[18px] flex-none" />
            Sair
          </button>
        </div>
      </aside>
    </>
  );
}
