import type { ReactNode } from "react";
import { Shell } from "@/components/shell/Shell";

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
