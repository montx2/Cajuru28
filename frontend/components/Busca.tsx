"use client";

import { useEffect, useRef } from "react";
import { Icone } from "./icons";

/**
 * Peças de busca e filtro usadas em todas as listas do painel.
 *
 * Por que um componente (e não um <input> copiado em cada tela): a busca
 * precisa se comportar igual em toda parte — ícone, botão de limpar, Enter
 * aplica na hora, Esc limpa — e o debounce evita uma consulta à API por
 * tecla digitada. Cada tela que ganha "um input rapidinho" sem isso termina
 * com uma UX diferente da vizinha, e é isso que faz um painel parecer
 * amador.
 */

/** Campo de busca com ícone, limpar, Enter (aplica) e Esc (limpa). */
export function BuscaInput({
  valor,
  aoMudar,
  /** Chamado com o termo já aparado. Sem isso, a busca é puramente controlada. */
  aoBuscar,
  /** Atraso da aplicação automática, em ms (padrão 400). 0 desliga o debounce. */
  atraso = 400,
  placeholder = "Buscar…",
  className = "",
  dicaTecla,
  autoFoco = false,
  ariaLabel = "Buscar",
}: {
  valor: string;
  aoMudar: (valor: string) => void;
  aoBuscar?: (termo: string) => void;
  atraso?: number;
  placeholder?: string;
  className?: string;
  dicaTecla?: string;
  autoFoco?: boolean;
  ariaLabel?: string;
}) {
  const referencia = useRef<HTMLInputElement>(null);

  // Debounce: enquanto a pessoa digita, nada sai da tela; quando ela para,
  // o termo é aplicado uma única vez.
  useEffect(() => {
    if (!aoBuscar || atraso <= 0) return;
    const temporizador = window.setTimeout(() => aoBuscar(valor.trim()), atraso);
    return () => window.clearTimeout(temporizador);
  }, [valor, aoBuscar, atraso]);

  return (
    <div className={`relative ${className}`}>
      <Icone
        nome="busca"
        className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint"
      />
      <input
        ref={referencia}
        type="search"
        value={valor}
        onChange={(e) => aoMudar(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && aoBuscar) {
            e.preventDefault();
            aoBuscar(valor.trim());
          }
          if (e.key === "Escape") {
            aoMudar("");
            if (aoBuscar) aoBuscar("");
            referencia.current?.blur();
          }
        }}
        placeholder={placeholder}
        aria-label={ariaLabel}
        autoComplete="off"
        /* `search` nativo tem um "x" próprio que duplicaria o botão abaixo */
        className="input h-10 pl-10 pr-9 [&::-webkit-search-cancel-button]:hidden [&::-webkit-search-decoration]:hidden"
        autoFocus={autoFoco}
      />
      {valor && (
        <button
          type="button"
          onClick={() => {
            aoMudar("");
            if (aoBuscar) aoBuscar("");
            referencia.current?.focus();
          }}
          className="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-ink-faint transition-colors hover:bg-bg-deep hover:text-ink"
          aria-label="Limpar busca"
        >
          <Icone nome="x" className="h-3.5 w-3.5" />
        </button>
      )}
      {dicaTecla && !valor && (
        <span className="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 rounded-md border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink-faint md:block">
          {dicaTecla}
        </span>
      )}
    </div>
  );
}

export interface OpcaoChipFiltro {
  id: string;
  rotulo: string;
  /** Contador ao lado do rótulo (ex.: "Sem certificado · 12"). */
  contador?: number;
}

/**
 * Chips de filtro — a versão "profissional" de abas de rádio: cada opção é
 * mutuamente exclusiva, mostra a contagem do grupo e a ativa fica evidente.
 * Usada em Empresas, Certificados e no seletor de importação.
 */
export function ChipsFiltro({
  opcoes,
  valor,
  aoMudar,
  rotuloGrupo,
}: {
  opcoes: OpcaoChipFiltro[];
  valor: string;
  aoMudar: (valor: string) => void;
  rotuloGrupo: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={rotuloGrupo}
      className="flex flex-wrap items-center gap-1.5"
    >
      {opcoes.map((opcao) => {
        const ativo = opcao.id === valor;
        return (
          <button
            key={opcao.id}
            type="button"
            role="tab"
            aria-selected={ativo}
            onClick={() => aoMudar(opcao.id)}
            className={`inline-flex items-center gap-1.5 rounded-pill border px-3 py-1.5 text-xs font-bold transition-[background,color,border-color] duration-150 ${
              ativo
                ? "border-accent bg-accent text-white shadow-sm"
                : "border-line bg-surface text-ink-muted hover:border-line-strong hover:text-ink"
            }`}
          >
            {opcao.rotulo}
            {opcao.contador !== undefined && (
              <span
                className={`rounded-pill px-1.5 py-px font-mono text-[10px] ${
                  ativo ? "bg-white/20 text-white" : "bg-bg-deep text-ink-muted"
                }`}
              >
                {opcao.contador}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Contador discreto usado ao lado das listas: "X de Y no filtro". */
export function ContadorLista({
  visiveis,
  total,
  rotulo = "no filtro",
}: {
  visiveis: number;
  total: number;
  rotulo?: string;
}) {
  return (
    <span className="text-xs text-ink-muted">
      {visiveis} {visiveis === 1 ? "item" : "itens"} {rotulo}
      {total > 0 && visiveis !== total ? ` · ${total} no total` : ""}
    </span>
  );
}
