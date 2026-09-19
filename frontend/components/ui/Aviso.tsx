import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { Tom } from "@/lib/estados";
import { Icone, type NomeIcone } from "./Icone";

const TONS: Record<Tom, { faixa: string; fundo: string; tinta: string; icone: NomeIcone }> = {
  ok: { faixa: "bg-ok", fundo: "bg-ok-tenue", tinta: "text-ok", icone: "verificar-circulo" },
  espera: { faixa: "bg-espera", fundo: "bg-espera-tenue", tinta: "text-espera", icone: "ampulheta" },
  erro: { faixa: "bg-erro", fundo: "bg-erro-tenue", tinta: "text-erro", icone: "alerta" },
  info: { faixa: "bg-info", fundo: "bg-info-tenue", tinta: "text-info", icone: "info" },
  neutro: { faixa: "bg-neutro", fundo: "bg-fundo-afundado", tinta: "text-tinta-suave", icone: "info" },
  acento: { faixa: "bg-acento", fundo: "bg-acento-tenue", tinta: "text-acento-escuro", icone: "info" },
};

export interface AvisoProps {
  tom?: Tom;
  titulo?: ReactNode;
  children?: ReactNode;
  icone?: NomeIcone;
  acao?: ReactNode;
  aoFechar?: () => void;
  className?: string;
  /** `role="alert"` interrompe o leitor de tela; use só para o que é urgente. */
  urgente?: boolean;
  compacto?: boolean;
}

/**
 * Aviso em linha. A faixa lateral de 3 px carrega o tom e o fundo fica suave:
 * alerta berrante compete com o dado, e aqui o dado é o que importa.
 */
export function Aviso({ tom = "info", titulo, children, icone, acao, aoFechar, className, urgente, compacto }: AvisoProps) {
  const cores = TONS[tom];
  return (
    <div
      role={urgente ? "alert" : "status"}
      className={cn(
        "relative flex gap-3 overflow-hidden rounded-cartao border border-traco",
        cores.fundo,
        compacto ? "px-3 py-2" : "px-3.5 py-3",
        className
      )}
    >
      <span aria-hidden="true" className={cn("absolute inset-y-0 left-0 w-[3px]", cores.faixa)} />
      <Icone nome={icone ?? cores.icone} className={cn("mt-0.5 h-4 w-4 flex-none", cores.tinta)} />
      <div className="min-w-0 flex-1">
        {titulo ? <p className="text-sm font-medium text-tinta-forte">{titulo}</p> : null}
        {children ? (
          <div className={cn("max-w-leitura text-sm leading-6 text-tinta", titulo ? "mt-0.5" : undefined)}>{children}</div>
        ) : null}
        {acao ? <div className="mt-2 flex flex-wrap items-center gap-2">{acao}</div> : null}
      </div>
      {aoFechar ? (
        <button
          type="button"
          onClick={aoFechar}
          aria-label="Fechar aviso"
          className="-mr-1 -mt-1 flex h-8 w-8 flex-none items-center justify-center self-start rounded-badge text-tinta-suave transition-colors duration-120 hover:bg-superficie hover:text-tinta-forte"
        >
          <Icone nome="fechar" className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </div>
  );
}
