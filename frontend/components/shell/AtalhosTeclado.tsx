"use client";
import { useCallback } from "react";
import { ATALHOS } from "@/lib/atalhos";
import { Modal } from "@/components/ui/Modal";
export function AtalhosTeclado({ aberto, aoFechar }: { aberto: boolean; aoFechar: () => void }) { const fechar = useCallback(aoFechar, [aoFechar]); return <Modal aberto={aberto} aoFechar={fechar} titulo="Atalhos de teclado"><table className="tabela mt-4"><caption>Mapa de atalhos do NotasFlow</caption><thead><tr><th scope="col">Ação</th><th scope="col">Teclas</th></tr></thead><tbody>{ATALHOS.map((atalho) => <tr key={`${atalho.grupo}-${atalho.rotulo}`}><td>{atalho.rotulo}</td><td className="text-right">{atalho.teclas.map((tecla) => <kbd key={tecla} className="ml-1 rounded-sm border border-traco-forte bg-fundo-afundado px-1.5 py-1 font-mono text-xs">{tecla}</kbd>)}</td></tr>)}</tbody></table></Modal>; }
