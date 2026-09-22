"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { Botao } from "@/components/ui/Botao";
import { Entrada } from "@/components/ui/Campo";
import { CampoSenha } from "@/components/ui/CampoSenha";
import { Icone } from "@/components/ui/Icone";
import { LogoFluxa } from "@/components/ui/LogoFluxa";

/**
 * Destino pós-login só aceita caminho interno relativo.
 * Aceitar qualquer string transformaria o login em redirecionador aberto.
 */
function destinoSeguro(valor: string | null): string {
  if (!valor) return "/dashboard";
  return valor.startsWith("/") && !valor.startsWith("//") ? valor : "/dashboard";
}

function mensagemDe(falha: unknown): string {
  if (!(falha instanceof ApiError)) return "Não foi possível validar o acesso. Verifique os dados e tente novamente.";
  switch (falha.status) {
    case 401:
      return "E-mail ou senha incorretos. Verifique os dados do escritório e tente novamente.";
    case 403:
      return "Origem não autorizada para esta sessão. Confirme o endereço usado para acessar o Fluxa.";
    case 429:
      return "Muitas tentativas seguidas. Aguarde alguns instantes e tente novamente.";
    case 0:
      return "A API não respondeu. Verifique os serviços com `docker compose ps` e consulte `GET /saude`.";
    default:
      return falha.message;
  }
}

export function FormularioLogin() {
  const router = useRouter();
  const parametros = useSearchParams();
  const destino = destinoSeguro(parametros.get("destino"));
  const campoEmail = useRef<HTMLInputElement>(null);
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  // Validação de campo só aparece depois da primeira tentativa de envio: erro
  // antes de o usuário terminar de digitar é ruído, não ajuda.
  const [tocado, setTocado] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  // Quem já tem cookie válido não deve ver o formulário: segue para o destino.
  // A sondagem é silenciosa de propósito — sem sessão a API responde 401, que
  // aqui significa "mostre o formulário", nunca "recarregue a página".
  useEffect(() => {
    let vivo = true;
    api
      .quemSouEuSilencioso()
      .then(() => {
        if (vivo) router.replace(destino);
      })
      .catch(() => {
        if (vivo) campoEmail.current?.focus();
      });
    return () => {
      vivo = false;
    };
  }, [destino, router]);

  async function entrar(evento: React.FormEvent<HTMLFormElement>) {
    evento.preventDefault();
    setTocado(true);
    setErro(null);
    // Campo vazio é erro de formulário: resolve aqui, sem gastar uma ida à API
    // nem consumir o limite de tentativas do rate limit.
    if (email.trim().length === 0 || senha.length === 0) return;
    setEnviando(true);
    try {
      await api.login(email.trim(), senha);
      router.replace(destino);
    } catch (falha) {
      setErro(mensagemDe(falha));
      setEnviando(false);
      if (falha instanceof ApiError && falha.status === 401) campoEmail.current?.focus();
    }
  }

  return (
    <main className="flex min-h-screen items-start justify-center px-4 py-10 sm:items-center sm:py-16">
      <div className="w-full max-w-formulario">
        <div className="mb-6 flex items-center gap-2.5">
          <span aria-hidden="true" className="flex h-8 w-8 flex-none items-center justify-center rounded-controle border border-grafite-traco bg-grafite text-acento">
            <LogoFluxa className="h-4 w-4" />
          </span>
          <span className="text-base font-semibold tracking-tight text-tinta-forte">Fluxa</span>
        </div>

        <div className="vidro rounded-camada p-5 shadow-nivel1 sm:p-6">
          <h1 className="text-lg font-semibold tracking-tight text-tinta-forte">Entrar</h1>
          <p className="mt-1 text-sm text-tinta-suave">Use as credenciais do escritório. A sessão fica em cookie HttpOnly.</p>

          <form className="mt-5 space-y-4" onSubmit={entrar} noValidate aria-busy={enviando}>
            <Entrada
              ref={campoEmail}
              rotulo="E-mail"
              obrigatorio
              type="email"
              inputMode="email"
              autoComplete="username"
              autoFocus
              disabled={enviando}
              value={email}
              onChange={(evento) => setEmail(evento.target.value)}
              erro={tocado && email.trim().length === 0 ? "Informe o e-mail usado no escritório." : null}
            />

            <CampoSenha
              rotulo="Senha"
              obrigatorio
              autoComplete="current-password"
              disabled={enviando}
              value={senha}
              onChange={(evento) => setSenha(evento.target.value)}
              erro={tocado && senha.length === 0 ? "Informe a senha." : null}
            />

            {erro ? (
              <p role="alert" className="flex items-start gap-2 rounded-controle border border-erro/40 bg-erro-tenue px-3 py-2.5 text-sm leading-6 text-erro">
                <Icone nome="alerta" className="mt-1 h-4 w-4 flex-none" />
                <span>{erro}</span>
              </p>
            ) : null}

            <Botao type="submit" variante="primaria" tamanho="lg" className="w-full" carregando={enviando}>
              {enviando ? "Verificando acesso…" : "Entrar"}
            </Botao>
          </form>
        </div>

        <p className="mt-4 text-xs leading-5 text-tinta-fraca">
          Ambiente privado. O acesso fica registrado em auditoria com usuário, ação e horário.
        </p>
      </div>
    </main>
  );
}
