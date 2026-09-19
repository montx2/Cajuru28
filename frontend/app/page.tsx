import { redirect } from "next/navigation";

/**
 * A raiz não tem conteúdo próprio: é porta de entrada. Quem tem cookie válido é
 * autenticado pela primeira chamada do painel; quem não tem recebe `401` e cai
 * no login. Decidir isso no servidor evita uma tela em branco com spinner.
 */
export default function PaginaRaiz() {
  redirect("/dashboard");
}
