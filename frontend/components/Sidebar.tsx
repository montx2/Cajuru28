"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { limparToken } from "@/lib/auth";
import { api } from "@/lib/api";
import { Icone, Logomarca } from "./icons";

const NAV_OPERACAO = [
  { href: "/dashboard", rotulo: "Visão geral", icone: "dashboard", exato: true },
  { href: "/dashboard/importacoes", rotulo: "Importações", icone: "importacao" },
  { href: "/dashboard/documentos", rotulo: "Documentos", icone: "documento" },
  { href: "/dashboard/relatorios", rotulo: "Fechamento", icone: "grafico" },
];

const NAV_GESTAO = [
  { href: "/dashboard/empresas", rotulo: "Empresas", icone: "empresa" },
  { href: "/dashboard/alertas", rotulo: "Alertas", icone: "sino", seloAlertas: true },
  { href: "/dashboard/configuracoes", rotulo: "Configurações", icone: "engrenagem" },
];

export function Sidebar({
  aberto,
  aoFechar,
}: {
  aberto: boolean;
  aoFechar: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [criticos, setCriticos] = useState(0);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    let vivo = true;
    const carregar = () =>
      api
        .contagemAlertas()
        .then((c) => {
          if (vivo) {
            setCriticos(c.criticos);
            setTotal(c.total);
          }
        })
        .catch(() => {});
    carregar();
    const intervalo = setInterval(carregar, 60_000);
    return () => {
      vivo = false;
      clearInterval(intervalo);
    };
  }, []);

  const ativo = (href: string, exato?: boolean) =>
    exato ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <>
      {/* véu no mobile */}
      <div
        onClick={aoFechar}
        className={`no-print fixed inset-0 z-30 bg-ink/50 backdrop-blur-sm transition-opacity lg:hidden ${
          aberto ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      <aside
        className={`no-print fixed inset-y-0 left-0 z-40 flex w-64 flex-none flex-col bg-sidebar transition-transform duration-200 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0 ${
          aberto ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <Link href="/dashboard" onClick={aoFechar} className="flex items-center gap-3 px-5 pb-5 pt-6">
          <Logomarca />
          <span>
            <span className="block font-serif text-lg font-bold leading-tight text-white">
              NotasFlow
            </span>
            <span className="block text-[11px] font-medium uppercase tracking-wider text-white/40">
              Gestão fiscal
            </span>
          </span>
        </Link>

        <nav className="flex-1 overflow-y-auto px-3 pb-4">
          <p className="px-3 pb-1.5 pt-2 text-[11px] font-semibold uppercase tracking-wider text-white/35">
            Operação
          </p>
          {NAV_OPERACAO.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={aoFechar}
              className={`nav-item ${ativo(item.href, item.exato) ? "nav-item-ativo" : ""}`}
            >
              <Icone nome={item.icone} className="h-5 w-5 flex-none" />
              {item.rotulo}
            </Link>
          ))}

          <p className="px-3 pb-1.5 pt-4 text-[11px] font-semibold uppercase tracking-wider text-white/35">
            Gestão
          </p>
          {NAV_GESTAO.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={aoFechar}
              className={`nav-item ${ativo(item.href) ? "nav-item-ativo" : ""}`}
            >
              <Icone nome={item.icone} className="h-5 w-5 flex-none" />
              <span className="flex-1">{item.rotulo}</span>
              {"seloAlertas" in item && total > 0 && (
                <span
                  className={`rounded-pill px-2 py-0.5 font-mono text-[11px] font-bold ${
                    criticos > 0 ? "bg-danger text-white" : "bg-gold text-sidebar"
                  }`}
                >
                  {total}
                </span>
              )}
            </Link>
          ))}
        </nav>

        <div className="border-t border-sidebar-line px-3 py-4">
          <div className="mb-2 flex items-center justify-between px-3">
            <span className="font-mono text-[11px] text-white/35">v2.0 premium</span>
            <span className="flex items-center gap-1.5 text-[11px] text-accent-bright">
              <span className="pulso-andamento inline-block h-1.5 w-1.5 rounded-full bg-accent-bright" />
              online
            </span>
          </div>
          <button
            type="button"
            onClick={() => {
              limparToken();
              router.push("/login");
            }}
            className="nav-item w-full"
          >
            <Icone nome="sair" className="h-5 w-5 flex-none" />
            Sair
          </button>
        </div>
      </aside>
    </>
  );
}
