"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { obterToken } from "@/lib/auth";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { ProvedorToast } from "@/components/Toast";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [autorizado, setAutorizado] = useState(false);
  const [menuAberto, setMenuAberto] = useState(false);

  useEffect(() => {
    if (!obterToken()) {
      router.replace("/login");
    } else {
      setAutorizado(true);
    }
  }, [router]);

  if (!autorizado) return null;

  return (
    <ProvedorToast>
      <div className="flex min-h-screen">
        <Sidebar aberto={menuAberto} aoFechar={() => setMenuAberto(false)} />
        <div className="flex min-h-screen min-w-0 flex-1 flex-col">
          <Topbar aoAbrirMenu={() => setMenuAberto(true)} />
          <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
            {children}
          </main>
          <footer className="no-print mx-auto w-full max-w-7xl px-4 pb-6 sm:px-6 lg:px-8">
            <p className="border-t border-line pt-4 text-xs text-ink-faint">
              NotasFlow v2.0 · Importação fiscal automática via ADN/SEFAZ · Os dados exibidos são
              lidos do seu banco local.
            </p>
          </footer>
        </div>
      </div>
    </ProvedorToast>
  );
}
