"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { obterToken } from "@/lib/auth";
import { Sidebar } from "@/components/Sidebar";

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
      <main className="min-h-screen flex-1 px-8 py-6">{children}</main>
    </div>
  );
}
