import { Suspense } from "react";
import type { Metadata } from "next";
import { EmpresaProcuracao } from "./EmpresaProcuracao";

export const metadata: Metadata = {
  title: "Procuração da empresa",
};

export default function PaginaEmpresaProcuracao() {
  return (
    <Suspense fallback={null}>
      <EmpresaProcuracao />
    </Suspense>
  );
}
