"use client";

import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { cn } from "@/lib/cn";
import { Icone } from "./Icone";

/* ── Estrutura compartilhada ─────────────────────────────────────────────── */

export interface CampoBase {
  rotulo: string;
  /** Texto de apoio permanente. Não substitui o rótulo. */
  descricao?: ReactNode;
  /** 3.3.1: o erro fica junto do campo, diz o que houve e como corrigir. */
  erro?: string | null;
  /** Contexto neutro (ex.: "via ReceitaWS"). Não é erro nem aviso de estado. */
  nota?: ReactNode;
  obrigatorio?: boolean;
  /** Ação ao lado do rótulo (ex.: "Consultar CNPJ"). */
  acaoRotulo?: ReactNode;
  className?: string;
  classeControle?: string;
}

const CONTROLE =
  "w-full rounded-controle border border-borda-controle bg-superficie px-2.5 text-sm text-tinta outline-none " +
  "transition-[border-color,background-color] duration-120 ease-produto placeholder:text-tinta-suave " +
  "hover:border-tinta-suave focus:border-acento disabled:cursor-not-allowed disabled:border-traco-forte " +
  "disabled:bg-fundo-afundado disabled:text-tinta-suave";

const ALTURAS = { sm: "h-8 text-xs", md: "h-9" } as const;
export type TamanhoCampo = keyof typeof ALTURAS;

function idsDoCampo(id: string, descricao?: ReactNode, erro?: string | null, nota?: ReactNode) {
  const partes: string[] = [];
  if (descricao) partes.push(`${id}-descricao`);
  if (nota) partes.push(`${id}-nota`);
  if (erro) partes.push(`${id}-erro`);
  return partes.length ? partes.join(" ") : undefined;
}

export interface CampoProps extends CampoBase {
  id?: string;
  /** Recebe o id gerado para associar o controle manualmente. */
  children: (id: string, descritoPor: string | undefined) => ReactNode;
}

/** Casca de campo: rótulo real, apoio, erro e a fiação ARIA entre eles. */
export function Campo({ rotulo, descricao, erro, nota, obrigatorio, acaoRotulo, className, id, children }: CampoProps) {
  const gerado = useId();
  const campoId = id ?? gerado;
  const descritoPor = idsDoCampo(campoId, descricao, erro, nota);

  return (
    <div className={cn("min-w-0", className)}>
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <label className="text-xs font-medium text-tinta" htmlFor={campoId}>
          {rotulo}
          {obrigatorio ? (
            <span className="text-erro" title="Campo obrigatório">
              {" "}
              *
            </span>
          ) : null}
        </label>
        {acaoRotulo}
      </div>
      {children(campoId, descritoPor)}
      {descricao ? (
        <p id={`${campoId}-descricao`} className="mt-1 text-xs leading-5 text-tinta-suave">
          {descricao}
        </p>
      ) : null}
      {nota ? (
        <p id={`${campoId}-nota`} className="mt-1 text-xs leading-5 text-tinta-suave">
          {nota}
        </p>
      ) : null}
      {erro ? (
        <p id={`${campoId}-erro`} role="alert" className="mt-1 flex items-start gap-1.5 text-xs leading-5 text-erro">
          <Icone nome="alerta" className="mt-0.5 h-3.5 w-3.5 flex-none" />
          <span>{erro}</span>
        </p>
      ) : null}
    </div>
  );
}

/* ── Entrada de texto ────────────────────────────────────────────────────── */

export interface EntradaProps extends CampoBase, Omit<InputHTMLAttributes<HTMLInputElement>, "className"> {
  tamanho?: TamanhoCampo;
  prefixo?: ReactNode;
  sufixo?: ReactNode;
  /** Alinha à direita e ativa números tabulares (valores, NSU, quantidades). */
  numerico?: boolean;
  mono?: boolean;
}

export const Entrada = forwardRef<HTMLInputElement, EntradaProps>(function Entrada(
  { rotulo, descricao, erro, nota, obrigatorio, acaoRotulo, className, classeControle, tamanho = "md", prefixo, sufixo, numerico, mono, id, ...props },
  ref
) {
  return (
    <Campo rotulo={rotulo} descricao={descricao} erro={erro} nota={nota} obrigatorio={obrigatorio} acaoRotulo={acaoRotulo} className={className} id={id}>
      {(campoId, descritoPor) => (
        <div
          className={cn(
            "flex items-stretch overflow-hidden rounded-controle border bg-superficie transition-[border-color] duration-120 focus-within:border-acento",
            erro ? "border-erro" : "border-borda-controle hover:border-tinta-suave",
            props.disabled && "cursor-not-allowed border-traco-forte bg-fundo-afundado"
          )}
        >
          {prefixo ? (
            <span className="flex items-center border-r border-traco bg-fundo-afundado px-2 text-xs text-tinta-suave">{prefixo}</span>
          ) : null}
          <input
            ref={ref}
            id={campoId}
            aria-describedby={descritoPor}
            aria-invalid={Boolean(erro) || undefined}
            className={cn(
              "min-w-0 flex-1 border-0 bg-transparent px-2.5 text-sm text-tinta outline-none placeholder:text-tinta-suave disabled:cursor-not-allowed disabled:text-tinta-suave",
              ALTURAS[tamanho],
              numerico && "text-right nums",
              mono && "font-mono text-xs tracking-tight",
              classeControle
            )}
            {...props}
          />
          {sufixo ? <span className="flex items-center pr-1.5 text-tinta-suave">{sufixo}</span> : null}
        </div>
      )}
    </Campo>
  );
});

