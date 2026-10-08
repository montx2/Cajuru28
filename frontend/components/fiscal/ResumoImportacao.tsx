import { cn } from "@/lib/cn";
import { numero, tempoRelativo } from "@/lib/format";
import { estadoDaSelecao } from "@/lib/estados";
import type { ResultadoImportacaoSelecionada } from "@/lib/types";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";

export interface ResumoImportacaoProps {
  resultado: ResultadoImportacaoSelecionada;
  modo: "previa" | "resultado";
  className?: string;
}

/**
 * A prévia antes do disparo.
 *
 * Cada CNPJ consultado gasta a janela oficial de 1 hora; mostrar o que vai
 * acontecer — o que roda agora, o que está na janela, o que não tem A1 — evita
 * gastar cota à toa e evita a surpresa de "disparei 400 e só 12 rodaram".
 */
export function ResumoImportacao({ resultado, modo, className }: ResumoImportacaoProps) {
  const contagem = new Map<string, number>();
  for (const item of resultado.itens) contagem.set(item.status, (contagem.get(item.status) ?? 0) + 1);

  return (
    <div className={cn("min-w-0", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <Resumo rotulo={modo === "previa" ? "Combinações avaliadas" : "Combinações"} valor={resultado.total} />
        <Resumo rotulo="Enfileiradas" valor={resultado.enfileiradas} tom="ok" />
        <Resumo rotulo="Na janela" valor={resultado.aguardando} tom="espera" />
        <Resumo rotulo="Ignoradas" valor={resultado.ignoradas} tom={resultado.ignoradas > 0 ? "erro" : undefined} />
      </div>

      {modo === "previa" ? (
        <p className="mt-2 text-xs leading-5 text-tinta-suave">
          Nada foi disparado ainda: esta é a leitura local do que aconteceria agora, sem gastar cota da SEFAZ.
        </p>
      ) : null}

      <ul className="mt-3 flex flex-wrap gap-1.5">
        {Array.from(contagem.entries()).map(([status, quantidade]) => {
          const estado = estadoDaSelecao(status);
          return (
            <li key={status}>
              <IndicadorEstado {...estado} variante="etiqueta" detalhe={numero(quantidade)} />
            </li>
          );
        })}
      </ul>

      <div className="caixa-tabela mt-3 max-h-72">
        <table className="tabela-dados">
          <caption className="sr-only">
            {modo === "previa" ? "Prévia do disparo por empresa e tipo" : "Resultado do disparo por empresa e tipo"}
          </caption>
          <thead>
            <tr>
              <th scope="col">Empresa</th>
              <th scope="col">Tipo</th>
              <th scope="col">Situação</th>
              <th scope="col">Detalhe</th>
            </tr>
          </thead>
          <tbody>
            {resultado.itens.map((item) => {
              const estado = estadoDaSelecao(item.status);
              return (
                <tr key={`${item.empresa_id}-${item.tipo}`}>
                  <td className="max-w-56 truncate" title={item.razao_social}>
                    {item.razao_social}
                  </td>
                  <td className="text-xs uppercase tracking-rotulo text-tinta-suave">{item.tipo}</td>
                  <td>
                    <IndicadorEstado {...estado} variante="texto" />
                  </td>
                  <td className="max-w-80 text-xs text-tinta-suave" title={item.mensagem}>
                    <span className="line-clamp-1">{item.mensagem}</span>
                    {item.disponivel_em ? (
                      <span className="nums ml-1 whitespace-nowrap text-espera" title={item.disponivel_em}>
                        · {tempoRelativo(item.disponivel_em)}
                      </span>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Resumo({ rotulo, valor, tom }: { rotulo: string; valor: number; tom?: "ok" | "espera" | "erro" }) {
  const cores = {
    ok: "text-ok",
    espera: "text-espera",
    erro: "text-erro",
  } as const;
  return (
    <p className="flex items-baseline gap-1.5 rounded-controle border border-traco bg-fundo-afundado px-2.5 py-1">
      <span className="text-xs text-tinta-suave">{rotulo}</span>
      <span className={cn("nums text-md font-semibold text-tinta-forte", tom ? cores[tom] : undefined)}>{numero(valor)}</span>
    </p>
  );
}
