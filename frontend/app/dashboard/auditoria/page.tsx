import { Suspense } from "react";
import type { Metadata } from "next";
import { Auditoria } from "./Auditoria";

export const metadata: Metadata = {
  title: "Auditoria · NotasFlow",
};

/* Ação, busca e limite vivem na URL. */
export default function PaginaAuditoria() {
  return (
    <Suspense fallback={null}>
      <Auditoria />
    </Suspense>
  );
}
