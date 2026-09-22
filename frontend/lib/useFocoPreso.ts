"use client";

import { useEffect, useRef, type RefObject } from "react";

const SELECIONAVEIS = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

export interface OpcoesFocoPreso {
  ativo: boolean;
  aoFechar: () => void;
  /** `primeiro` é o padrão; diálogos de perigo pedem `ultimo` (Cancelar). */
  destino?: "primeiro" | "ultimo";
  travarRolagem?: boolean;
}

function visivel(elemento: HTMLElement): boolean {
  return elemento.offsetWidth > 0 || elemento.offsetHeight > 0 || elemento.getClientRects().length > 0;
}

/**
 * Foco preso e devolvido (WCAG 2.1.2 e 2.4.3).
 *
 * Sem isto, o Tab escapa do modal para a página atrás — o operador "perde" a
 * interface e o leitor de tela anuncia conteúdo que não está mais disponível.
 * O foco volta exatamente ao gatilho que abriu a camada.
 *
 * ┌───────────────────────────────────────────────────────────────────────────┐
 * │ REGRA INVIOLÁVEL: o efeito abaixo depende SÓ de `ativo`.                   │
 * │                                                                           │
 * │ Ele contém `alvo.focus()` — mover o foco é um efeito colateral que só      │
 * │ pode acontecer na ABERTURA real da camada. Qualquer outra dependência      │
 * │ (`aoFechar`, `destino`, `travarRolagem`) é recriada a cada render do       │
 * │ componente que usa o modal: uma seta `aoFechar={() => setAberto(false)}`   │
 * │ é um objeto novo por render, o efeito reexecuta e o foco volta para o      │
 * │ primeiro focável do diálogo — o botão "Fechar" (X) do cabeçalho.           │
 * │                                                                           │
 * │ Era exatamente esse o bug do campo de senha do certificado: cada tecla     │
 * │ digitada mudava o estado da tela → novo render → nova identidade de        │
 * │ `aoFechar` → efeito de foco reexecutado → cursor roubado do input para o   │
 * │ X. O usuário precisava reclicar no campo a cada caractere.                 │
 * │                                                                           │
 * │ As três opções vivem em refs mutáveis para continuarem sempre atuais       │
 * │ dentro dos handlers, SEM entrar no array de dependências.                  │
 * └───────────────────────────────────────────────────────────────────────────┘
 */
export function useFocoPreso<T extends HTMLElement>({
  ativo,
  aoFechar,
  destino = "primeiro",
  travarRolagem = true,
}: OpcoesFocoPreso): RefObject<T | null> {
  const container = useRef<T | null>(null);
  const gatilho = useRef<HTMLElement | null>(null);

  // Espelhos sempre atualizados, lidos pelos handlers sem reexecutar o efeito.
  const aoFecharRef = useRef(aoFechar);
  const destinoRef = useRef(destino);
  const travarRolagemRef = useRef(travarRolagem);
  aoFecharRef.current = aoFechar;
  destinoRef.current = destino;
  travarRolagemRef.current = travarRolagem;

  useEffect(() => {
    if (!ativo) return;
    const elemento = container.current;
    if (!elemento) return;

    const travar = travarRolagemRef.current;
    gatilho.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflowAnterior = document.body.style.overflow;
    if (travar) document.body.style.overflow = "hidden";

    function focaveis(): HTMLElement[] {
      return Array.from(elemento?.querySelectorAll<HTMLElement>(SELECIONAVEIS) ?? []).filter(visivel);
    }

    // Marca o destino preferido com `data-foco-inicial` quando o conteúdo quer
    // decidir (ex.: campo de confirmação por digitação).
    const preferido = elemento.querySelector<HTMLElement>("[data-foco-inicial]");
    const lista = focaveis();
    const alvo = preferido ?? (destinoRef.current === "ultimo" ? (lista[lista.length - 1] ?? elemento) : (lista[0] ?? elemento));
    if (alvo === elemento) elemento.setAttribute("tabindex", "-1");
    alvo.focus();

    function aoTeclar(evento: KeyboardEvent) {
      if (evento.key === "Escape") {
        evento.stopPropagation();
        aoFecharRef.current();
        return;
      }
      if (evento.key !== "Tab") return;
      const atuais = focaveis();
      if (atuais.length === 0) {
        evento.preventDefault();
        elemento?.focus();
        return;
      }
      const primeiro = atuais[0];
      const ultimo = atuais[atuais.length - 1];
      const ativoAgora = document.activeElement;
      if (evento.shiftKey && (ativoAgora === primeiro || ativoAgora === elemento)) {
        evento.preventDefault();
        ultimo.focus();
      } else if (!evento.shiftKey && ativoAgora === ultimo) {
        evento.preventDefault();
        primeiro.focus();
      }
    }

    elemento.addEventListener("keydown", aoTeclar);
    return () => {
      elemento.removeEventListener("keydown", aoTeclar);
      if (travar) document.body.style.overflow = overflowAnterior;
      // Devolver o foco só faz sentido se o gatilho ainda existir na página.
      if (gatilho.current?.isConnected) gatilho.current.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ver bloco acima: só `ativo`.
  }, [ativo]);

  return container;
}
