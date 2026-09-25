import { Suspense } from "react";
import type { Metadata } from "next";
import { Atencao } from "./Atencao";

export const metadata: Metadata = {
  title: "Precisa da sua atenção",
};

/* Filtros de nível, categoria e empresa vivem na URL. */
export default function PaginaAtencao() {
  return (
    <Suspense fallback={null}>
      <Atencao />
    </Suspense>
  );
}
