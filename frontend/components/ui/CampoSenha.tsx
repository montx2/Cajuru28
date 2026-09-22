"use client";

import { forwardRef, useId, useState } from "react";
import { Entrada, type EntradaProps } from "./Campo";
import { Icone } from "./Icone";

export type CampoSenhaProps = Omit<EntradaProps, "type" | "sufixo">;

/**
 * Campo de senha com alternância mostrar/ocultar.
 *
 * Existe como componente próprio porque senha aparece em três contextos
 * (login, certificado A1, usuários) e nos três o operador precisa conferir o
 * que digitou: senha de certificado errada só falha lá na SEFAZ, muito depois
 * do erro de digitação. Tendo um só componente, o comportamento e o rótulo
 * acessível não divergem entre telas.
 *
 * O botão é `tabindex={-1}` de propósito: no Tab, o caminho natural é senha →
 * ação do formulário, sem parada intermediária num controle que só muda a
 * apresentação. Continua alcançável por leitor de tela e por clique.
 *
 * `aria-pressed` comunica o estado; o rótulo muda junto para quem só ouve.
 */
export const CampoSenha = forwardRef<HTMLInputElement, CampoSenhaProps>(function CampoSenha(props, ref) {
  const [visivel, setVisivel] = useState(false);
  const idAviso = useId();

  return (
    <>
      <Entrada
        ref={ref}
        {...props}
        type={visivel ? "text" : "password"}
        sufixo={
          <button
            type="button"
            tabIndex={-1}
            onClick={() => setVisivel((atual) => !atual)}
            aria-pressed={visivel}
            aria-label={visivel ? "Ocultar senha" : "Mostrar senha"}
            aria-describedby={idAviso}
            disabled={props.disabled}
            className="flex h-8 w-8 items-center justify-center rounded-controle text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta disabled:cursor-not-allowed disabled:text-tinta-fraca"
          >
            <Icone nome={visivel ? "ocultar" : "ver"} className="h-4 w-4" />
          </button>
        }
      />
      {/* Anunciado só quando muda: evita que o leitor de tela repita a dica a cada foco. */}
      <span id={idAviso} role="status" aria-live="polite" className="sr-only">
        {visivel ? "Senha visível na tela" : "Senha oculta"}
      </span>
    </>
  );
});
