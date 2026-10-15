"use client";

import { useState, type KeyboardEvent } from "react";
import { cn } from "@/lib/cn";
import { NOMES_CURTOS_DOS_MESES, anoDe, mesAtual, mesesAnteriores, mesesDoAno, rotulo as rotuloCompetencia } from "@/lib/competencia";
import { useCamada } from "@/lib/useCamada";
import { CamadaFlutuante } from "@/components/ui/CamadaFlutuante";
import { Campo } from "@/components/ui/Campo";
import { Icone } from "@/components/ui/Icone";

export interface SeletorMesProps {
  rotulo: string;
  /** Formato interno AAAA-MM. */
  value: string;
  /** Teto de seleção em AAAA-MM (o mês em andamento, na prática). */
  max?: string;
  onChange: (mes: string) => void;
  descricao?: string;
  erro?: string | null;
  className?: string;
  /**
   * Variante de cabeçalho: um controle só, da altura dos botões do topo, sem
   * rótulo visível (a altura do cabeçalho é fixa em 72 px) e com a camada
   * alinhada à direita, longe da borda da viewport.
   */
  compacto?: boolean;
}

/**
 * Competência por ano + grade de meses, em popover do próprio produto.
 *
 * O `<input type="month">` nativo foi trocado de propósito: o desenho dele muda
 * a cada navegador (no Firefox e no Safari não há grade nenhuma), o texto saía
 * fora do padrão do resto do sistema e o operador não tinha como voltar dois
 * anos sem digitar. Aqui a mesma decisão — mês de competência — é um botão do
 * tamanho de um campo, com grade de 4×3, setas do teclado, `Esc` fechando e o
 * teto do mês em andamento desabilitado em vez de recusado depois do envio.
 *
 * Uma competência só existe no app (`ProvedorContexto`), então este componente
 * serve tanto o formulário (rótulo visível) quanto o cabeçalho (`compacto`) —
 * sem escrever a grade de meses duas vezes.
 */