/* ── Busca com limpar e atalho `/` ───────────────────────────────────────── */

export interface BuscaProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "className" | "onChange" | "value"> {
  valor: string;
  aoMudar: (valor: string) => void;
  rotulo?: string;
  /** Marca o campo como alvo da tecla `/` — um por tela. */
  alvoDoAtalho?: boolean;
  className?: string;
  tamanho?: TamanhoCampo;
  /**
   * Mostra o rótulo acima do campo, como nos demais controles.
   *
   * Numa linha de filtros a busca fica ao lado de `Selecao`/`Combobox`, que
   * sempre têm rótulo visível. Sem isto a busca sobe ~20px e o conjunto fica
   * visivelmente desalinhado — o `items-end` do contêiner só disfarça quando
   * todos os campos têm a mesma altura de rótulo.
   */
  rotuloVisivel?: boolean;
}

/**
 * Busca de tabela: rótulo para leitor de tela, botão limpar que só aparece com
 * conteúdo, e `data-atalho-filtro` para a tecla `/` achar o campo da tela.
 */
export const Busca = forwardRef<HTMLInputElement, BuscaProps>(function Busca(
  { valor, aoMudar, rotulo = "Buscar", alvoDoAtalho = true, className, tamanho = "md", rotuloVisivel = false, id, ...props },
  ref
) {
  const gerado = useId();
  const campoId = id ?? gerado;
  // A lupa é desenhada dentro do campo: o texto precisa começar depois dela.
  // esquerda(10px) + ícone(16px) + respiro(8px) = 34px  → pl-[2.125rem]
  // No tamanho `sm` o ícone encolhe para 14px → 10+14+6 = 30px.
  const recuoTexto = tamanho === "sm" ? "pl-[1.875rem]" : "pl-[2.125rem]";
  return (
    <div className={cn("min-w-0", className)}>
      {rotuloVisivel ? (
        <div className="mb-1.5 flex items-baseline justify-between gap-3">
          <label className="text-xs font-medium text-tinta" htmlFor={campoId}>
            {rotulo}
          </label>
        </div>
      ) : (
        <label className="sr-only" htmlFor={campoId}>
          {rotulo}
        </label>
      )}
      <div className="relative min-w-0">
        <Icone
          nome="busca"
          className={cn(
            "pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-tinta-suave",
            tamanho === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"
          )}
        />
        <input
          ref={ref}
          id={campoId}
          type="search"
          role="searchbox"
          value={valor}
          onChange={(evento) => aoMudar(evento.target.value)}
          data-atalho-filtro={alvoDoAtalho ? "" : undefined}
          className={cn(
            CONTROLE,
            ALTURAS[tamanho],
            recuoTexto,
            // O botão limpar ocupa 28px a partir de 4px da borda: o texto tem
            // de parar em 36px, senão encosta no X ao digitar frases longas.
            valor && "pr-9",
            "[&::-webkit-search-cancel-button]:appearance-none"
          )}
          {...props}
        />
        {valor ? (
          <button
            type="button"
            aria-label="Limpar busca"
            onClick={() => aoMudar("")}
            className="absolute right-1 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-badge text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta-forte"
          >
            <Icone nome="fechar" className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
    </div>
  );
});

/* ── Área de texto ───────────────────────────────────────────────────────── */

export interface AreaProps extends CampoBase, Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "className"> {
  mono?: boolean;
}

export const Area = forwardRef<HTMLTextAreaElement, AreaProps>(function Area(
  { rotulo, descricao, erro, nota, obrigatorio, acaoRotulo, className, classeControle, mono, id, rows = 3, ...props },
  ref
) {
  return (
    <Campo rotulo={rotulo} descricao={descricao} erro={erro} nota={nota} obrigatorio={obrigatorio} acaoRotulo={acaoRotulo} className={className} id={id}>
      {(campoId, descritoPor) => (
        <textarea
          ref={ref}
          id={campoId}
          rows={rows}
          aria-describedby={descritoPor}
          aria-invalid={Boolean(erro) || undefined}
          className={cn(CONTROLE, "resize-y py-2 leading-6", mono && "font-mono text-xs", erro && "border-erro", classeControle)}
          {...props}
        />
      )}
    </Campo>
  );
});

/* ── Seleção ─────────────────────────────────────────────────────────────── */

export interface OpcaoSelecao {
  valor: string;
  rotulo: string;
  desabilitada?: boolean;
}

export interface SelecaoProps extends CampoBase, Omit<SelectHTMLAttributes<HTMLSelectElement>, "className"> {
  opcoes: OpcaoSelecao[];
  tamanho?: TamanhoCampo;
}

/** `select` nativo: teclado, leitor de tela e mobile já vêm resolvidos. */
export const Selecao = forwardRef<HTMLSelectElement, SelecaoProps>(function Selecao(
  { rotulo, descricao, erro, nota, obrigatorio, acaoRotulo, className, classeControle, opcoes, tamanho = "md", id, ...props },
  ref
) {
  return (
    <Campo rotulo={rotulo} descricao={descricao} erro={erro} nota={nota} obrigatorio={obrigatorio} acaoRotulo={acaoRotulo} className={className} id={id}>
      {(campoId, descritoPor) => (
        <div className="relative">
          <select
            ref={ref}
            id={campoId}
            aria-describedby={descritoPor}
            aria-invalid={Boolean(erro) || undefined}
            className={cn(CONTROLE, ALTURAS[tamanho], "cursor-pointer appearance-none pr-8", erro && "border-erro", classeControle)}
            {...props}
          >
            {opcoes.map((opcao) => (
              <option key={opcao.valor} value={opcao.valor} disabled={opcao.desabilitada}>
                {opcao.rotulo}
              </option>
            ))}
          </select>
          <Icone
            nome="chevron-baixo"
            className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-tinta-suave"
          />
        </div>
      )}
    </Campo>
  );
});

/* ── Checkbox ────────────────────────────────────────────────────────────── */

export interface CaixaProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  rotulo: ReactNode;
  descricao?: ReactNode;
  indeterminado?: boolean;
  /** Alvo de 40 px: o box tem 16 px, mas a área clicável é a linha inteira. */
  compacta?: boolean;
}

export const Caixa = forwardRef<HTMLInputElement, CaixaProps>(function Caixa(
  { rotulo, descricao, indeterminado = false, compacta = false, className, disabled, ...props },
  ref
) {
  const interno = useRef<HTMLInputElement | null>(null);

  // `indeterminate` é propriedade DOM, não atributo: só existe via ref.
  useEffect(() => {
    if (interno.current) interno.current.indeterminate = indeterminado && !props.checked;
  }, [indeterminado, props.checked]);

  function definirRef(node: HTMLInputElement | null) {
    interno.current = node;
    if (typeof ref === "function") ref(node);
    else if (ref) ref.current = node;
  }

  return (
    <label
      className={cn(
        "flex cursor-pointer items-start gap-2.5 rounded-controle px-1 transition-colors duration-120 hover:bg-fundo-afundado",
        compacta ? "min-h-8 py-1.5" : "min-h-10 py-2",
        disabled && "cursor-not-allowed opacity-55 hover:bg-transparent",
        className
      )}
    >
      <input
        ref={definirRef}
        type="checkbox"
        disabled={disabled}
        className="mt-0.5 h-4 w-4 flex-none cursor-pointer accent-acento disabled:cursor-not-allowed"
        {...props}
      />
      <span className="min-w-0 text-sm leading-5 text-tinta">
        {rotulo}
        {descricao ? <span className="mt-0.5 block text-xs leading-5 text-tinta-suave">{descricao}</span> : null}
      </span>
    </label>
  );
});

/* ── Radio ───────────────────────────────────────────────────────────────── */

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  rotulo: ReactNode;
  descricao?: ReactNode;
}

