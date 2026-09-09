"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { salvarToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function entrar(evento: React.FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      const { access_token } = await api.login(email, senha);
      salvarToken(access_token);
      router.push("/dashboard");
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Não foi possível entrar. Tente novamente.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <p className="mb-8 font-serif text-2xl text-ink">NotasFlow</p>

        <form onSubmit={entrar} className="border border-line bg-surface p-6">
          <label className="mb-1 block text-sm text-ink-muted" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mb-4 w-full border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />

          <label className="mb-1 block text-sm text-ink-muted" htmlFor="senha">
            Senha
          </label>
          <input
            id="senha"
            type="password"
            required
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            className="mb-5 w-full border border-line bg-bg px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />

          {erro && (
            <p className="mb-4 border border-danger-soft bg-danger-soft px-3 py-2 text-sm text-danger">
              {erro}
            </p>
          )}

          <button
            type="submit"
            disabled={enviando}
            className="w-full bg-accent px-3 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {enviando ? "Entrando…" : "Entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}
