"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Modal } from "@/components/ui/Modal";
import { SeletorTema } from "./SeletorTema";
const comandos = [
  ["Painel", "/dashboard"], ["Precisa da sua atenção", "/dashboard/atencao"], ["Execuções", "/dashboard/execucoes"],
  ["Documentos", "/dashboard/documentos"], ["Disparar importação", "/dashboard/importacoes"], ["Empresas", "/dashboard/empresas"],
  ["Certificados", "/dashboard/certificados"], ["Baixar fechamento", "/dashboard/relatorios"], ["Saúde", "/dashboard/saude"],
] as const;
export function PaletaComandos({ aberto, aoFechar }: { aberto: boolean; aoFechar: () => void }) { const router = useRouter(); const [busca, setBusca] = useState(""); const fechar = useCallback(() => { setBusca(""); aoFechar(); }, [aoFechar]); const itens = useMemo(() => comandos.filter(([rotulo]) => rotulo.toLocaleLowerCase("pt-BR").includes(busca.toLocaleLowerCase("pt-BR"))), [busca]); useEffect(() => { if (!aberto) setBusca(""); }, [aberto]); return <Modal aberto={aberto} aoFechar={fechar} titulo="Comandos"><input autoFocus className="input mt-4" value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Buscar tela, documento ou ação" aria-label="Buscar comando" /><ul className="mt-3 max-h-80 overflow-y-auto" role="listbox" aria-label="Comandos disponíveis">{itens.map(([rotulo, href]) => <li key={href}><button role="option" aria-selected="false" className="flex min-h-10 w-full items-center justify-between rounded-md px-3 text-left text-sm hover:bg-fundo-afundado" onClick={() => { fechar(); router.push(href); }}><span>{rotulo}</span><span aria-hidden="true">›</span></button></li>)}</ul><div className="mt-3 border-t border-traco pt-3"><SeletorTema /></div></Modal>; }
