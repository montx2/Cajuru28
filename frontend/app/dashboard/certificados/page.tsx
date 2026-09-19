import { Suspense } from "react";
import type { Metadata } from "next";
import { Certificados } from "./Certificados";

export const metadata: Metadata = {
  title: "Certificados · NotasFlow",
};

/* Filtro, busca e ordenação vivem na URL. */
export default function PaginaCertificados() {
  return (
    <Suspense fallback={null}>
      <Certificados />
    </Suspense>
  );
}
