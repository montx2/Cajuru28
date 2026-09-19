import { cn } from "@/lib/cn";
import { numero } from "@/lib/format";
import type { Tom } from "@/lib/estados";

const CORES: Record<Tom, string> = {
  ok: "bg-ok",
  espera: "bg-espera",
  erro: "bg-erro",
  info: "bg-info",
  neutro: "bg-neutro",
  acento: "bg-acento",
};

export interface BarraProgressoProps {
  valor: number;
  maximo: number;
  tom?: Tom;
  rotulo: string;
  /** Texto à direita (ex.: "1.204 de 1.310"). */
  descricao?: string;
  className?: string;
  altura?: "fina" | "media";
}

/** Barra com nome acessível completo: `progressbar` exige valor e rótulo. */
export function BarraProgresso({ valor, maximo, tom = "acento", rotulo, descricao, className, altura = "fina" }: BarraProgressoProps) {
  const percentual = maximo > 0 ? Math.min(100, Math.max(0, (valor / maximo) * 100)) : 0;
  return (
    <div className={cn("min-w-0", className)}>
      <div
        role="progressbar"
        aria-label={rotulo}
        aria-valuenow={Math.round(valor)}
        aria-valuemin={0}
        aria-valuumax={Math.round(maximo)}
        aria-valuetext={descricao ?? `${numero(valor)} de ${numero(maximo)}`}
        className={cn("w-full overflow-hidden rounded-full bg-fundo-afundado", altura === "fina" ? "h-1.5" : "h-2.5")}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-240 ease-produto", CORES[tom])}
          style={{ width: `${percentual}%` }}
        />
      </div>
    </div>
  );
}

export interface MedidorProps {
  rotulo: string;
  valor: number;
  maximo: number;
  tom?: Tom;
  /** Números ao lado: o que já foi e o que falta. */
  esquerda?: string;
  direita?: string;
  className?: string;
}

/** Progresso com números visíveis — barra sozinha não responde "quantos faltam?". */
export function Medidor({ rotulo, valor, maximo, tom = "acento", esquerda, direita, className }: MedidorProps) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="mb-1 flex items-baseline justify-between gap-3 text-xs">
        <span className="nums truncate text-tinta">{esquerda ?? numero(valor)}</span>
        <span className="nums flex-none text-tinta-suave">{direita ?? `de ${numero(maximo)}`}</span>
      </div>
      <BarraProgresso valor={valor} maximo={maximo} tom={tom} rotulo={rotulo} />
    </div>
  );
}
