import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import {
  AUSENTE,
  chaveEmGrupos,
  dataHora,
  formatarCnpjCpf,
  moedaPartes,
  numero,
  tempoRelativo,
} from "@/lib/format";
import { useAgora } from "@/components/shell/ProvedorAgora";
import { CopiavelMono } from "./CopiavelMono";

/**
 * Formatação como componente. Quando "R$ 1.234,56" é uma função chamada em dez
 * lugares, cada um decide um detalhe diferente; quando é um componente, o
 * alinhamento pela vírgula e o `title` existem em todos por construção.
 */

export interface ValorMoedaProps {
  valor: number | null | undefined;
  /** Cancelada aparece riscada — o valor não entra em total nenhum. */
  cancelado?: boolean;
  className?: string;
  /** Esconde o símbolo em colunas cujo cabeçalho já diz "R$". */
  semSimbolo?: boolean;
  titulo?: string;
}

export function ValorMoeda({ valor, cancelado, className, semSimbolo, titulo }: ValorMoedaProps) {
  if (valor === null || valor === undefined || Number.isNaN(valor)) {
    return <span className={cn("nums text-right text-tinta-suave", className)}>{AUSENTE}</span>;
  }
  const partes = moedaPartes(valor);
  const riscado = "text-tinta-suave line-through decoration-1";

  return (
    <span
      className={cn("nums inline-flex items-baseline justify-end whitespace-nowrap text-right", className)}
      title={titulo ?? `${partes.simbolo} ${partes.inteiro},${partes.decimal}`}
    >
      {semSimbolo ? null : <span className="mr-1 text-tinta-suave">{partes.simbolo}</span>}
      <span className={cn(cancelado && riscado)}>{partes.inteiro}</span>
      {/* duas casas fixas: é isso que alinha as vírgulas em coluna */}
      <span className={cn("text-tinta-suave", cancelado && riscado)}>,{partes.decimal}</span>
    </span>
  );
}

export function Quantidade({ valor, className, titulo }: { valor: number | null | undefined; className?: string; titulo?: string }) {
  if (valor === null || valor === undefined || Number.isNaN(valor)) {
    return <span className={cn("nums text-right text-tinta-suave", className)}>{AUSENTE}</span>;
  }
  return (
    <span className={cn("nums text-right font-medium text-tinta-forte", className)} title={titulo}>
      {numero(valor)}
    </span>
  );
}

export interface DataHoraProps {
  iso: string | null | undefined;
  /** Superfície relativa ("há 6 min") e absoluto no `title`. Nunca um só. */
  relativo?: boolean;
  className?: string;
  sufixo?: ReactNode;
}

export function DataHora({ iso, relativo = true, className, sufixo }: DataHoraProps) {
  const agora = useAgora();
  if (!iso) return <span className={cn("text-tinta-suave", className)}>{AUSENTE}</span>;
  const absoluto = dataHora(iso);
  return (
    <span className={cn("whitespace-nowrap", className)} title={absoluto}>
      {relativo ? tempoRelativo(iso, agora) : absoluto}
      {sufixo}
    </span>
  );
}

export function Cnpj({ valor, className, copiar = true }: { valor: string | null | undefined; className?: string; copiar?: boolean }) {
  if (!valor) return <span className={cn("text-tinta-suave", className)}>{AUSENTE}</span>;
  return <CopiavelMono valor={valor} exibicao={formatarCnpjCpf(valor)} rotulo="Copiar CNPJ" className={className} copiar={copiar} />;
}

export function ChaveAcesso({ valor, className, copiar = true }: { valor: string | null | undefined; className?: string; copiar?: boolean }) {
  if (!valor) return <span className={cn("text-tinta-suave", className)}>{AUSENTE}</span>;
  return (
    <CopiavelMono
      valor={valor}
      exibicao={chaveEmGrupos(valor)}
      rotulo="Copiar chave de acesso"
      className={className}
      quebrar
      copiar={copiar}
    />
  );
}

/** Truncar sem `title` é esconder dado: aqui os dois vêm sempre juntos. */
export function Truncado({ texto, className, titulo, linhas = 1 }: { texto: ReactNode; className?: string; titulo?: string; linhas?: number }) {
  return (
    <span
      className={cn(linhas === 1 ? "block truncate" : "line-clamp-2", className)}
      title={titulo ?? (typeof texto === "string" ? texto : undefined)}
    >
      {texto}
    </span>
  );
}

/** "—" para o que não se aplica; "0" continua sendo zero. */
export function Ausente({ className }: { className?: string }) {
  return <span className={cn("text-tinta-suave", className)}>{AUSENTE}</span>;
}
