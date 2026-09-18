"use client";
import { useEffect, useState } from "react";
type Tema = "claro" | "escuro" | "sistema";
function aplicar(tema: Tema) { const escuro = tema === "escuro" || (tema === "sistema" && window.matchMedia("(prefers-color-scheme: dark)").matches); document.documentElement.dataset.tema = escuro ? "escuro" : "claro"; }
export function SeletorTema() {
  const [tema, setTema] = useState<Tema>("sistema");
  useEffect(() => { const salvo = localStorage.getItem("notasflow:tema"); const inicial: Tema = salvo === "claro" || salvo === "escuro" ? salvo : "sistema"; setTema(inicial); aplicar(inicial); const media = window.matchMedia("(prefers-color-scheme: dark)"); const mudar = () => aplicar(inicial); media.addEventListener("change", mudar); return () => media.removeEventListener("change", mudar); }, []);
  return <select id="tema-interface" className="h-10 max-w-28 rounded-md border border-traco bg-superficie px-2 text-xs text-tinta" value={tema} onChange={(e) => { const valor = e.target.value as Tema; setTema(valor); localStorage.setItem("notasflow:tema", valor); aplicar(valor); }} aria-label="Tema da interface"><option value="sistema">Tema: sistema</option><option value="claro">Tema: claro</option><option value="escuro">Tema: escuro</option></select>;
}
