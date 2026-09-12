"use client";

/**
 * A sessão é um cookie HttpOnly emitido pela API. Este módulo existe apenas
 * para compatibilidade de imports antigos: nenhum token é acessível ao
 * JavaScript, ao localStorage ou ao sessionStorage.
 */
export function limparToken(): void {
  // Não há token no browser para apagar. O logout real chama /auth/logout.
}
