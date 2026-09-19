import type { PapelUsuario } from "./types";

/**
 * Papéis: a API é quem barra de verdade. Estas funções existem para a interface
 * não oferecer um clique que vai falhar — controle indisponível fica visível e
 * desabilitado, com o motivo no tooltip (esconder deixaria o operador sem saber
 * por que a ação sumiu).
 */

export function ehAdmin(papel: PapelUsuario | string | undefined): boolean {
  return papel === "admin";
}

export function podeOperar(papel: PapelUsuario | string | undefined): boolean {
  return papel === "admin" || papel === "operador";
}

export function somenteLeitura(papel: PapelUsuario | string | undefined): boolean {
  return papel === "leitura";
}

export const MOTIVO_SOMENTE_LEITURA = "Seu papel é somente leitura. Peça a um operador para executar esta ação.";

/** Rótulo humano do papel — aparece no menu do usuário e na tabela Equipe. */
export const ROTULO_PAPEL_CURTO: Record<string, string> = {
  admin: "Administrador",
  operador: "Operador",
  leitura: "Somente leitura",
};
