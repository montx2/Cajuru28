import { redirect } from "next/navigation";

/**
 * `/dashboard/alertas` virou `/dashboard/atencao`: o nome antigo descrevia o
 * mecanismo, o novo descreve o trabalho. Links salvos, favoritos e e-mails
 * antigos continuam funcionando — por isso é redirect e não 404.
 */
export default function PaginaAlertas() {
  redirect("/dashboard/atencao");
}
