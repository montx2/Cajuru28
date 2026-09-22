import { Suspense } from "react";
import type { Metadata } from "next";
import { Empresa } from "./Empresa";

export const metadata: Metadata = {
  title: "Empresa · Fluxa",
};

/* `id` e `aba` vivem na URL: o link de um alerta já cai na aba certa. */
export default function PaginaEmpresa() {
  return (
    <Suspense fallback={null}>
      <Empresa />
    </Suspense>
  );
}