export const Radio = forwardRef<HTMLInputElement, RadioProps>(function Radio(
  { rotulo, descricao, className, disabled, ...props },
  ref
) {
  return (
    <label
      className={cn(
        "flex min-h-10 cursor-pointer items-start gap-2.5 rounded-controle px-2 py-2 transition-colors duration-120 hover:bg-fundo-afundado",
        disabled && "cursor-not-allowed opacity-55 hover:bg-transparent",
        className
      )}
    >
      <input ref={ref} type="radio" disabled={disabled} className="mt-0.5 h-4 w-4 flex-none cursor-pointer accent-acento disabled:cursor-not-allowed" {...props} />
      <span className="min-w-0 text-sm leading-5 text-tinta">
        {rotulo}
        {descricao ? <span className="mt-0.5 block text-xs leading-5 text-tinta-suave">{descricao}</span> : null}
      </span>
    </label>
  );
});

export interface GrupoRadioProps {
  rotulo: string;
  descricao?: string;
  name: string;
  valor: string;
  aoMudar: (valor: string) => void;
  opcoes: OpcaoSelecao[];
  className?: string;
  /** true = linha única (segmented control); false = coluna. */
  horizontal?: boolean;
}

/** Radiogroup com navegação por setas — o padrão APG, não uma lista de divs. */
export function GrupoRadio({ rotulo, descricao, name, valor, aoMudar, opcoes, className, horizontal = true }: GrupoRadioProps) {
  function aoTeclar(evento: React.KeyboardEvent<HTMLDivElement>) {
    const habilitadas = opcoes.filter((opcao) => !opcao.desabilitada);
    if (habilitadas.length < 2) return;
    const indice = habilitadas.findIndex((opcao) => opcao.valor === valor);
    let proximo = indice;
    if (evento.key === "ArrowRight" || evento.key === "ArrowDown") proximo = (indice + 1) % habilitadas.length;
    else if (evento.key === "ArrowLeft" || evento.key === "ArrowUp") proximo = (indice - 1 + habilitadas.length) % habilitadas.length;
    else if (evento.key === "Home") proximo = 0;
    else if (evento.key === "End") proximo = habilitadas.length - 1;
    else return;
    evento.preventDefault();
    aoMudar(habilitadas[proximo].valor);
    const alvo = document.getElementById(`${name}-${habilitadas[proximo].valor}`);
    alvo?.focus();
  }

  return (
    <fieldset className={cn("min-w-0", className)}>
      <legend className="mb-1.5 text-xs font-medium text-tinta">
        {rotulo}
        {descricao ? <span className="ml-2 font-normal text-tinta-suave">{descricao}</span> : null}
      </legend>
      <div role="radiogroup" aria-label={rotulo} onKeyDown={aoTeclar} className={cn(horizontal ? "flex flex-wrap gap-1" : "flex flex-col")}>
        {opcoes.map((opcao) => {
          const ativo = opcao.valor === valor;
          return (
            <label
              key={opcao.valor}
              htmlFor={`${name}-${opcao.valor}`}
              className={cn(
                "flex min-h-9 cursor-pointer items-center gap-2 rounded-controle border px-2.5 text-sm transition-colors duration-120",
                ativo
                  ? "border-acento bg-acento-tenue font-medium text-acento-escuro"
                  : "border-borda-controle bg-superficie text-tinta-suave hover:border-tinta-suave hover:text-tinta",
                opcao.desabilitada && "cursor-not-allowed opacity-55"
              )}
            >
              <input
                id={`${name}-${opcao.valor}`}
                type="radio"
                name={name}
                value={opcao.valor}
                checked={ativo}
                disabled={opcao.desabilitada}
                onChange={() => aoMudar(opcao.valor)}
                onFocus={() => aoMudar(opcao.valor)}
                tabIndex={ativo || (!valor && opcao === opcoes[0]) ? 0 : -1}
                className="sr-only"
              />
              {opcao.rotulo}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

/* ── Alternador (switch) ─────────────────────────────────────────────────── */

export interface AlternadorProps {
  rotulo: string;
  descricao?: ReactNode;
  ligado: boolean;
  aoMudar: (ligado: boolean) => void;
  desabilitado?: boolean;
  /** Explicação exibida quando o controle está indisponível (papel/estado). */
  motivoDesabilitado?: string;
  className?: string;
  /** Otimismo: mostra o estado pendente sem desligar o controle. */
  pendente?: boolean;
}

export function Alternador({ rotulo, descricao, ligado, aoMudar, desabilitado, motivoDesabilitado, className, pendente }: AlternadorProps) {
  return (
    <div className={cn("flex items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <p id={`${rotulo.replace(/\s+/g, "-").toLowerCase()}-rotulo`} className="text-sm font-medium text-tinta">
          {rotulo}
        </p>
        {descricao ? <p className="mt-0.5 text-xs leading-5 text-tinta-suave">{descricao}</p> : null}
        {desabilitado && motivoDesabilitado ? (
          <p className="mt-0.5 text-xs leading-5 text-tinta-suave">{motivoDesabilitado}</p>
        ) : null}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={ligado}
        aria-label={rotulo}
        disabled={desabilitado}
        onClick={() => aoMudar(!ligado)}
        className={cn(
          "relative mt-0.5 h-6 w-11 flex-none rounded-full border transition-colors duration-120 ease-produto",
          "disabled:cursor-not-allowed disabled:opacity-50",
          ligado ? "border-acento bg-acento" : "border-borda-controle bg-fundo-afundado"
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-superficie shadow-nivel1 transition-transform duration-120 ease-produto",
            ligado ? "translate-x-6" : "translate-x-1"
          )}
        />
        {pendente ? <span aria-hidden="true" className="absolute inset-0 animate-pulso rounded-full" /> : null}
      </button>
    </div>
  );
}
