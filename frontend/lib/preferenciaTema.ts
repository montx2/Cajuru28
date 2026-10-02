import { PREFIXO_ARMAZENAMENTO } from "./atalhos";

export type Tema = "claro" | "escuro" | "sistema";
export const TEMA_PADRAO: Tema = "escuro";
export const CHAVE_TEMA = `${PREFIXO_ARMAZENAMENTO}tema`;

export function normalizarTema(valor: string | null): Tema {
  return valor === "claro" || valor === "escuro" || valor === "sistema" ? valor : TEMA_PADRAO;
}

export function ehTemaEscuro(tema: Tema, sistemaEscuro: boolean): boolean {
  return tema === "escuro" || (tema === "sistema" && sistemaEscuro);
}

/* Só a primeira pintura. A assinatura de mudanças fica no hook, sem um
   listener antigo que volte ao tema inicial depois de uma escolha do usuário. */
export const SCRIPT_TEMA_INICIAL = `(function(){var t=${JSON.stringify(TEMA_PADRAO)};try{var s=localStorage.getItem(${JSON.stringify(CHAVE_TEMA)});if(s==="claro"||s==="escuro"||s==="sistema")t=s;}catch(e){}var escuro=t!=="claro";try{if(t==="sistema")escuro=window.matchMedia("(prefers-color-scheme: dark)").matches;}catch(e){}document.documentElement.dataset.tema=escuro?"escuro":"claro";})()`;
