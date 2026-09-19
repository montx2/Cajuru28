import { Suspense } from "react";
import type { Metadata } from "next";
import { Documentos } from "./Documentos";

export const metadata: Metadata = {
  title: "Documentos · NotasFlow",
};

/* Período, filtros, ordenação, página e documento aberto vivem na URL. */
export default function PaginaDocumentos() {
  return (
    <Suspense fallback={null}>
      <Documentos />
    </Suspense>
  );
}
