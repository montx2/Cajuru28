import type { StatusExecucao } from "@/lib/types";

const CONFIGURACAO: Record<StatusExecucao, { cor: string; rotulo: string; pulsa: boolean }> = {
  em_andamento: { cor: "bg-warn", rotulo: "Em andamento", pulsa: true },
  concluida: { cor: "bg-accent", rotulo: "Concluída", pulsa: false },
  erro: { cor: "bg-danger", rotulo: "Erro", pulsa: false },
};

export function StatusDot({ status }: { status: StatusExecucao }) {
  const { cor, rotulo, pulsa } = CONFIGURACAO[status];
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={`h-2 w-2 rounded-full ${cor} ${pulsa ? "pulso-andamento" : ""}`} />
      {rotulo}
    </span>
  );
}
