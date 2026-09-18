import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "NotasFlow — Operação fiscal", description: "Captura, validação e fechamento de documentos fiscais.", icons: { icon: "/icone.png" } };
const scriptTema = `(function(){try{var t=localStorage.getItem('notasflow:tema')||'sistema';var e=t==='escuro'||(t==='sistema'&&matchMedia('(prefers-color-scheme:dark)').matches);document.documentElement.dataset.tema=e?'escuro':'claro'}catch(e){}})()`;
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="pt-BR" suppressHydrationWarning><head><script dangerouslySetInnerHTML={{ __html: scriptTema }} /></head><body>{children}</body></html>; }
