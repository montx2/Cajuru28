import { Suspense } from "react";
import type { Metadata } from "next";
import { Relatorios } from "./Relatorios";

export const metadata: Metadata = {
  title: "Fechamento",
};

/* A competência do fechamento vive na URL (`?mes=AAAA-MM`). */
export default function PaginaRelatorios() {
  return (
    <Suspense fallback={null}>
      <Relatorios />
    </Suspense>
  );
}
