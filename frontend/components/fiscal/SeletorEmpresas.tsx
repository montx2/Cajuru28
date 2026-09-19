"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { formatarCnpjCpf, numero, somenteDigitos } from "@/lib/format";
import type { EstadoVisual } from "@/lib/estados";
import type { Empresa } from "@/lib/types";
import { Busca, Caixa } from "@/components/ui/Campo";
import { Icone } from "@/components/ui/Icone";
import { IndicadorEstado } from "@/components/ui/IndicadorEstado";

export type FiltroSituacao = "todas" | "ativas" | "atencao" | "sem_certificado";

const FILTROS: Array<{ valor: FiltroSituacao; rotulo: string }> = [
  { valor: "todas", rotulo: "Todas" },
  { valor: "ativas", rotulo: "Ativas" },
  { valor: "atencao", rotulo: "Com pendência" },
  { valor: "sem_certificado", rotulo: "Sem certificado" },
];

const ALTURA_LINHA = 36;
const MARGEM = 6;

export interface SeletorEmpresasProps {
  empresas: Empresa[];
  selecionadas: Set<number>;
  aoMudar: (selecao: Set<number>) => void;
  /** Situação resumida por empresa (a pior entre os tipos sincronizados). */
  situacoes?: Map<number, EstadoVisual>;
  /** Motivo de bloqueio por empresa — ex.: "Sem certificado A1". */
  bloqueios?: Map<number, string>;
  altura?: number;
  rotulo?: string;
  filtros?: boolean;
  desabilitadas?: Set<number>;
  className?: string;
}

/**
 * Seleção de empresas em escala.
 *
 * Com 1.000 empresas, um `select multiple` é inutilizável e uma lista inteira
 * renderizada trava a rolagem. Aqui: busca por razão social ou CNPJ, janela
 * virtualizada, Shift para intervalo, "selecionar todas as visíveis" e a
 * situação de cada uma na própria linha — o operador não precisa abrir empresa
 * por empresa para saber o que vai acontecer.
 */
