"use client";

import { useState } from "react";
import { ApiError } from "@/lib/api";
import { descreverErro } from "@/lib/erros";
import { Aviso } from "./Aviso";
import { Botao } from "./Botao";
import { Icone } from "./Icone";

export interface EstadoErroProps {
  erro: unknown;
  /** Recarrega os dados. Some quando a causa é espera (janela da SEFAZ). */
  aoTentarNovamente?: () => void;
  contexto?: string;
  className?: string;
  carregando?: boolean;
}

/**
 * Erro com causa e próximo passo. O detalhe técnico fica recolhido em
 * `<details>`: o operador lê a decisão, o engenheiro abre quando precisa.
 */
export function EstadoErro({ erro, aoTentarNovamente, contexto, className, carregando }: EstadoErroProps) {
  const [detalheAberto, setDetalheAberto] = useState(false);
  const descrito = descreverErro(erro, contexto);
  const ehAguardo = erro instanceof ApiError && erro.ehAguardo;

  return (
    <Aviso
      tom={descrito.tom}
      titulo={descrito.titulo}
      className={className}
      icone={ehAguardo ? "ampulheta" : undefined}
      acao={
        aoTentarNovamente && !ehAguardo ? (
          <Botao variante="secundaria" tamanho="sm" onClick={aoTentarNovamente} carregando={carregando} iconeEsquerda={<Icone nome="atualizar" className="h-3.5 w-3.5" />}>
            Tentar novamente
          </Botao>
        ) : undefined
      }
    >
      <p>{descrito.causa}</p>
      <p className="mt-1">
        <span className="font-medium text-tinta-forte">Próximo passo: </span>
        {descrito.proximoPasso}
      </p>
      {descrito.detalhe ? (
        <details className="mt-2" open={detalheAberto} onToggle={(evento) => setDetalheAberto((evento.target as HTMLDetailsElement).open)}>
          <summary className="cursor-pointer rounded-badge text-xs font-medium text-tinta-suave underline-offset-4 hover:text-tinta hover:underline">
            Detalhe técnico da resposta
          </summary>
          <pre className="rolagem-fina mt-2 max-h-40 overflow-auto rounded-controle border border-traco bg-superficie p-2 font-mono text-2xs leading-5 text-tinta-suave">
            {descrito.detalhe}
          </pre>
        </details>
      ) : null}
    </Aviso>
  );
}
