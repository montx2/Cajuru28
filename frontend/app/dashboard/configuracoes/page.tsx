import { Suspense } from "react";
import type { Metadata } from "next";
import { Configuracoes } from "./Configuracoes";

export const metadata: Metadata = {
  title: "Configurações · Fluxa",
};

/* A aba ativa vive na URL: link de alerta cai direto na seção certa. */
export default function PaginaConfiguracoes() {
  return (
    <Suspense fallback={null}>
      <Configuracoes />
    </Suspense>
  );
}
