"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { salvarToken } from "@/lib/auth";
import { Icone, Logomarca } from "@/components/icons";

const PONTOS = [
  "Notas encontradas e organizadas automaticamente",
  "Certificados A1 protegidos no ambiente local",
  "Alertas só quando uma ação realmente é necessária",
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
    <main className="relative grid min-h-screen overflow-hidden bg-sidebar lg:grid-cols-[minmax(0,1.05fr)_minmax(460px,.95fr)]">
      <div className="pointer-events-none absolute -left-48 -top-48 h-[520px] w-[520px] rounded-full bg-accent/20 blur-[100px]" />
      <div className="pointer-events-none absolute bottom-0 left-[28%] h-72 w-72 rounded-full bg-info/10 blur-[120px]" />

      <section className="relative hidden flex-col justify-between px-10 py-10 lg:flex xl:px-16 xl:py-14">
        <div className="flex items-center gap-3">
          <Logomarca className="h-11 w-11 rounded-[15px] text-xl" />
          <div>
            <p className="font-display text-xl font-extrabold tracking-tight text-white">NotasFlow</p>
            <p className="mt-0.5 text-[10px] font-bold uppercase tracking-[.16em] text-white/42">Operação fiscal</p>
          </div>
        </div>

        <div className="max-w-xl">
          <p className="text-[11px] font-bold uppercase tracking-[.18em] text-accent-bright">Seu centro de controle</p>
          <h1 className="mt-5 font-display text-[clamp(2.5rem,4.5vw,4.5rem)] font-extrabold leading-[.98] tracking-tight text-white">
            Fiscal no fluxo. <span className="text-accent-bright">Sem ruído.</span>
          </h1>
          <p className="mt-6 max-w-md text-base leading-7 text-white/58">
            NFS-e, NFe e CT-e chegam do ADN e da SEFAZ para o seu banco. Você acompanha apenas o que precisa de decisão.
          </p>
          <ul className="mt-9 space-y-4">
            {PONTOS.map((ponto) => (
              <li key={ponto} className="flex items-center gap-3 text-sm font-semibold text-white/78">
                <span className="flex h-6 w-6 items-center justify-center rounded-full border border-accent-bright/30 bg-accent-bright/10 text-accent-bright">
                  <Icone nome="check" className="h-3.5 w-3.5" strokeWidth={2.2} />
                </span>
                {ponto}
              </li>
            ))}
          </ul>
        </div>

        <p className="font-mono text-[10px] uppercase tracking-[.12em] text-white/28">ADN · SEFAZ · ambiente privado</p>
      </section>

      <section className="relative flex items-center justify-center bg-bg px-5 py-10 sm:px-8 lg:px-12">
        <div className="w-full max-w-[390px] animate-fade-up">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <Logomarca className="h-10 w-10 rounded-[14px]" />
            <div>
              <p className="font-display text-lg font-extrabold tracking-tight text-ink">NotasFlow</p>
              <p className="text-[10px] font-bold uppercase tracking-[.14em] text-ink-faint">Operação fiscal</p>
            </div>
          </div>

          <div>
            <p className="page-kicker">Acesso restrito</p>
            <h2 className="page-title">Entrar no espaço de trabalho</h2>
            <p className="page-description">Use as credenciais do seu escritório para abrir o painel.</p>
          </div>

          <form onSubmit={entrar} className="card-pad mt-8 p-5 sm:p-6">
            <div>
              <label className="label" htmlFor="email">E-mail</label>
              <input id="email" type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="voce@escritorio.com.br" className="input" />
            </div>
            <div className="mt-4">
              <label className="label" htmlFor="senha">Senha</label>
              <input id="senha" type="password" required autoComplete="current-password" value={senha} onChange={(e) => setSenha(e.target.value)} placeholder="Sua senha" className="input" />
            </div>

            {erro && (
              <div className="mt-4 flex items-start gap-2 rounded-xl border border-danger/20 bg-danger-soft/70 px-3 py-2.5 text-sm text-danger" role="alert">
                <Icone nome="alerta" className="mt-0.5 h-4 w-4 flex-none" />
                <p>{erro}</p>
              </div>
            )}

            <button type="submit" disabled={enviando} className="btn-primary mt-6 w-full">
              {enviando ? "Verificando acesso…" : "Entrar"}
              {!enviando && <Icone nome="setaDireita" className="h-4 w-4" />}
            </button>
          </form>

          <div className="mt-5 flex items-center justify-center gap-2 text-center text-[11px] text-ink-faint">
            <Icone nome="escudo" className="h-3.5 w-3.5" /> Acesso protegido · dados no seu ambiente
          </div>
        </div>
      </section>
    </main>
  );
}
