"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { limparToken } from "@/lib/auth";

const ITENS_NAV = [
  { href: "/dashboard", rotulo: "Visão geral" },
  { href: "/dashboard/empresas", rotulo: "Empresas" },
  { href: "/dashboard/importacoes", rotulo: "Importações" },
  { href: "/dashboard/documentos", rotulo: "Documentos" },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();

  return (
    <aside className="flex h-screen w-60 flex-none flex-col border-r border-line bg-surface">
      <div className="border-b border-line px-5 py-5">
        <p className="font-serif text-lg text-ink">NotasFlow</p>
        <p className="text-xs text-ink-muted">Importação fiscal automática</p>
      </div>

      <nav className="flex-1 px-3 py-4">
        {ITENS_NAV.map((item) => {
          const ativo = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`mb-1 block rounded px-3 py-2 text-sm transition-colors ${
                ativo
                  ? "bg-accent-soft font-medium text-accent"
                  : "text-ink-muted hover:bg-bg hover:text-ink"
              }`}
            >
              {item.rotulo}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-line px-3 py-4">
        <button
          onClick={() => {
            limparToken();
            router.push("/login");
          }}
          className="w-full rounded px-3 py-2 text-left text-sm text-ink-muted hover:bg-bg hover:text-ink"
        >
          Sair
        </button>
      </div>
    </aside>
  );
}
