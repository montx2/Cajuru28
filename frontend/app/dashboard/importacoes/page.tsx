import { Suspense } from "react";
import type { Metadata } from "next";
import { Importacoes } from "./Importacoes";

export const metadata: Metadata = {
  title: "Importações · Fluxa",
};

/* Período, empresas, tipos, forçar e filtros do sincronismo vivem na URL. */
export default function PaginaImportacoes() {
  return (
    <Suspense fallback={null}>
      <Importacoes />
    </Suspense>
  );
}
