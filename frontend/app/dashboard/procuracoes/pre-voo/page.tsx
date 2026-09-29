import { Suspense } from "react";
import type { Metadata } from "next";
import { PreVoo } from "./PreVoo";

export const metadata: Metadata = {
  title: "Pré-voo · Procurações RFB",
};

export default function PaginaPreVoo() {
  return (
    <Suspense fallback={null}>
      <PreVoo />
    </Suspense>
  );
}
