"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { Botao } from "@/components/ui/Botao";
import { Entrada } from "@/components/ui/Campo";
import { CampoSenha } from "@/components/ui/CampoSenha";
import { Icone } from "@/components/ui/Icone";
import { LogoFluxa } from "@/components/ui/LogoFluxa";
import { SeletorTema } from "@/components/shell/SeletorTema";

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
      return "Não foi possível conectar ao Fluxa. Verifique se os serviços estão ativos e tente novamente.";
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
    <main className="grid min-h-dvh lg:grid-cols-2">
      <aside aria-label="Sobre o Fluxa" className="login-apresentacao relative hidden flex-col justify-between overflow-hidden p-10 lg:flex xl:p-14">
        <div aria-hidden="true" className="login-grade pointer-events-none absolute inset-0" />
        <div className="relative flex items-center gap-3">
          <span className="marca-fluxa flex h-10 w-10 items-center justify-center rounded-lg"><LogoFluxa className="h-7 w-7" /></span>
          <span className="text-[28px] font-semibold tracking-[-.04em]">fluxa<span className="text-[var(--lateral-acento)]">.</span></span>
        </div>

        <div className="relative mx-auto w-full max-w-lg py-12">
          <p className="mb-5 text-xs font-medium uppercase tracking-[.18em] text-[var(--lateral-acento)]">Sua operação, em fluxo</p>
          <h2 className="text-[42px] font-semibold leading-[1.12] tracking-[-.045em] text-sobre-grafite xl:text-[54px]">Menos tarefas.<br />Mais controle.</h2>
          <p className="mt-6 max-w-sm text-md leading-7 text-sobre-grafite/70">Da captura ao fechamento, seus documentos fiscais organizados em um único lugar.</p>

          <div className="mt-10 rounded-camada border border-grafite-traco bg-grafite-alta/80 p-6">
            <div className="mb-6 flex items-center justify-between gap-3">
              <span className="text-sm font-medium">Um fluxo. Tudo conectado.</span>
              <LogoFluxa className="h-5 w-5 text-[var(--lateral-acento)]" />
            </div>
            <ol className="space-y-5">
              {[
                { icone: "sincronizar" as const, titulo: "Captura automática", descricao: "NFS-e, NF-e e CT-e pelas fontes oficiais" },
                { icone: "pasta" as const, titulo: "Acervo organizado", descricao: "Empresas, certificados e XMLs em ordem" },
                { icone: "fechamento" as const, titulo: "Fechamento tranquilo", descricao: "Conferência e exportação por competência" },
              ].map((item, indice) => (
                <li key={item.titulo} className="flex items-center gap-4">
                  <span className="flex h-10 w-10 flex-none items-center justify-center rounded-lg border border-grafite-traco bg-grafite text-[var(--lateral-acento)]"><Icone nome={item.icone} className="h-5 w-5" /></span>
                  <span className="min-w-0 flex-1"><span className="block text-sm font-medium">{item.titulo}</span><span className="mt-1 block text-xs text-sobre-grafite/65">{item.descricao}</span></span>
                  <span aria-hidden="true" className="font-mono text-xs text-sobre-grafite/50">0{indice + 1}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>
        <p className="relative flex items-center gap-2 text-xs text-sobre-grafite/60"><Icone nome="escudo" className="h-4 w-4" />Sistema operacional fiscal · Acesso privado</p>
      </aside>

      <section className="relative flex min-h-dvh flex-col items-center justify-center bg-fundo px-5 py-20 sm:px-8 lg:px-12">
        <div className="absolute right-5 top-5 sm:right-8 sm:top-6"><SeletorTema /></div>
        <div className="w-full max-w-[440px]">
          <div className="mb-8 flex items-center justify-center gap-2.5 lg:hidden">
            <span className="marca-fluxa flex h-9 w-9 items-center justify-center rounded-lg"><LogoFluxa className="h-6 w-6" /></span>
            <span className="text-xl font-semibold tracking-tight text-tinta-forte">fluxa<span className="text-acento">.</span></span>
          </div>
          <div className="cartao-produto rounded-camada p-6 sm:p-8">
            <p className="mb-3 text-xs font-medium uppercase tracking-[.12em] text-acento">Seu espaço de trabalho</p>
            <h1 className="text-xl font-semibold text-tinta-forte">Bem-vindo de volta</h1>
            <p className="mt-2 text-sm text-tinta-suave">Entre para acompanhar sua operação fiscal.</p>

            <form className="mt-8 space-y-5" onSubmit={entrar} noValidate aria-busy={enviando}>
              <Entrada
                ref={campoEmail}
                rotulo="E-mail"
                obrigatorio
                type="email"
                inputMode="email"
                autoComplete="username"
                autoFocus
                placeholder="voce@escritorio.com.br"
                tamanho="lg"
                disabled={enviando}
                value={email}
                onChange={(evento) => setEmail(evento.target.value)}
                erro={tocado && email.trim().length === 0 ? "Informe o e-mail usado no escritório." : null}
              />
              <CampoSenha
                rotulo="Senha"
                obrigatorio
                autoComplete="current-password"
                placeholder="Sua senha de acesso"
                tamanho="lg"
                disabled={enviando}
                value={senha}
                onChange={(evento) => setSenha(evento.target.value)}
                erro={tocado && senha.length === 0 ? "Informe a senha." : null}
              />
              {erro ? (
                <p role="alert" className="flex items-start gap-2 rounded-controle border border-erro/40 bg-erro-tenue px-3 py-3 text-sm leading-6 text-erro">
                  <Icone nome="alerta" className="mt-1 h-4 w-4 flex-none" /><span>{erro}</span>
                </p>
              ) : null}
              <Botao type="submit" variante="primaria" tamanho="lg" className="w-full" carregando={enviando} iconeDireita={<Icone nome="seta-direita" className="h-4 w-4" />}>
                {enviando ? "Verificando acesso…" : "Entrar"}
              </Botao>
            </form>
            <p className="mt-6 border-t border-traco pt-5 text-center text-xs leading-5 text-tinta-suave">Precisa de acesso? Fale com o administrador do escritório.</p>
          </div>
          <p className="mt-6 flex items-center justify-center gap-2 text-xs text-tinta-suave"><Icone nome="cadeado" className="h-3.5 w-3.5" />Acesso restrito à equipe do escritório.</p>
        </div>
      </section>
    </main>
  );
}
