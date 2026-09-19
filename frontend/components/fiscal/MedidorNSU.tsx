import { cn } from "@/lib/cn";
import { numero, nsuFormatado } from "@/lib/format";
import { BarraProgresso } from "@/components/ui/Progresso";
import type { EstadoSincronizacao } from "@/lib/types";

export interface MedidorNSUProps {
  ultimo: string;
  maximo: string | null;
  pendencia?: number;
  className?: string;
  compacto?: boolean;
}

/**
 * NSU é cursor de leitura da SEFAZ por empresa e tipo: `ultimo / max` é o
 * progresso e `pendencia` é o que falta ler. Sem o par completo o operador não
 * sabe se "0 pendência" significa em dia ou nunca consultado.
 */
export function MedidorNSU({ ultimo, maximo, pendencia, className, compacto }: MedidorNSUProps) {
  const temMaximo = Boolean(maximo && Number(maximo) > 0);
  const valor = Number(ultimo ?? 0) || 0;
  const teto = temMaximo ? Number(maximo) : 0;

  return (
    <div className={cn("min-w-0", className)}>
      <div className="flex items-baseline gap-1.5 text-xs">
        <span className="nums font-mono text-tinta" title={`Último NSU lido: ${nsuFormatado(ultimo)}`}>
          {nsuFormatado(ultimo)}
        </span>
        <span className="text-tinta-fraca">/</span>
        <span className="nums font-mono text-tinta-suave" title={temMaximo ? `Maior NSU disponível: ${nsuFormatado(maximo)}` : "A SEFAZ ainda não informou o NSU máximo"}>
          {temMaximo ? nsuFormatado(maximo) : "—"}
        </span>
      </div>
      {!compacto ? (
        <BarraProgresso
          className="mt-1"
          valor={temMaximo ? Math.min(valor, teto) : 0}
          maximo={temMaximo ? teto : 1}
          tom={temMaximo && valor < teto ? "espera" : "ok"}
          rotulo="Progresso do NSU"
          descricao={temMaximo ? `${numero(valor)} de ${numero(teto)}` : "NSU máximo desconhecido"}
        />
      ) : null}
      {pendencia !== undefined ? (
        <p className={cn("nums mt-0.5 text-2xs", pendencia > 0 ? "text-espera" : "text-tinta-suave")}>
          {pendencia > 0 ? `${numero(pendencia)} para ler` : "nada para ler"}
        </p>
      ) : null}
    </div>
  );
}

/** Linha completa de sincronismo: medidor + contagem regressiva da janela. */
export function ResumoNSU({ estado, className }: { estado: EstadoSincronizacao; className?: string }) {
  return (
    <MedidorNSU
      className={className}
      ultimo={estado.ultimo_nsu}
      maximo={estado.max_nsu}
      pendencia={estado.pendencia}
    />
  );
}
