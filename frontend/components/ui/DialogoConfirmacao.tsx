"use client";

import { useEffect, useId, useState, type ReactNode } from "react";
import { Botao } from "./Botao";
import { Entrada } from "./Campo";
import { Icone } from "./Icone";
import { Modal, type LarguraModal } from "./Modal";

export interface DialogoConfirmacaoProps {
  aberto: boolean;
  aoFechar: () => void;
  aoConfirmar: () => void;
  titulo: string;
  /** O que acontece, em fato: "Os 12 XMLs serão apagados do disco." */
  consequencia: ReactNode;
  /** O que entra na conta: lista, quantidades, nomes de empresa. */
  impacto?: ReactNode;
  rotuloConfirmar: string;
  tom?: "normal" | "perigo";
  /** Irreversível em massa exige digitação — o clique duplo não basta. */
  exigirTexto?: string;
  carregando?: boolean;
  erro?: string | null;
  largura?: LarguraModal;
  /** Complemento após a confirmação (ex.: "A empresa também perde os XMLs."). */
  aviso?: ReactNode;
}

/**
 * Substitui todo `window.confirm` do produto.
 *
 * Três decisões: o foco abre no Cancelar (o Enter acidental não destrói nada),
 * a consequência é escrita como fato e não como ameaça, e o que é irreversível
 * em massa só libera depois de a palavra ser digitada.
 */
export function DialogoConfirmacao({
  aberto,
  aoFechar,
  aoConfirmar,
  titulo,
  consequencia,
  impacto,
  rotuloConfirmar,
  tom = "normal",
  exigirTexto,
  carregando,
  erro,
  largura = "media",
  aviso,
}: DialogoConfirmacaoProps) {
  const [texto, setTexto] = useState("");
  const idImpacto = useId();
  const confirmado = !exigirTexto || texto.trim() === exigirTexto;

  // Reabrir com o campo limpo: confirmação anterior não pode valer de novo.
  useEffect(() => {
    if (!aberto) setTexto("");
  }, [aberto]);

  return (
    <Modal
      aberto={aberto}
      aoFechar={carregando ? () => undefined : aoFechar}
      titulo={titulo}
      descricao={consequencia}
      largura={largura}
      focoNoFim={!exigirTexto}
      rodape={
        <>
          <Botao variante="sutil" onClick={aoFechar} disabled={carregando}>
            Cancelar
          </Botao>
          <Botao
            variante={tom === "perigo" ? "perigo" : "primaria"}
            onClick={aoConfirmar}
            disabled={!confirmado}
            carregando={carregando}
            iconeEsquerda={tom === "perigo" ? <Icone nome="alerta" className="h-4 w-4" /> : undefined}
          >
            {rotuloConfirmar}
          </Botao>
        </>
      }
    >
      <div className="space-y-4">
        {impacto ? (
          <div id={idImpacto} className="rounded-cartao border border-traco bg-fundo-afundado px-3.5 py-3 text-sm leading-6 text-tinta">
            {impacto}
          </div>
        ) : null}
        {aviso ? (
          <p className="flex gap-2 text-sm leading-6 text-tinta-suave">
            <Icone nome="info" className="mt-0.5 h-4 w-4 flex-none" />
            <span>{aviso}</span>
          </p>
        ) : null}
        {exigirTexto ? (
          <Entrada
            rotulo={`Digite ${exigirTexto} para liberar`}
            data-foco-inicial=""
            autoComplete="off"
            spellCheck={false}
            mono
            value={texto}
            onChange={(evento) => setTexto(evento.target.value)}
            descricao="Confirmação por digitação: impede que um clique duplo apague dados em massa."
            erro={erro}
            placeholder={exigirTexto}
          />
        ) : erro ? (
          <p role="alert" className="flex items-start gap-1.5 text-sm leading-6 text-erro">
            <Icone nome="alerta" className="mt-0.5 h-4 w-4 flex-none" />
            {erro}
          </p>
        ) : null}
      </div>
    </Modal>
  );
}
