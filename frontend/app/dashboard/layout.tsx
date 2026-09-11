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
      <div className="app-shell flex min-h-screen">
        <Sidebar aberto={menuAberto} aoFechar={() => setMenuAberto(false)} />
        <div className="relative flex min-h-screen min-w-0 flex-1 flex-col">
          <Topbar aoAbrirMenu={() => setMenuAberto(true)} />
          <main className="relative mx-auto w-full max-w-[1440px] flex-1 px-4 py-7 sm:px-7 lg:px-10 lg:py-9">
            {children}
          </main>
          <footer className="no-print mx-auto w-full max-w-[1440px] px-4 pb-6 sm:px-7 lg:px-10">
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
