"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { Campo, type CampoBase, type TamanhoCampo } from "./Campo";
import { Icone } from "./Icone";

export interface OpcaoCombobox {
  valor: string;
  rotulo: string;
  /** Segunda linha da opção (CNPJ, situação, contagem). */
  descricao?: string;
  desabilitada?: boolean;
}

export interface ComboboxProps extends CampoBase {
  opcoes: OpcaoCombobox[];
  valor: string;
  aoMudar: (valor: string) => void;
  placeholder?: string;
  /** Mensagem quando a busca não casa com nada — instrução, não "vazio". */
  vazio?: string;
  tamanho?: TamanhoCampo;
  carregando?: boolean;
  permiteLimpar?: boolean;
  id?: string;
}

/**
 * Combobox editável (padrão ARIA completo: `role="combobox"` + `listbox`).
 * Existe porque com 1.000 empresas um `select` nativo vira uma rolagem
 * interminável — aqui o operador digita três letras e escolhe.
 */
export function Combobox({
  opcoes,
  valor,
  aoMudar,
  placeholder = "Buscar…",
  vazio = "Nada encontrado com esse termo.",
  rotulo,
  descricao,
  erro,
  nota,
  obrigatorio,
  acaoRotulo,
  className,
  tamanho = "md",
  carregando = false,
  permiteLimpar = true,
  id,
}: ComboboxProps) {
  const gerado = useId();
  const campoId = id ?? gerado;
  const idLista = `${campoId}-lista`;
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState("");
  const [ativo, setAtivo] = useState(-1);
  const container = useRef<HTMLDivElement>(null);
  const entrada = useRef<HTMLInputElement>(null);

  const selecionada = useMemo(() => opcoes.find((opcao) => opcao.valor === valor) ?? null, [opcoes, valor]);

  const filtradas = useMemo(() => {
    const termo = busca.trim().toLocaleLowerCase("pt-BR");
    if (!termo) return opcoes;
    return opcoes.filter((opcao) =>
      `${opcao.rotulo} ${opcao.descricao ?? ""}`.toLocaleLowerCase("pt-BR").includes(termo)
    );
  }, [busca, opcoes]);

  useEffect(() => {
    if (!aberto) return;
    function aoClicarFora(evento: MouseEvent) {
      if (container.current && !container.current.contains(evento.target as Node)) {
        setAberto(false);
        setBusca("");
      }
    }
    document.addEventListener("mousedown", aoClicarFora);
    return () => document.removeEventListener("mousedown", aoClicarFora);
  }, [aberto]);

  useEffect(() => {
    if (!aberto) return;
    const indice = filtradas.findIndex((opcao) => opcao.valor === valor);
    setAtivo(indice >= 0 ? indice : filtradas.length ? 0 : -1);
  }, [aberto, filtradas, valor]);

  useEffect(() => {
    if (!aberto || ativo < 0) return;
    const elemento = document.getElementById(`${idLista}-opcao-${ativo}`);
    elemento?.scrollIntoView({ block: "nearest" });
  }, [aberto, ativo, idLista]);

  function escolher(opcao: OpcaoCombobox) {
    if (opcao.desabilitada) return;
    aoMudar(opcao.valor);
    setAberto(false);
    setBusca("");
    entrada.current?.focus();
  }

  function aoTeclar(evento: React.KeyboardEvent<HTMLInputElement>) {
    if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
      evento.preventDefault();
      if (!aberto) {
        setAberto(true);
        return;
      }
      if (!filtradas.length) return;
      const passo = evento.key === "ArrowDown" ? 1 : -1;
      setAtivo((atual) => {
        let proximo = atual + passo;
        while (proximo >= 0 && proximo < filtradas.length && filtradas[proximo].desabilitada) proximo += passo;
        if (proximo < 0) proximo = filtradas.length - 1;
        if (proximo >= filtradas.length) proximo = 0;
        return proximo;
      });
      return;
    }
    if (evento.key === "Enter") {
      if (aberto && ativo >= 0 && filtradas[ativo]) {
        evento.preventDefault();
        escolher(filtradas[ativo]);
      }
      return;
    }
    if (evento.key === "Escape") {
      if (aberto) {
        evento.preventDefault();
        evento.stopPropagation();
        setAberto(false);
        setBusca("");
      }
      return;
    }
    if (evento.key === "Tab") setAberto(false);
    if (evento.key === "Home" && aberto) {
      evento.preventDefault();
      setAtivo(0);
    }
    if (evento.key === "End" && aberto) {
      evento.preventDefault();
      setAtivo(filtradas.length - 1);
    }
  }

  return (
    <Campo
      rotulo={rotulo}
      descricao={descricao}
      erro={erro}
      nota={nota}
      obrigatorio={obrigatorio}
      acaoRotulo={acaoRotulo}
      className={className}
      id={campoId}
    >
      {(_, descritoPor) => (
        <div ref={container} className="relative">
          <div
            className={cn(
              "flex items-center gap-1 rounded-controle border bg-superficie pr-1 transition-[border-color] duration-120",
              erro ? "border-erro" : aberto ? "border-acento" : "border-borda-controle hover:border-tinta-suave"
            )}
          >
            {/* O combobox é um campo em que se digita para filtrar, igual à
                Busca — sem a lupa ele parecia um `select` e o operador não
                percebia que dava para pesquisar com 1.000 empresas na lista. */}
            <Icone
              nome="busca"
              className={cn(
                "pointer-events-none ml-2.5 flex-none text-tinta-suave",
                tamanho === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"
              )}
            />
            <input
              ref={entrada}
              id={campoId}
              type="text"
              role="combobox"
              autoComplete="off"
              aria-expanded={aberto}
              aria-controls={idLista}
              aria-autocomplete="list"
              aria-activedescendant={aberto && ativo >= 0 ? `${idLista}-opcao-${ativo}` : undefined}
              aria-describedby={descritoPor}
              aria-invalid={Boolean(erro) || undefined}
              placeholder={aberto ? placeholder : (selecionada?.rotulo ?? placeholder)}
              value={aberto ? busca : (selecionada?.rotulo ?? "")}
              onChange={(evento) => {
                setBusca(evento.target.value);
                setAberto(true);
              }}
              onFocus={() => setAberto(true)}
              onClick={() => setAberto(true)}
              onKeyDown={aoTeclar}
              className={cn(
                // `pl-0`: o recuo agora vem da lupa à esquerda; manter px-2.5
                // abriria um vão duplo entre o ícone e o texto.
                "min-w-0 flex-1 rounded-controle bg-transparent pl-2 pr-1 text-sm text-tinta outline-none placeholder:text-tinta-suave",
                tamanho === "sm" ? "h-8 text-xs" : "h-9"
              )}
            />
            {permiteLimpar && valor && !aberto ? (
              <button
                type="button"
                aria-label={`Limpar ${rotulo}`}
                onClick={() => {
                  aoMudar("");
                  entrada.current?.focus();
                }}
                className="flex h-7 w-7 flex-none items-center justify-center rounded-badge text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta-forte"
              >
                <Icone nome="fechar" className="h-3.5 w-3.5" />
              </button>
            ) : null}
            <button
              type="button"
              tabIndex={-1}
              aria-hidden="true"
              onClick={() => {
                setAberto((atual) => !atual);
                entrada.current?.focus();
              }}
              className="flex h-8 w-7 flex-none items-center justify-center rounded-badge text-tinta-suave"
            >
              <Icone nome={aberto ? "chevron-cima" : "chevron-baixo"} className="h-4 w-4" />
            </button>
          </div>

          {aberto ? (
            <div className="absolute left-0 right-0 top-full z-camada mt-1 overflow-hidden rounded-cartao border border-traco bg-superficie shadow-nivel1 animate-subir">
              <ul id={idLista} role="listbox" aria-label={rotulo} className="rolagem-fina max-h-72 overflow-y-auto py-1">
                {carregando ? (
                  <li className="px-3 py-2 text-sm text-tinta-suave" role="presentation">
                    Carregando opções…
                  </li>
                ) : filtradas.length === 0 ? (
                  <li className="px-3 py-3 text-sm text-tinta-suave" role="presentation">
                    {vazio}
                  </li>
                ) : (
                  filtradas.map((opcao, indice) => {
                    const marcada = opcao.valor === valor;
                    return (
                      <li
                        key={opcao.valor}
                        id={`${idLista}-opcao-${indice}`}
                        role="option"
                        aria-selected={marcada}
                        aria-disabled={opcao.desabilitada || undefined}
                        onMouseEnter={() => setAtivo(indice)}
                        onMouseDown={(evento) => {
                          // `mousedown` para não perder o foco do input antes do clique.
                          evento.preventDefault();
                          escolher(opcao);
                        }}
                        className={cn(
                          "flex cursor-pointer items-start gap-2 px-2.5 py-1.5 text-sm",
                          indice === ativo && "bg-fundo-afundado",
                          opcao.desabilitada && "cursor-not-allowed opacity-55"
                        )}
                      >
                        <Icone
                          nome="verificar"
                          className={cn("mt-0.5 h-3.5 w-3.5 flex-none", marcada ? "text-acento" : "text-transparent")}
                        />
                        <span className="min-w-0 flex-1">
                          <span className={cn("block truncate", marcada && "font-medium text-tinta-forte")}>{opcao.rotulo}</span>
                          {opcao.descricao ? (
                            <span className="block truncate text-xs text-tinta-suave">{opcao.descricao}</span>
                          ) : null}
                        </span>
                      </li>
                    );
                  })
                )}
              </ul>
              {filtradas.length > 0 && busca ? (
                <p className="border-t border-traco px-3 py-1.5 text-xs text-tinta-suave nums">
                  {filtradas.length} de {opcoes.length} opções
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </Campo>
  );
}
