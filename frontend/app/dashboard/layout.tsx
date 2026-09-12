"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { ProvedorToast } from "@/components/Toast";
import { api } from "@/lib/api";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [autorizado, setAutorizado] = useState(false);
  const [menuAberto, setMenuAberto] = useState(false);

  useEffect(() => {
    let ativo = true;
    // O cookie é HttpOnly, logo a única forma correta de conhecer a sessão é
    // perguntar à API. Isso também valida revogação e versão de sessão.
    api.quemSouEu()
      .then(() => ativo && setAutorizado(true))
      .catch(() => router.replace("/login"));
    return () => { ativo = false; };
  }, [router]);

  if (!autorizado) return null;

  return (
    <ProvedorToast>
      <div className="app-shell flex min-h-screen">
        <Sidebar aberto={menuAberto} aoFechar={() => setMenuAberto(false)} />
        <div className="relative flex min-h-screen min-w-0 flex-1 flex-col">
          <Topbar aoAbrirMenu={() => setMenuAberto(true)} />
          <main className="relative mx-auto w-full max-w-[1600px] flex-1 px-4 py-7 sm:px-7 lg:px-9 lg:py-8 xl:px-11">
            {children}
          </main>
          <footer className="no-print mx-auto w-full max-w-[1600px] px-4 pb-6 sm:px-7 lg:px-9 xl:px-11">
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line/80 pt-4 text-[11px] text-ink-faint">
              <span>NotasFlow · operação fiscal automática</span>
              <span className="font-mono">dados locais · ADN / SEFAZ</span>
            </div>
          </footer>
        </div>
      </div>
    </ProvedorToast>
  );
}
