import { Suspense } from "react";
import type { Metadata } from "next";
import { Painel } from "./Painel";

export const metadata: Metadata = {
  title: "Painel · Fluxa",
};

/* Filtros de competência vivem na URL: `useSearchParams` pede fronteira de Suspense. */
export default function PaginaPainel() {
  return (
    <Suspense fallback={null}>
      <Painel />
    </Suspense>
  );
}
