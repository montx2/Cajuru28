import { Suspense } from "react";
import type { Metadata } from "next";
import { Execucoes } from "./Execucoes";

export const metadata: Metadata = {
  title: "Execuções · Fluxa",
};

/* Aba, empresa, tipo, busca e ordenação vivem na URL. */
export default function PaginaExecucoes() {
  return (
    <Suspense fallback={null}>
      <Execucoes />
    </Suspense>
  );
}
