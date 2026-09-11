"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { salvarToken } from "@/lib/auth";
import { Icone, Logomarca } from "@/components/icons";

const DESTAQUES = [
  { icone: "raio", titulo: "Sincronismo automático", texto: "O sistema consulta a SEFAZ sozinho, dentro da janela oficial." },
  { icone: "escudo", titulo: "Cofre de certificados", texto: "Senhas cifradas, um A1 por empresa, alertas de vencimento." },
  { icone: "baixar", titulo: "Download em massa", texto: "Milhares de XMLs + relação em CSV num clique." },
];

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
    <div className="flex min-h-screen">
      {/* painel da marca */}
      <div
        className="relative hidden flex-1 flex-col justify-between overflow-hidden p-10 lg:flex"
        style={{
          backgroundImage:
            "radial-gradient(700px 500px at 15% 10%, rgba(38,208,139,.18), transparent 60%), linear-gradient(160deg, #0E1613 0%, #0A100E 60%, #070B09 100%)",
        }}
      >
        <div
          className="pointer-events-none absolute inset-0 opacity-40"
          style={{
            background:
              "radial-gradient(600px 400px at 20% 20%, rgba(47,163,122,.35), transparent), radial-gradient(500px 500px at 80% 80%, rgba(201,162,39,.18), transparent)",
          }}
        />
        {/* grade sutil */}
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.06]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.6) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.6) 1px, transparent 1px)",
            backgroundSize: "44px 44px",
          }}
        />
        <div className="relative flex items-center gap-3">
          <Logomarca className="h-11 w-11 text-xl" />
          <div>
            <p className="font-display text-2xl font-bold tracking-tight text-white">NotasFlow</p>
            <p className="text-xs font-medium uppercase tracking-widest text-accent-bright/70">
              Gestão fiscal automática
            </p>
          </div>
        </div>

        <div className="relative">
          <p className="max-w-md font-display text-[2.6rem] font-bold leading-[1.08] tracking-tight text-white">
            Todas as notas do escritório, <span className="text-accent-bright">sozinhas</span> no
            seu banco.
          </p>
          <p className="mt-4 max-w-md text-white/60">
            NFS-e, NFe e CT-e importadas direto do ADN e da SEFAZ com o certificado A1 de cada
            empresa — sem planilha, sem portal, sem F5.
          </p>
          <ul className="mt-8 space-y-4">
            {DESTAQUES.map((d) => (
              <li key={d.titulo} className="flex items-start gap-3">
                <span className="inline-flex h-9 w-9 flex-none items-center justify-center rounded-xl border border-white/10 bg-white/[0.06] text-accent-bright backdrop-blur">
                  <Icone nome={d.icone} className="h-5 w-5" />
                </span>
                <span>
                  <span className="block text-sm font-semibold text-white">{d.titulo}</span>
                  <span className="block text-sm text-white/55">{d.texto}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative font-mono text-xs text-white/35">
          ADN · SEFAZ · mTLS · Celery Beat · PostgreSQL
        </p>
      </div>

      {/* formulário */}
      <div className="relative flex flex-1 items-center justify-center px-4 py-10">
        <div className="relative w-full max-w-sm animate-fade-up">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <Logomarca />
            <p className="font-display text-2xl font-bold tracking-tight text-ink">NotasFlow</p>
          </div>

          <p className="font-display text-3xl font-bold tracking-tight text-ink">Bem-vindo de volta</p>
          <p className="mb-6 mt-1 text-sm text-ink-muted">Entre para abrir o painel do escritório.</p>

          <form onSubmit={entrar} className="card-pad">
            <label className="label" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="voce@escritorio.com.br"
              className="input mb-4"
            />

            <label className="label" htmlFor="senha">
              Senha
            </label>
            <input
              id="senha"
              type="password"
              required
              autoComplete="current-password"
              value={senha}
              onChange={(e) => setSenha(e.target.value)}
              placeholder="••••••••"
              className="input mb-5"
            />

            {erro && (
              <p className="mb-4 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
                {erro}
              </p>
            )}

            <button type="submit" disabled={enviando} className="btn-primary w-full">
              {enviando ? "Entrando…" : "Entrar no painel"}
              {!enviando && <Icone nome="setaDireita" className="h-4 w-4" />}
            </button>
          </form>

          <p className="mt-6 text-center text-xs text-ink-faint">
            Acesso restrito à equipe do escritório · v2.0
          </p>
        </div>
      </div>
    </div>
  );
}
