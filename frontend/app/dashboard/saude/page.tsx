import type { Metadata } from "next";
import { Saude } from "./Saude";

export const metadata: Metadata = {
  title: "Saúde · Fluxa",
};

/* Tela sem filtros de URL: lê o estado atual do ambiente. */
export default function PaginaSaude() {
  return <Saude />;
}
