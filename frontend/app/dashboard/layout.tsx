"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "@/components/Sidebar";
import { Topbar } from "@/components/Topbar";
import { ProvedorToast } from "@/components/Toast";
import { api } from "@/lib/api";
export default function DashboardLayout({ children }: { children: React.ReactNode }) { const router = useRouter(); const [autorizado, setAutorizado] = useState(false); const [menu, setMenu] = useState(false); useEffect(() => { let vivo = true; api.quemSouEu().then(() => { if (vivo) setAutorizado(true); }).catch(() => router.replace("/login")); return () => { vivo = false; }; }, [router]); return <ProvedorToast><a href="#conteudo-principal" className="fixed left-3 top-3 z-[100] -translate-y-20 rounded-md bg-superficie px-3 py-2 text-sm shadow-nivel1 focus:translate-y-0">Pular para o conteúdo</a>{autorizado ? <div className="app-shell flex min-h-screen"><Sidebar aberto={menu} aoFechar={() => setMenu(false)} /><div className="min-w-0 flex-1"><Topbar aoAbrirMenu={() => setMenu(true)} /><main id="conteudo-principal" tabIndex={-1} className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6">{children}</main></div></div> : <main id="conteudo-principal" className="grid min-h-screen place-items-center" aria-busy="true"><span className="text-sm text-tinta-suave">Validando sessão…</span></main>}</ProvedorToast>; }
