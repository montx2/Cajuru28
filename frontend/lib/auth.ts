const CHAVE_TOKEN = "notasflow_token";

export function salvarToken(token: string): void {
  localStorage.setItem(CHAVE_TOKEN, token);
}

export function obterToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(CHAVE_TOKEN);
}

export function limparToken(): void {
  localStorage.removeItem(CHAVE_TOKEN);
}
