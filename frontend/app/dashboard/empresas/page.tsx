import { Suspense } from "react";
import type { Metadata } from "next";
import { Empresas } from "./Empresas";

export const metadata: Metadata = {
  title: "Empresas",
};

/* Busca, situação, ordenação e página vivem na URL. */
export default function PaginaEmpresas() {
  return (
    <Suspense fallback={null}>
      <Empresas />
    </Suspense>
  );
}
