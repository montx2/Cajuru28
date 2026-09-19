"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { copiarTexto } from "@/lib/format";
import { Icone } from "./Icone";

export interface CopiavelMonoProps {
  /** Valor bruto que vai para a área de transferência (sem espaços nem máscara). */
  valor: string;
  /** Valor exibido. Quando omitido, mostra o bruto. */
  exibicao?: string;
  /** Nome acessível do botão: "Copiar chave de acesso". */
  rotulo: string;
  className?: string;
  /** Quebra em linhas quando não cabe — chave de 44 dígitos precisa aparecer inteira. */
  quebrar?: boolean;
  copiar?: boolean;
}

/**
 * CNPJ, chave de acesso, NSU e ID em monoespaçada com cópia em um clique.
 *
 * O operador confere esses valores contra o XML e contra o sistema do cliente
 * dezenas de vezes por dia; digitar de novo um CNPJ é a fonte clássica de erro
 * de cadastro, então copiar é o caminho padrão e o botão faz parte do dado.
 */
export function CopiavelMono({ valor, exibicao, rotulo, className, quebrar, copiar = true }: CopiavelMonoProps) {
  const [copiado, setCopiado] = useState(false);
  const temporizador = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (temporizador.current) window.clearTimeout(temporizador.current);
    },
    []
  );

  async function aoCopiar() {
    const ok = await copiarTexto(valor);
    if (!ok) return;
    setCopiado(true);
    if (temporizador.current) window.clearTimeout(temporizador.current);
    temporizador.current = window.setTimeout(() => setCopiado(false), 2000);
  }

  const ausente = !valor || valor === "—";

  return (
    <span className={cn("group inline-flex min-w-0 max-w-full items-start gap-1", className)}>
      <span
        className={cn(
          "min-w-0 font-mono text-xs leading-5 text-tinta",
          quebrar ? "break-all whitespace-normal" : "truncate whitespace-nowrap"
        )}
        title={valor}
      >
        {ausente ? <span className="text-tinta-suave">—</span> : (exibicao ?? valor)}
      </span>
      {copiar && !ausente ? (
        <button
          type="button"
          onClick={aoCopiar}
          aria-label={copiado ? `${rotulo}: copiado` : rotulo}
          className={cn(
            "-my-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-badge transition-colors duration-120",
            copiado ? "text-ok" : "text-tinta-fraca hover:bg-fundo-afundado hover:text-tinta group-hover:text-tinta-suave"
          )}
        >
          <Icone nome={copiado ? "verificar" : "copiar"} className="h-3.5 w-3.5" />
        </button>
      ) : null}
      <span className="sr-only" role="status" aria-live="polite">
        {copiado ? `${rotulo}: copiado para a área de transferência` : ""}
      </span>
    </span>
  );
}
