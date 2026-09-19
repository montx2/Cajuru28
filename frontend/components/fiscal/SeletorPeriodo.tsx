"use client";

import { cn } from "@/lib/cn";
import { anoCorrente, erroDoPeriodo, intervaloDoMes, mesPassado, periodoValido, ultimosMeses, type Periodo } from "@/lib/periodo";
import { mesAtual } from "@/lib/competencia";
import { Botao } from "@/components/ui/Botao";
import { SeletorData } from "@/components/ui/SeletorData";
import { Icone } from "@/components/ui/Icone";

export interface AtalhoPeriodo {
  rotulo: string;
  periodo: () => Periodo;
}

export const ATALHOS_PERIODO: AtalhoPeriodo[] = [
  { rotulo: "Este mês", periodo: () => intervaloDoMes(mesAtual()) },
  { rotulo: "Mês passado", periodo: mesPassado },
  { rotulo: "Últimos 3 meses", periodo: () => ultimosMeses(3) },
  { rotulo: "Este ano", periodo: anoCorrente },
];

export interface SeletorPeriodoProps {
  periodo: Periodo;
  aoMudar: (periodo: Periodo) => void;
  /** O período é obrigatório em toda consulta ao acervo: a API responde 422 sem ele. */
  obrigatorio?: boolean;
  atalhos?: boolean;
  className?: string;
  rotuloInicio?: string;
  rotuloFim?: string;
  /** Esconde o erro enquanto o operador ainda está digitando a segunda data. */
  mostrarErro?: boolean;
}

/**
 * As duas datas do intervalo, sempre juntas.
 *
 * Período obrigatório não é capricho: sem `data_inicio`/`data_fim` a API
 * responde 422, e uma consulta sem limite em milhões de documentos derruba o
 * banco. A validação é inline e diz como corrigir ("inverta as duas").
 */
export function SeletorPeriodo({
  periodo,
  aoMudar,
  obrigatorio = true,
  atalhos = true,
  className,
  rotuloInicio = "Data inicial",
  rotuloFim = "Data final",
  mostrarErro = true,
}: SeletorPeriodoProps) {
  const erro = mostrarErro && obrigatorio ? erroDoPeriodo(periodo) : null;
  const valido = periodoValido(periodo);

  return (
    <fieldset className={cn("min-w-0", className)}>
      <legend className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-tinta">
        Período
        {obrigatorio ? (
          <span className="text-erro" title="Obrigatório: a API recusa consulta ao acervo sem intervalo">
            *
          </span>
        ) : null}
        {valido ? (
          <span className="inline-flex items-center gap-1 text-2xs font-normal text-ok">
            <Icone nome="verificar" className="h-3 w-3" /> intervalo válido
          </span>
        ) : null}
      </legend>

      <div className="flex flex-wrap items-start gap-2">
        <SeletorData
          className="w-40"
          rotulo={rotuloInicio}
          value={periodo.inicio}
          onChange={(evento) => aoMudar({ ...periodo, inicio: evento.target.value })}
          max={periodo.fim || undefined}
          obrigatorio={obrigatorio}
          aria-label={rotuloInicio}
        />
        <span aria-hidden="true" className="mt-8 text-tinta-suave">
          até
        </span>
        <SeletorData
          className="w-40"
          rotulo={rotuloFim}
          value={periodo.fim}
          onChange={(evento) => aoMudar({ ...periodo, fim: evento.target.value })}
          min={periodo.inicio || undefined}
          obrigatorio={obrigatorio}
          aria-label={rotuloFim}
        />
      </div>

      {atalhos ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {ATALHOS_PERIODO.map((atalho) => {
            const alvo = atalho.periodo();
            const ativo = alvo.inicio === periodo.inicio && alvo.fim === periodo.fim;
            return (
              <Botao
                key={atalho.rotulo}
                tamanho="sm"
                variante={ativo ? "secundaria" : "sutil"}
                onClick={() => aoMudar(alvo)}
                aria-pressed={ativo}
                className={cn(ativo && "border-acento-borda bg-acento-tenue text-acento-escuro")}
              >
                {atalho.rotulo}
              </Botao>
            );
          })}
        </div>
      ) : null}

      {erro ? (
        <p role="alert" className="mt-2 flex items-start gap-1.5 text-xs leading-5 text-erro">
          <Icone nome="alerta" className="mt-0.5 h-3.5 w-3.5 flex-none" />
          <span>{erro}</span>
        </p>
      ) : (
        <p className="mt-2 text-xs leading-5 text-tinta-suave">
          Competência e período não são a mesma coisa: o período filtra a data de emissão; a competência é o mês-calendário do documento.
        </p>
      )}
    </fieldset>
  );
}
