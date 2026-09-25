import { Suspense } from "react";
import type { Metadata } from "next";
import { Procuracoes } from "./Procuracoes";

export const metadata: Metadata = {
  title: "Procurações RFB",
};

/* Situação, busca e página vivem na URL — o link do alerta cai no recorte certo. */
export default function PaginaProcuracoes() {
  return (
    <Suspense fallback={null}>
      <Procuracoes />
    </Suspense>
  );
}
