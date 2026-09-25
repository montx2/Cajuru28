import { Suspense } from "react";
import type { Metadata } from "next";
import { Estacoes } from "./Estacoes";

export const metadata: Metadata = {
  title: "Estações · Procurações RFB · Fluxa",
};

export default function PaginaEstacoes() {
  return (
    <Suspense fallback={null}>
      <Estacoes />
    </Suspense>
  );
}
