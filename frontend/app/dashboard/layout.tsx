"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { obterToken } from "@/lib/auth";
import { Sidebar } from "@/components/Sidebar";
import { AvisoAtualizacao } from "@/components/AvisoAtualizacao";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [autorizado, setAutorizado] = useState(false);

  useEffect(() => {
    if (!obterToken()) {
      router.replace("/login");
    } else {
      setAutorizado(true);
    }
  }, [router]);

  if (!autorizado) return null;

  return (
    <div className="flex">
      <Sidebar />
      <div className="flex min-h-screen flex-1 flex-col">
        {/* Fora do <main> de propósito: a faixa de atualização precisa existir
            em todas as telas sem que cada página saiba dela. */}
        <AvisoAtualizacao />
        <main className="flex-1 px-8 py-6">{children}</main>
      </div>
    </div>
  );
}
