import type { StatusExecucao } from "@/lib/types";

const CONFIGURACAO: Record<StatusExecucao, { cor: string; rotulo: string; pulsa: boolean }> = {
  em_andamento: { cor: "bg-warn", rotulo: "Em andamento", pulsa: true },
  // A SEFAZ pediu a janela de 1 hora. Não é falha: é o protocolo.
  aguardando: { cor: "bg-warn", rotulo: "Aguardando a SEFAZ", pulsa: true },
  concluida: { cor: "bg-accent", rotulo: "Concluída", pulsa: false },
  erro: { cor: "bg-danger", rotulo: "Erro", pulsa: false },
};

const DESCONHECIDO = { cor: "bg-line", rotulo: "Desconhecido", pulsa: false };

export function StatusDot({ status }: { status: StatusExecucao }) {
  const { cor, rotulo, pulsa } = CONFIGURACAO[status] ?? DESCONHECIDO;
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className={`h-2 w-2 rounded-full ${cor} ${pulsa ? "pulso-andamento" : ""}`} />
      {rotulo}
    </span>
  );
}
