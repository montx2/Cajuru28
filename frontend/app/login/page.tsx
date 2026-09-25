import { Suspense } from "react";
import type { Metadata } from "next";
import { FormularioLogin } from "./FormularioLogin";

export const metadata: Metadata = {
  title: "Entrar",
};

/* `useSearchParams` exige fronteira de Suspense no build estático do App Router. */
export default function PaginaLogin() {
  return (
    <Suspense fallback={null}>
      <FormularioLogin />
    </Suspense>
  );
}
