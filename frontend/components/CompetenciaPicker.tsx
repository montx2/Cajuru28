import { mesAtual, mesesAnteriores, ultimosMeses } from "@/lib/competencia";

/**
 * Seletor de competência (mês-calendário).
 *
 * Existe porque "puxar as notas de agosto" é a frase que o contador fala, e o
 * navegador já tem um controle nativo de mês — sem dependência, sem máscara,
 * sem digitar texto. Vale `null` = "todos os períodos".
 */
export function CompetenciaPicker({
  valor,
  aoMudar,
  permitirVazio = true,
  id,
}: {
  valor: string | null;
  aoMudar: (valor: string | null) => void;
  permitirVazio?: boolean;
  id?: string;
}) {
  const ultimos = ultimosMeses(6);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        id={id}
        type="month"
        value={valor ?? ""}
        max={mesAtual()}
        onChange={(e) => aoMudar(e.target.value || null)}
        className="input"
        aria-label="Competência (mês)"
      />
      <button
        type="button"
        onClick={() => aoMudar(mesAnterior(valor))}
        className="border border-line px-2 py-2 text-sm text-ink-muted hover:border-accent hover:text-ink"
        title="Mês anterior"
        aria-label="Mês anterior"
      >
        ‹
      </button>
      <button
        type="button"
        onClick={() => aoMudar(mesSeguinte(valor))}
        className="border border-line px-2 py-2 text-sm text-ink-muted hover:border-accent hover:text-ink"
        title="Mês seguinte"
        aria-label="Mês seguinte"
      >
        ›
      </button>
      {permitirVazio && (
        <button
          type="button"
          onClick={() => aoMudar(null)}
          className={
            valor === null
              ? "bg-accent px-2.5 py-2 text-xs text-white"
              : "border border-line px-2.5 py-2 text-xs text-ink-muted hover:border-accent"
          }
        >
          todos
        </button>
      )}
      <span className="hidden items-center gap-1 sm:flex">
        {ultimos.slice(0, 3).map((mes) => (
          <button
            key={mes}
            type="button"
            onClick={() => aoMudar(mes)}
            className={
              valor === mes
                ? "bg-accent-soft px-2 py-1 font-mono text-xs text-accent"
                : "px-2 py-1 font-mono text-xs text-ink-muted hover:text-ink"
            }
            title="Atalho: mês recente"
          >
            {mes.split("-").reverse().join("/")}
          </button>
        ))}
      </span>
    </div>
  );
}

function mesAnterior(valor: string | null): string {
  return mesesAnteriores(valor || mesAtual(), 1);
}

function mesSeguinte(valor: string | null): string {
  const base = valor || mesAtual();
  const [ano, mes] = base.split("-").map(Number);
  const data = new Date(ano, mes, 1); // mês+1 porque o Date já é 0-indexado
  return `${data.getFullYear()}-${String(data.getMonth() + 1).padStart(2, "0")}`;
}