export function SeletorMes({ rotulo, value, max, onChange, descricao, erro, className, compacto = false }: SeletorMesProps) {
  const teto = max ?? mesAtual();
  const [ano, setAno] = useState(() => anoDe(value));
  const camada = useCamada("dialog", () => setAno(anoDe(value)));
  const anoMaximo = anoDe(teto);

  function escolher(mes: string) {
    onChange(mes);
    camada.fechar();
  }

  /** Setas andam pela grade, PageUp/PageDown trocam de ano. */
  function aoTeclarNaGrade(evento: KeyboardEvent<HTMLDivElement>) {
    const passos: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -4, ArrowDown: 4 };
    if (evento.key === "PageUp" || evento.key === "PageDown") {
      evento.preventDefault();
      setAno((atual) => Math.min(anoMaximo, Math.max(1900, atual + (evento.key === "PageDown" ? 1 : -1))));
      return;
    }
    const passo = passos[evento.key];
    if (!passo) return;
    const botoes = Array.from(evento.currentTarget.querySelectorAll<HTMLButtonElement>("button:not([disabled])"));
    if (botoes.length === 0) return;
    evento.preventDefault();
    const atual = botoes.indexOf(document.activeElement as HTMLButtonElement);
    const proximo = botoes[Math.min(botoes.length - 1, Math.max(0, (atual < 0 ? 0 : atual) + passo))];
    proximo?.focus();
  }

  const meses = mesesDoAno(ano, teto);
  const porExtenso = value ? rotuloCompetencia(value) : "Escolher o mês";
  const [anoDoValor, mesDoValor] = (value || teto).split("-").map(Number);
  const abreviado = value ? `${NOMES_CURTOS_DOS_MESES[mesDoValor - 1] ?? mesDoValor}/${anoDoValor}` : "";
  const mesAnterior = mesesAnteriores(value || teto, 1);

  /** Gatilho + camada: a mesma casca nos dois modos; muda só o que se vê. */
  function conteudo(campoId?: string, descritoPor?: string) {
    return (
      <div ref={camada.container} className="relative">
        <button
          type="button"
          id={campoId}
          aria-describedby={descritoPor}
          aria-label={compacto ? `Competência: ${porExtenso} — mudar o mês de trabalho` : undefined}
          title={compacto ? "Competência: o mês de trabalho vale para Painel, Documentos, Empresas e Fechamento" : undefined}
          {...camada.propsGatilho}
          onClick={camada.alternar}
          className={cn(
            "flex h-10 items-center gap-2 rounded-controle border text-sm text-tinta",
            "transition-[border-color,background-color] duration-120 ease-produto",
            camada.aberto ? "border-acento" : "hover:border-tinta-suave",
            compacto
              ? cn("flex-none justify-start bg-superficie px-2.5", !camada.aberto && "border-traco-forte")
              : cn("w-full justify-between bg-fundo-afundado px-3", !camada.aberto && "border-borda-controle")
          )}
        >
          {compacto ? (
            <Icone nome="calendario" className="h-4 w-4 flex-none text-tinta-suave" />
          ) : null}
          <span className={cn("min-w-0 truncate", !compacto && "flex-1", !value && "text-tinta-suave", compacto && "hidden xl:inline")}>
            {porExtenso}
          </span>
          {compacto ? (
            <>
              <span className={cn("nums hidden text-xs sm:inline xl:hidden", !value && "text-tinta-suave")}>{abreviado}</span>
              <Icone nome="chevron-baixo" className="hidden h-3.5 w-3.5 flex-none text-tinta-suave sm:inline" />
            </>
          ) : (
            <Icone nome="calendario" className="h-4 w-4 flex-none text-tinta-suave" />
          )}
        </button>

        {camada.aberto ? (
          <CamadaFlutuante
            ancora={camada.container}
            painel={camada.painel}
            alinhamento={compacto ? "direita" : "esquerda"}
            id={camada.idPainel}
            role="dialog"
            aria-label={`Escolher ${rotulo.toLowerCase()}`}
            className="w-[min(92vw,17rem)] p-2"
          >
            <div className="flex items-center justify-between px-0.5 pb-2">
              <button
                type="button"
                aria-label="Ano anterior"
                onClick={() => setAno((atual) => Math.max(1900, atual - 1))}
                className="inline-flex h-7 w-7 items-center justify-center rounded-controle text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta"
              >
                <Icone nome="chevron-esquerda" className="h-4 w-4" />
              </button>
              <span className="nums text-sm font-medium text-tinta-forte">{ano}</span>
              <button
                type="button"
                aria-label="Ano seguinte"
                disabled={ano >= anoMaximo}
                onClick={() => setAno((atual) => Math.min(anoMaximo, atual + 1))}
                className="inline-flex h-7 w-7 items-center justify-center rounded-controle text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta disabled:pointer-events-none disabled:opacity-40"
              >
                <Icone nome="chevron-direita" className="h-4 w-4" />
              </button>
            </div>
            <div role="grid" aria-label={`Meses de ${ano}`} onKeyDown={aoTeclarNaGrade} className="grid grid-cols-4 gap-1">
              {meses.map((mes) => (
                <button
                  key={mes.valor}
                  type="button"
                  role="gridcell"
                  aria-label={mes.rotulo}
                  aria-current={mes.valor === value ? "date" : undefined}
                  disabled={!mes.disponivel}
                  onClick={() => escolher(mes.valor)}
                  className={cn(
                    "h-8 rounded-controle text-xs transition-colors duration-120",
                    mes.valor === value
                      ? "border border-acento-borda bg-acento-tenue font-medium text-acento-escuro"
                      : "border border-transparent text-tinta hover:bg-fundo-afundado",
                    !mes.disponivel && "cursor-not-allowed text-tinta-fraca opacity-45 hover:bg-transparent"
                  )}
                >
                  {mes.curto}
                </button>
              ))}
            </div>
            {/* Atalhos do vaivém do fechamento: antes eram as setas ‹ › de uma
                faixa fixa inteira da tela; aqui não custam altura nenhuma. */}
            <div className="mt-2 flex items-center justify-between gap-2 border-t border-traco px-0.5 pt-2">
              <button
                type="button"
                onClick={() => escolher(mesAnterior)}
                className="inline-flex h-7 items-center gap-1 rounded-controle px-1.5 text-xs text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta"
              >
                <Icone nome="chevron-esquerda" className="h-3.5 w-3.5" />
                Mês anterior
              </button>
              <button
                type="button"
                disabled={value >= teto}
                onClick={() => escolher(teto)}
                className="inline-flex h-7 items-center rounded-controle px-1.5 text-xs text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta disabled:pointer-events-none disabled:opacity-40"
              >
                Mês atual
              </button>
            </div>
            <p className="px-0.5 pt-1.5 text-2xs text-tinta-suave">
              {teto === mesAtual() ? "O mês em andamento é o último disponível." : "Até " + rotuloCompetencia(teto) + "."}
            </p>
          </CamadaFlutuante>
        ) : null}
      </div>
    );
  }

  if (compacto) {
    // Sem `Campo`: no cabeçalho o rótulo visível viraria uma linha a mais numa
    // altura fixa de 72 px. O nome acessível vem do `aria-label` do gatilho.
    return <div className={cn("relative flex-none", className)}>{conteudo()}</div>;
  }

  return (
    <Campo rotulo={rotulo} descricao={descricao} erro={erro} className={className}>
      {(campoId, descritoPor) => conteudo(campoId, descritoPor)}
    </Campo>
  );
}
