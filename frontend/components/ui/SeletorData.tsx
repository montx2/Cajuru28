"use client";

import { forwardRef, type InputHTMLAttributes } from "react";
import { Entrada, type CampoBase, type TamanhoCampo } from "./Campo";

export interface SeletorDataProps extends CampoBase, Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "className" | "size"> {
  tamanho?: TamanhoCampo;
}

/**
 * Data e mês usam o controle nativo do navegador de propósito: calendário
 * desenhado à mão é a maior superfície de bugs de acessibilidade que existe
 * num sistema fiscal, e o operador já sabe usar o do próprio sistema.
 * O valor entra e sai em AAAA-MM-DD (e AAAA-MM), que é o que a API aceita.
 */
export const SeletorData = forwardRef<HTMLInputElement, SeletorDataProps>(function SeletorData(
  { tamanho = "md", classeControle, ...props },
  ref
) {
  return (
    <Entrada
      ref={ref}
      type="date"
      tamanho={tamanho}
      numerico
      classeControle={classeControle}
      {...props}
    />
  );
});

export const SeletorMes = forwardRef<HTMLInputElement, SeletorDataProps>(function SeletorMes(
  { tamanho = "md", classeControle, ...props },
  ref
) {
  return (
    <Entrada
      ref={ref}
      type="month"
      tamanho={tamanho}
      numerico
      classeControle={classeControle}
      {...props}
    />
  );
});
