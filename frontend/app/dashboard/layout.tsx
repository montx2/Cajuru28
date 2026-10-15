import type { ReactNode } from "react";
import { Shell } from "@/components/shell/Shell";

/* Shell autenticado com dados 100% no cliente: pré-renderizar a casca não compra
   nada e a competência do cabeçalho lê a URL (`useSearchParams`) já no layout. */
export const dynamic = "force-dynamic";

/**
 * Layout do workspace.
 *
 * É servidor de propósito: quem decide se há sessão é a API em cada chamada
 * (`401` → `/login`). Fazer essa checagem aqui criaria um segundo lugar para
 * guardar regra de autenticação e ainda renderizaria no servidor um estado que
 * só existe no navegador.
 */
export default function LayoutDashboard({ children }: { children: ReactNode }) {
  return <Shell>{children}</Shell>;
}
