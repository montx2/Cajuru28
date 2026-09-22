import { Suspense } from "react";
import type { Metadata } from "next";
import { Usuarios } from "./Usuarios";

export const metadata: Metadata = {
  title: "Equipe · Fluxa",
};

/* Busca, filtro e ordenação vivem na URL. */
export default function PaginaUsuarios() {
  return (
    <Suspense fallback={null}>
      <Usuarios />
    </Suspense>
  );
}