export function SeletorEmpresas({
  empresas,
  selecionadas,
  aoMudar,
  situacoes,
  bloqueios,
  altura = 320,
  rotulo = "Empresas",
  filtros = true,
  desabilitadas,
  className,
}: SeletorEmpresasProps) {
  const [busca, setBusca] = useState("");
  const [filtro, setFiltro] = useState<FiltroSituacao>("todas");
  const [deslocamento, setDeslocamento] = useState(0);
  const [ultimaMarcada, setUltimaMarcada] = useState<number | null>(null);
  const corpo = useRef<HTMLDivElement | null>(null);

  const visiveis = useMemo(() => {
    const termo = somenteDigitos(busca).length >= 2 && /^[\d\s./-]+$/.test(busca) ? somenteDigitos(busca) : busca.trim().toLocaleLowerCase("pt-BR");
    return empresas.filter((empresa) => {
      if (filtro === "ativas" && !empresa.ativa) return false;
      const situacao = situacoes?.get(empresa.id);
      if (filtro === "atencao" && (!situacao || (situacao.tom !== "espera" && situacao.tom !== "erro"))) return false;
      if (filtro === "sem_certificado" && situacao?.rotulo !== "Sem certificado A1") return false;
      if (!termo) return true;
      if (/^\d+$/.test(termo)) return somenteDigitos(empresa.cnpj_cpf).includes(termo);
      return empresa.razao_social.toLocaleLowerCase("pt-BR").includes(termo);
    });
  }, [busca, empresas, filtro, situacoes]);

  const selecionadasVisiveis = useMemo(() => visiveis.filter((empresa) => selecionadas.has(empresa.id)).length, [selecionadas, visiveis]);

  useEffect(() => {
    setDeslocamento(0);
    if (corpo.current) corpo.current.scrollTop = 0;
  }, [busca, filtro]);

  const inicio = Math.max(0, Math.floor(deslocamento / ALTURA_LINHA) - MARGEM);
  const fim = Math.min(visiveis.length, inicio + Math.ceil(altura / ALTURA_LINHA) + MARGEM * 2);

  const alternar = useCallback(
    (id: number, indice: number, ate?: number | null) => {
      const proximas = new Set(selecionadas);
      if (ate !== null && ate !== undefined && ate !== indice) {
        const [de, para] = ate < indice ? [ate, indice] : [indice, ate];
        const marcar = !proximas.has(id);
        for (let i = de; i <= para; i += 1) {
          const empresa = visiveis[i];
          if (!empresa || desabilitadas?.has(empresa.id)) continue;
          if (marcar) proximas.add(empresa.id);
          else proximas.delete(empresa.id);
        }
      } else if (proximas.has(id)) proximas.delete(id);
      else proximas.add(id);
      setUltimaMarcada(indice);
      aoMudar(proximas);
    },
    [aoMudar, desabilitadas, selecionadas, visiveis]
  );

  function selecionarVisiveis() {
    const proximas = new Set(selecionadas);
    if (selecionadasVisiveis === visiveis.length) visiveis.forEach((empresa) => proximas.delete(empresa.id));
    else visiveis.forEach((empresa) => !desabilitadas?.has(empresa.id) && proximas.add(empresa.id));
    aoMudar(proximas);
  }

  return (
    <div className={cn("min-w-0 rounded-cartao border border-traco bg-superficie", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-traco bg-fundo-afundado px-3 py-2">
        <p className="text-xs font-medium text-tinta">
          {rotulo}
          <span className="nums ml-2 font-normal text-tinta-suave">
            {numero(selecionadas.size)} de {numero(empresas.length)} marcadas
          </span>
        </p>
        {filtros ? (
          <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filtrar empresas por situação">
            {FILTROS.map((opcao) => (
              <button
                key={opcao.valor}
                type="button"
                aria-pressed={filtro === opcao.valor}
                onClick={() => setFiltro(opcao.valor)}
                className={cn(
                  "h-7 rounded-badge border px-2 text-xs transition-colors duration-120",
                  filtro === opcao.valor
                    ? "border-acento-borda bg-acento-tenue font-medium text-acento-escuro"
                    : "border-traco bg-superficie text-tinta-suave hover:border-traco-forte hover:text-tinta"
                )}
              >
                {opcao.rotulo}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-traco px-3 py-2">
        <Busca
          className="min-w-48 flex-1"
          tamanho="sm"
          valor={busca}
          aoMudar={setBusca}
          rotulo="Buscar empresa por razão social ou CNPJ"
          placeholder="Razão social ou CNPJ"
          alvoDoAtalho={false}
        />
        <Caixa
          compacta
          rotulo={`Selecionar todas as ${visiveis.length} visíveis`}
          checked={visiveis.length > 0 && selecionadasVisiveis === visiveis.length}
          indeterminado={selecionadasVisiveis > 0 && selecionadasVisiveis < visiveis.length}
          disabled={visiveis.length === 0}
          onChange={selecionarVisiveis}
        />
      </div>

      <div
        ref={corpo}
        onScroll={(evento) => setDeslocamento(evento.currentTarget.scrollTop)}
        className="rolagem-fina overflow-y-auto"
        style={{ height: altura }}
        role="group"
        aria-label={`${numero(visiveis.length)} empresas listadas`}
      >
        {visiveis.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-tinta-suave">
            {empresas.length === 0 ? "Nenhuma empresa cadastrada." : "Nenhuma empresa corresponde ao filtro."}
          </p>
        ) : (
          <ul>
            {inicio > 0 ? <li aria-hidden="true" style={{ height: inicio * ALTURA_LINHA }} /> : null}
            {visiveis.slice(inicio, fim).map((empresa, posicao) => {
              const indice = inicio + posicao;
              const situacao = situacoes?.get(empresa.id);
              const bloqueio = bloqueios?.get(empresa.id);
              const desabilitada = desabilitadas?.has(empresa.id) || !empresa.ativa;
              return (
                <li
                  key={empresa.id}
                  style={{ height: ALTURA_LINHA }}
                  className={cn(
                    "flex items-center gap-2 border-b border-traco px-2 last:border-0",
                    selecionadas.has(empresa.id) && "bg-acento-tenue/60",
                    desabilitada && "opacity-60"
                  )}
                >
                  <Caixa
                    compacta
                    className="w-auto flex-none py-0"
                    rotulo=""
                    aria-label={`Selecionar ${empresa.razao_social}`}
                    checked={selecionadas.has(empresa.id)}
                    disabled={desabilitada}
                    title={bloqueio ?? (empresa.ativa ? undefined : "Empresa inativa")}
                    onChange={() => alternar(empresa.id, indice)}
                    onClick={(evento) => {
                      if (evento.shiftKey) {
                        evento.preventDefault();
                        alternar(empresa.id, indice, ultimaMarcada ?? indice);
                      }
                    }}
                  />
                  <span className="min-w-0 flex-1 truncate text-sm text-tinta" title={empresa.razao_social}>
                    {empresa.razao_social}
                  </span>
                  <span className="nums hidden flex-none font-mono text-xs text-tinta-suave sm:block">{formatarCnpjCpf(empresa.cnpj_cpf)}</span>
                  {bloqueio ? (
                    <span className="flex-none text-tinta-suave" title={bloqueio}>
                      <Icone nome="cadeado" className="h-3.5 w-3.5" />
                      <span className="sr-only">{bloqueio}</span>
                    </span>
                  ) : null}
                  {situacao ? <IndicadorEstado {...situacao} variante="texto" className="w-40 flex-none" /> : null}
                </li>
              );
            })}
            {fim < visiveis.length ? <li aria-hidden="true" style={{ height: (visiveis.length - fim) * ALTURA_LINHA }} /> : null}
          </ul>
        )}
      </div>
    </div>
  );
}
