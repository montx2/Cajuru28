"use client";
import { useCallback, useState } from "react";
import { Botao } from "./Botao";
import { Modal } from "./Modal";
export function DialogoConfirmacao({ aberto, aoFechar, aoConfirmar, titulo, consequencia, rotuloConfirmar, tom = "normal", exigirTexto, carregando }: { aberto: boolean; aoFechar: () => void; aoConfirmar: () => void | Promise<void>; titulo: string; consequencia: string; rotuloConfirmar: string; tom?: "normal" | "perigo"; exigirTexto?: string; carregando?: boolean }) {
  const [texto, setTexto] = useState(""); const fechar = useCallback(() => { setTexto(""); aoFechar(); }, [aoFechar]); const liberado = !exigirTexto || texto === exigirTexto;
  return <Modal aberto={aberto} aoFechar={fechar} titulo={titulo}><p className="mt-2 max-w-[75ch] text-sm text-tinta-suave">{consequencia}</p>{exigirTexto && <div className="mt-4"><label className="label" htmlFor="confirmacao-texto">Digite <strong>{exigirTexto}</strong> para continuar</label><input id="confirmacao-texto" className="input" value={texto} onChange={(e) => setTexto(e.target.value)} autoComplete="off" /></div>}<div className="mt-6 flex justify-between gap-3"><Botao onClick={fechar} autoFocus>Cancelar</Botao><Botao variante={tom === "perigo" ? "perigo" : "primaria"} disabled={!liberado} carregando={carregando} onClick={aoConfirmar}>{rotuloConfirmar}</Botao></div></Modal>;
}
