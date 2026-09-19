import { useId } from "react";
import { cn } from "@/lib/cn";
import { numero } from "@/lib/format";

/**
 * Gráficos em SVG puro, sem biblioteca.
 *
 * Regra do produto: um gráfico só entra na tela se muda uma decisão. Quando
 * entra, ele é acessível de verdade — `role="img"` com `<title>`/`<desc>` e uma
 * tabela alternativa oculta com os mesmos números, porque gráfico desenhado não
 * é lido por leitor de tela nem sobrevive à impressão em preto e branco.
 * Uma cor (acento) e neutros: cor aqui é destaque de série, não decoração.
 */

export interface PontoSerie {
  rotulo: string;
  valor: number;
  /** Detalhe no tooltip nativo (ex.: valor monetário do mês). */
  titulo?: string;
  destaque?: boolean;
}

export interface GraficoProps {
  dados: PontoSerie[];
  titulo: string;
  descricao?: string;
  /** Formata o valor na tabela alternativa e no tooltip. */
  formatoValor?: (valor: number) => string;
  className?: string;
}

function TabelaAlternativa({ dados, titulo, formatoValor }: { dados: PontoSerie[]; titulo: string; formatoValor: (valor: number) => string }) {
  return (
    <table className="sr-only">
      <caption>Dados de {titulo}</caption>
      <thead>
        <tr>
          <th scope="col">Período</th>
          <th scope="col">Valor</th>
        </tr>
      </thead>
      <tbody>
        {dados.map((ponto) => (
          <tr key={ponto.rotulo}>
            <th scope="row">{ponto.rotulo}</th>
            <td>{formatoValor(ponto.valor)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function GraficoBarras({ dados, titulo, descricao, formatoValor = numero, className }: GraficoProps & { altura?: number }) {
  const id = useId().replace(/:/g, "");
  const maximo = Math.max(1, ...dados.map((ponto) => ponto.valor));
  const larguraBarra = dados.length ? 100 / dados.length : 0;

  return (
    <figure className={cn("min-w-0", className)}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-40 w-full overflow-visible" role="img" aria-labelledby={`${id}-titulo`} aria-describedby={descricao ? `${id}-desc` : undefined}>
        <title id={`${id}-titulo`}>{titulo}</title>
        {descricao ? <desc id={`${id}-desc`}>{descricao}</desc> : null}
        <line x1="0" y1="100" x2="100" y2="100" className="stroke-traco" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {dados.map((ponto, indice) => {
          const altura = (ponto.valor / maximo) * 96;
          return (
            <rect
              key={ponto.rotulo}
              x={indice * larguraBarra + larguraBarra * 0.16}
              y={100 - altura}
              width={larguraBarra * 0.68}
              height={Math.max(altura, ponto.valor > 0 ? 1.2 : 0)}
              rx="0.6"
              className={cn("transition-opacity duration-120", ponto.destaque ? "fill-acento" : "fill-traco-forte hover:fill-acento")}
            >
              <title>{ponto.titulo ?? `${ponto.rotulo}: ${formatoValor(ponto.valor)}`}</title>
            </rect>
          );
        })}
      </svg>
      <figcaption>
        <div className="mt-2 flex gap-1">
          {dados.map((ponto) => (
            <span key={ponto.rotulo} className={cn("flex-1 truncate text-center text-2xs", ponto.destaque ? "font-medium text-tinta-forte" : "text-tinta-suave")} title={ponto.rotulo}>
              {ponto.rotulo}
            </span>
          ))}
        </div>
        <TabelaAlternativa dados={dados} titulo={titulo} formatoValor={formatoValor} />
      </figcaption>
    </figure>
  );
}

export interface FatiaSerie {
  rotulo: string;
  valor: number;
  /** Classe de cor do arco (`fill-acento`, `fill-neutro`…). */
  cor?: "acento" | "neutro" | "espera" | "info" | "ok";
}

const CORES_ARCO: Record<NonNullable<FatiaSerie["cor"]>, string> = {
  acento: "stroke-acento",
  neutro: "stroke-traco-forte",
  espera: "stroke-espera",
  info: "stroke-info",
  ok: "stroke-ok",
};

export interface GraficoDonutProps {
  dados: FatiaSerie[];
  titulo: string;
  descricao?: string;
  centro?: string;
  formatoValor?: (valor: number) => string;
  className?: string;
}

export function GraficoDonut({ dados, titulo, descricao, centro, formatoValor = numero, className }: GraficoDonutProps) {
  const id = useId().replace(/:/g, "");
  const total = dados.reduce((soma, fatia) => soma + fatia.valor, 0);
  const raio = 42;
  const circunferencia = 2 * Math.PI * raio;
  let acumulado = 0;

  return (
    <figure className={cn("flex flex-wrap items-center gap-5", className)}>
      <div className="relative h-32 w-32 flex-none">
        <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90" role="img" aria-labelledby={`${id}-titulo`} aria-describedby={descricao ? `${id}-desc` : undefined}>
          <title id={`${id}-titulo`}>{titulo}</title>
          {descricao ? <desc id={`${id}-desc`}>{descricao}</desc> : null}
          <circle cx="50" cy="50" r={raio} fill="none" strokeWidth="14" className="stroke-fundo-afundado" />
          {total > 0
            ? dados.map((fatia) => {
                const fracao = fatia.valor / total;
                const arco = (
                  <circle
                    key={fatia.rotulo}
                    cx="50"
                    cy="50"
                    r={raio}
                    fill="none"
                    strokeWidth="14"
                    strokeDasharray={`${fracao * circunferencia} ${circunferencia}`}
                    strokeDashoffset={-acumulado * circunferencia}
                    className={CORES_ARCO[fatia.cor ?? "neutro"]}
                  >
                    <title>{`${fatia.rotulo}: ${formatoValor(fatia.valor)} (${Math.round(fracao * 100)}%)`}</title>
                  </circle>
                );
                acumulado += fracao;
                return arco;
              })
            : null}
        </svg>
        {centro ? (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="nums text-lg font-semibold text-tinta-forte">{centro}</span>
          </div>
        ) : null}
      </div>
      <figcaption className="min-w-0 flex-1">
        <ul className="space-y-1.5">
          {dados.map((fatia) => (
            <li key={fatia.rotulo} className="flex items-center gap-2 text-sm">
              <span aria-hidden="true" className={cn("h-2.5 w-2.5 flex-none rounded-badge", CORES_ARCO[fatia.cor ?? "neutro"].replace("stroke-", "bg-"))} />
              <span className="min-w-0 flex-1 truncate text-tinta">{fatia.rotulo}</span>
              <span className="nums flex-none text-xs text-tinta-suave">{formatoValor(fatia.valor)}</span>
              <span className="nums w-10 flex-none text-right text-xs text-tinta-suave">{total > 0 ? `${Math.round((fatia.valor / total) * 100)}%` : "—"}</span>
            </li>
          ))}
        </ul>
        <TabelaAlternativa dados={dados.map((fatia) => ({ rotulo: fatia.rotulo, valor: fatia.valor }))} titulo={titulo} formatoValor={formatoValor} />
      </figcaption>
    </figure>
  );
}

export function Sparkline({ dados, titulo, formatoValor = numero, className }: GraficoProps) {
  const id = useId().replace(/:/g, "");
  const maximo = Math.max(1, ...dados.map((ponto) => ponto.valor));
  const minimo = Math.min(0, ...dados.map((ponto) => ponto.valor));
  const amplitude = maximo - minimo || 1;
  const pontos = dados
    .map((ponto, indice) => {
      const x = dados.length > 1 ? (indice / (dados.length - 1)) * 100 : 50;
      const y = 100 - ((ponto.valor - minimo) / amplitude) * 92 - 4;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
  const ultimo = dados[dados.length - 1];

  return (
    <figure className={cn("min-w-0", className)}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-10 w-full" role="img" aria-labelledby={`${id}-titulo`}>
        <title id={`${id}-titulo`}>
          {titulo}
          {ultimo ? ` — último: ${formatoValor(ultimo.valor)}` : ""}
        </title>
        <polyline points={pontos} fill="none" className="stroke-acento" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <TabelaAlternativa dados={dados} titulo={titulo} formatoValor={formatoValor} />
    </figure>
  );
}
