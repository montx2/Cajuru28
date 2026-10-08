"use client";

import type { ComponentProps, ReactNode } from "react";

export interface FormularioProps extends Omit<ComponentProps<"form">, "onSubmit"> {
  /** A mesma função do botão primário do rodapé — uma ação, um caminho. */
  aoEnviar: () => void | Promise<void>;
  children: ReactNode;
  /** Envio em curso: o Enter não dispara uma segunda vez. */
  ocupado?: boolean;
  className?: string;
}

/**
 * Formulário de modal e painel.
 *
 * O `<form>` do login sempre respondeu ao Enter; os modais de cadastro, não —
 * quem digita a senha do certificado e aperta Enter via ficar sem reação, e a
 * única saída era achar o botão com o mouse. Aqui o Enter chama **a mesma**
 * função do botão primário do rodapé: semântica de formulário de verdade, sem
 * mover o botão para dentro do `<form>` (o rodapé é do `Modal`).
 *
 * `noValidate` é intencional: a validação é do produto (mensagem no campo, com
 * `ErroDoCampo`), não do balão do navegador.
 */
export function Formulario({ aoEnviar, children, ocupado, className, ...props }: FormularioProps) {
  return (
    <form
      noValidate
      aria-busy={ocupado || undefined}
      className={className}
      onSubmit={(evento) => {
        evento.preventDefault();
        if (ocupado) return;
        void aoEnviar();
      }}
      {...props}
    >
      {children}
    </form>
  );
}
