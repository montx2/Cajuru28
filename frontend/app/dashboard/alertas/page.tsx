import { redirect } from "next/navigation";

/**
 * A central de alertas virou "Precisa da sua atenção" — a lista operacional
 * principal do sistema privado. Mantemos a rota antiga redirecionando para
 * não quebrar favoritos e hábitos de teclado do operador.
 */
export default function AlertasPage() {
  redirect("/dashboard/atencao");
}
