"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { numero } from "@/lib/format";
import { Caixa } from "./Campo";
import { EsqueletoTabela } from "./Esqueleto";
import { EstadoErro } from "./EstadoErro";
import { EstadoVazio } from "./EstadoVazio";
import { Icone, type NomeIcone } from "./Icone";
import { Popover } from "./Popover";

export type DensidadeTabela = "confortavel" | "compacta";
export type DirecaoOrdenacao = "asc" | "desc";

export interface OrdenacaoTabela {
  coluna: string;
  direcao: DirecaoOrdenacao;
}

export interface ColunaTabela<L> {
  id: string;
  cabecalho: string;
  /** Dica curta no cabeçalho (unidade, origem do dado). */
  dica?: string;
  /** Classe de largura (`w-40`, `min-w-56`). Datas e números pedem largura fixa. */
  largura?: string;
  alinhamento?: "esquerda" | "direita" | "centro";
  /** Números: alinha à direita e ativa tabular-nums por construção. */
  numerica?: boolean;
  ordenavel?: boolean;
  /** Não pode ser ocultada no menu de colunas. */
  fixa?: boolean;
  ocultaPorPadrao?: boolean;
  celula: (linha: L, contexto: CelulaContexto) => ReactNode;
  classeCelula?: string;
  classeCabecalho?: string;
}

export interface CelulaContexto {
  selecionada: boolean;
  ativa: boolean;
}

export interface SelecaoTabela {
  chaves: Set<string>;
  aoMudar: (chaves: Set<string>) => void;
  /** Total do filtro — quando maior que as linhas carregadas, oferece "todas as N". */
  totalNoFiltro?: number;
  /** Marca o filtro inteiro sem materializar ids (exportar/excluir pelo critério). */
  aoSelecionarTudoDoFiltro?: () => void;
  todasDoFiltro?: boolean;
  aoCancelarTudoDoFiltro?: () => void;
}

export interface EstadosTabela {
  carregando?: boolean;
  erro?: unknown;
  aoTentarNovamente?: () => void;
  vazioTitulo: string;
  vazioInstrucao?: ReactNode;
  vazioAcao?: ReactNode;
  vazioIcone?: NomeIcone;
  /** Sem resultado por causa do filtro: aparece "Limpar filtros". */
  filtroAtivo?: boolean;
  aoLimparFiltro?: () => void;
}

export interface TabelaProps<L> {
  linhas: L[];
  colunas: Array<ColunaTabela<L>>;
  chaveDaLinha: (linha: L) => string | number;
  /** `<caption>` para leitor de tela: o que esta tabela é. */
  legenda: string;
  estados: EstadosTabela;
  selecao?: SelecaoTabela;
  ordenacao?: OrdenacaoTabela | null;
  aoOrdenar?: (ordenacao: OrdenacaoTabela | null) => void;
  aoAbrirLinha?: (linha: L) => void;
  densidade?: DensidadeTabela;
  aoMudarDensidade?: (densidade: DensidadeTabela) => void;
  colunasVisiveis?: string[];
  aoMudarColunas?: (ids: string[]) => void;
  /** Ações que aparecem na barra flutuante quando há seleção. */
  barraDeSelecao?: (contexto: { quantidade: number; limpar: () => void }) => ReactNode;
  ferramentas?: ReactNode;
  rodape?: ReactNode;
  /** Rolagem interna com cabeçalho colado; sem isto a página inteira rola. */
  altura?: string;
  /** Automática acima de 300 linhas — 5.000 têm que rolar a 60 fps. */
  virtualizar?: boolean;
  /** Classe extra por linha — é onde a regra de negócio marca risco ou espera. */
  classeLinha?: (linha: L) => string | undefined;
  className?: string;
}

const ALTURA_LINHA: Record<DensidadeTabela, number> = { compacta: 40, confortavel: 44 };
const LIMITE_VIRTUALIZACAO = 300;
const MARGEM_LINHAS = 8;

/**
 * A tabela operacional do Fluxa.
 *
 * Por que um componente só: linha de 40 px, número à direita, cabeçalho colado,
 * seleção por intervalo com Shift, coluna ocultável persistida, virtualização e
 * os quatro estados (carregando, vazio, erro, conteúdo) são a mesma decisão em
 * dez telas. Feita à mão em cada página, divergiria na segunda semana.
 *
 * Decisão de acessibilidade: a linha clicável **não** recebe `role="button"` —
 * isso apagaria a semântica de linha para o leitor de tela. Ela é focável
 * (`tabIndex`), abre com Enter/Espaço e o clique do mouse é ignorado quando cai
 * sobre um controle interno.
 */
export function Tabela<L>({
  linhas,
  colunas,
  chaveDaLinha,
  legenda,
  estados,
  selecao,
  ordenacao,
  aoOrdenar,
  aoAbrirLinha,
  densidade = "compacta",
  aoMudarDensidade,
  colunasVisiveis,
  aoMudarColunas,
  barraDeSelecao,
  ferramentas,
  rodape,
  altura,
  virtualizar,
  classeLinha,
  className,
}: TabelaProps<L>) {
  const corpo = useRef<HTMLDivElement | null>(null);
  const [deslocamento, setDeslocamento] = useState(0);
  const [alturaVisivel, setAlturaVisivel] = useState(600);
  const [indiceAtivo, setIndiceAtivo] = useState(-1);
  const [ultimaSelecionada, setUltimaSelecionada] = useState<number | null>(null);

  const visiveis = useMemo(() => {
    if (!colunasVisiveis) return colunas;
    return colunas.filter((coluna) => coluna.fixa || colunasVisiveis.includes(coluna.id));
  }, [colunas, colunasVisiveis]);

  const chaves = useMemo(() => linhas.map((linha) => String(chaveDaLinha(linha))), [chaveDaLinha, linhas]);
  const selecionadas = selecao?.chaves ?? new Set<string>();
  const selecionadasNaPagina = useMemo(() => chaves.filter((chave) => selecionadas.has(chave)), [chaves, selecionadas]);

  const usaVirtualizacao = (virtualizar ?? linhas.length > LIMITE_VIRTUALIZACAO) && linhas.length > 0;
  const alturaLinha = ALTURA_LINHA[densidade];

  useEffect(() => {
    if (!usaVirtualizacao || !corpo.current) return;
    const observador = new ResizeObserver(([entrada]) => setAlturaVisivel(entrada.contentRect.height));
    observador.observe(corpo.current);
    setAlturaVisivel(corpo.current.clientHeight);
    return () => observador.disconnect();
  }, [usaVirtualizacao]);

  const aoRolar = useCallback((evento: React.UIEvent<HTMLDivElement>) => {
    setDeslocamento(evento.currentTarget.scrollTop);
  }, []);

  const intervalo = useMemo(() => {
    if (!usaVirtualizacao) return { inicio: 0, fim: linhas.length };
    const visiveisPorTela = Math.ceil(alturaVisivel / alturaLinha);
    const inicio = Math.max(0, Math.floor(deslocamento / alturaLinha) - MARGEM_LINHAS);
    const fim = Math.min(linhas.length, inicio + visiveisPorTela + MARGEM_LINHAS * 2);
    return { inicio, fim };
  }, [alturaLinha, deslocamento, alturaVisivel, linhas.length, usaVirtualizacao]);

  // A linha ativa muda pelo teclado: mantém o índice dentro do que existe.
  useEffect(() => {
    if (indiceAtivo >= linhas.length) setIndiceAtivo(linhas.length ? linhas.length - 1 : -1);
  }, [indiceAtivo, linhas.length]);

  function alternarSelecao(chave: string, indice: number, intervaloAte?: number | null) {
    if (!selecao) return;
    const proximas = new Set(selecionadas);
    if (intervaloAte !== null && intervaloAte !== undefined && intervaloAte !== indice) {
      const [de, ate] = intervaloAte < indice ? [intervaloAte, indice] : [indice, intervaloAte];
      const marcar = !proximas.has(chave);
      for (let i = de; i <= ate; i += 1) {
        const chaveDoIntervalo = chaves[i];
        if (!chaveDoIntervalo) continue;
        if (marcar) proximas.add(chaveDoIntervalo);
        else proximas.delete(chaveDoIntervalo);
      }
    } else if (proximas.has(chave)) {
      proximas.delete(chave);
    } else {
      proximas.add(chave);
    }
    setUltimaSelecionada(indice);
    selecao.aoMudar(proximas);
  }

  function selecionarPagina() {
    if (!selecao) return;
    const proximas = new Set(selecionadas);
    if (selecionadasNaPagina.length === chaves.length) chaves.forEach((chave) => proximas.delete(chave));
    else chaves.forEach((chave) => proximas.add(chave));
    selecao.aoMudar(proximas);
  }

  function aoTeclarNaTabela(evento: React.KeyboardEvent<HTMLDivElement>) {
    if (!linhas.length) return;
    const alvo = evento.target as HTMLElement;
    // Dentro de campo de texto, j/k/x digitam: o atalho não rouba a tecla.
    if (alvo.closest("input, textarea, select, [contenteditable='true']")) return;

    if (evento.key === "j" || evento.key === "J" || evento.key === "ArrowDown") {
      evento.preventDefault();
      mover(1);
    } else if (evento.key === "k" || evento.key === "K" || evento.key === "ArrowUp") {
      evento.preventDefault();
      mover(-1);
    } else if (evento.key === "x" || evento.key === "X") {
      if (!selecao || indiceAtivo < 0) return;
      evento.preventDefault();
      const chave = chaves[indiceAtivo];
      if (chave) alternarSelecao(chave, indiceAtivo);
    } else if (evento.key === "Enter" || evento.key === " ") {
      if (!aoAbrirLinha || indiceAtivo < 0 || alvo.closest("button, a")) return;
      evento.preventDefault();
      aoAbrirLinha(linhas[indiceAtivo]);
    } else if (evento.key === "Home") {
      evento.preventDefault();
      setIndiceAtivo(0);
    } else if (evento.key === "End") {
      evento.preventDefault();
      setIndiceAtivo(linhas.length - 1);
    }
  }

  function mover(passo: number) {
    setIndiceAtivo((atual) => {
      const proximo = atual < 0 ? (passo > 0 ? 0 : linhas.length - 1) : atual + passo;
      return Math.min(Math.max(proximo, 0), linhas.length - 1);
    });
  }

  // A linha ativa precisa continuar visível quando o teclado a move.
  useEffect(() => {
    if (indiceAtivo < 0 || !usaVirtualizacao || !corpo.current) return;
    const topo = indiceAtivo * alturaLinha;
    const fim = topo + alturaLinha;
    const visivelTopo = corpo.current.scrollTop;
    const visivelFim = visivelTopo + corpo.current.clientHeight;
    if (topo < visivelTopo) corpo.current.scrollTop = topo;
    else if (fim > visivelFim) corpo.current.scrollTop = fim - corpo.current.clientHeight;
  }, [alturaLinha, indiceAtivo, usaVirtualizacao]);

  const totalColunas = visiveis.length + (selecao ? 1 : 0);
  const conteudoVazio = estados.carregando ? null : (
    <tr>
      <td colSpan={totalColunas} className="p-0">
        {estados.erro ? (
          <div className="p-4">
            <EstadoErro erro={estados.erro} aoTentarNovamente={estados.aoTentarNovamente} contexto="carregar esta tabela" />
          </div>
        ) : (
          <div className="p-4">
            <EstadoVazio
              inline
              icone={estados.vazioIcone ?? (estados.filtroAtivo ? "busca" : "caixa")}
              titulo={estados.filtroAtivo ? "Nenhum resultado com estes filtros" : estados.vazioTitulo}
              instrucao={
                estados.filtroAtivo
                  ? "Nenhum registro corresponde à combinação atual de período, empresa e demais filtros."
                  : estados.vazioInstrucao
              }
              acao={
                estados.filtroAtivo && estados.aoLimparFiltro ? (
                  <button
                    type="button"
                    onClick={estados.aoLimparFiltro}
                    className="rounded-controle border border-borda-controle bg-superficie px-3 py-1.5 text-sm font-medium text-tinta transition-colors duration-120 hover:bg-fundo-afundado"
                  >
                    Limpar filtros
                  </button>
                ) : (
                  estados.vazioAcao
                )
              }
            />
          </div>
        )}
      </td>
    </tr>
  );

  const temConteudo = !estados.carregando && !estados.erro && linhas.length > 0;
  const mostrarBarra = Boolean(selecao && (selecionadas.size > 0 || selecao.todasDoFiltro));

  return (
    <div className={cn("relative overflow-hidden rounded-cartao border border-traco bg-superficie", className)}>
      {(aoMudarDensidade || aoMudarColunas || ferramentas || (selecao && selecao.totalNoFiltro !== undefined)) && (
        <div className="nao-imprimir flex flex-wrap items-center justify-between gap-2 border-b border-traco bg-fundo-afundado px-3 py-2">
          <p className="nums text-xs text-tinta-suave" role="status" aria-live="polite">
            {estados.carregando
              ? "Carregando…"
              : `${numero(linhas.length)} ${linhas.length === 1 ? "linha" : "linhas"} nesta página`}
            {selecao && selecao.totalNoFiltro !== undefined && selecao.totalNoFiltro !== linhas.length
              ? ` · ${numero(selecao.totalNoFiltro)} no filtro`
              : null}
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            {ferramentas}
            {aoMudarDensidade ? (
              <div className="flex items-center gap-0.5 rounded-controle border border-traco bg-superficie p-0.5" role="group" aria-label="Densidade da tabela">
                {(["confortavel", "compacta"] as DensidadeTabela[]).map((opcao) => (
                  <button
                    key={opcao}
                    type="button"
                    aria-pressed={densidade === opcao}
                    onClick={() => aoMudarDensidade(opcao)}
                    title={opcao === "compacta" ? "Linhas de 40 px — mais registros por tela" : "Linhas de 44 px — mais respiro"}
                    className={cn(
                      "flex h-7 w-8 items-center justify-center rounded-badge transition-colors duration-120",
                      densidade === opcao ? "bg-fundo-afundado text-tinta-forte" : "text-tinta-suave hover:text-tinta"
                    )}
                  >
                    <Icone nome={opcao === "compacta" ? "filtrar" : "menu"} className="h-3.5 w-3.5" />
                    <span className="sr-only">{opcao === "compacta" ? "Compacta" : "Confortável"}</span>
                  </button>
                ))}
              </div>
            ) : null}
            {aoMudarColunas ? (
              <Popover rotulo="Colunas" icone="colunas" alinhamento="direita" largura="w-60" dica="Escolher colunas">
                {() => (
                  <div className="max-h-80 overflow-y-auto py-1">
                    <p className="px-3 py-1.5 text-2xs font-medium uppercase tracking-[.04em] text-tinta-fraca">Colunas visíveis</p>
                    {colunas.map((coluna) => (
                      <Caixa
                        key={coluna.id}
                        compacta
                        rotulo={coluna.cabecalho}
                        checked={coluna.fixa || !colunasVisiveis || colunasVisiveis.includes(coluna.id)}
                        disabled={coluna.fixa}
                        onChange={(evento) => {
                          if (coluna.fixa) return;
                          const atuais = colunasVisiveis ?? colunas.map((item) => item.id);
                          const proximas = evento.target.checked
                            ? colunas.map((item) => item.id).filter((id) => id === coluna.id || atuais.includes(id))
                            : atuais.filter((id) => id !== coluna.id);
                          aoMudarColunas(proximas);
                        }}
                        className="px-3"
                      />
                    ))}
                  </div>
                )}
              </Popover>
            ) : null}
          </div>
        </div>
      )}

      <div
        ref={corpo}
        onScroll={aoRolar}
        onKeyDown={aoTeclarNaTabela}
        className={cn("rolagem-fina relative overflow-auto", altura ?? "max-h-[calc(100vh-14rem)]")}
        style={altura ? { height: altura } : undefined}
      >
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{legenda}</caption>
          <thead>
            <tr className="border-b border-traco">
              {selecao ? (
                <th scope="col" className="sticky top-0 z-10 w-10 bg-fundo-afundado px-2 py-1.5 align-middle">
                  <span className="sr-only">Selecionar todas as linhas desta página</span>
                  <Caixa
                    compacta
                    rotulo=""
                    aria-label="Selecionar todas as linhas desta página"
                    checked={chaves.length > 0 && selecionadasNaPagina.length === chaves.length}
                    indeterminado={selecionadasNaPagina.length > 0 && selecionadasNaPagina.length < chaves.length}
                    disabled={chaves.length === 0}
                    onChange={selecionarPagina}
                    className="-my-1.5 px-0 hover:bg-transparent"
                  />
                </th>
              ) : null}
              {visiveis.map((coluna) => {
                const ativa = ordenacao?.coluna === coluna.id;
                const alinhamento = coluna.numerica ? "text-right" : coluna.alinhamento === "direita" ? "text-right" : coluna.alinhamento === "centro" ? "text-center" : "text-left";
                return (
                  <th
                    key={coluna.id}
                    scope="col"
                    aria-sort={ativa ? (ordenacao?.direcao === "asc" ? "ascending" : "descending") : coluna.ordenavel ? "none" : undefined}
                    data-numerico={coluna.numerica || undefined}
                    className={cn(
                      "sticky top-0 z-10 h-10 whitespace-nowrap bg-fundo-afundado px-3 text-xs font-medium text-tinta-suave",
                      alinhamento,
                      coluna.largura,
                      coluna.classeCabecalho
                    )}
                  >
                    {coluna.ordenavel && aoOrdenar ? (
                      <button
                        type="button"
                        onClick={() => {
                          if (!ativa) aoOrdenar({ coluna: coluna.id, direcao: "asc" });
                          else if (ordenacao?.direcao === "asc") aoOrdenar({ coluna: coluna.id, direcao: "desc" });
                          else aoOrdenar(null);
                        }}
                        className={cn(
                          "-mx-1 inline-flex max-w-full items-center gap-1 rounded-badge px-1 py-0.5 transition-colors duration-120 hover:text-tinta-forte",
                          ativa && "text-tinta-forte",
                          alinhamento === "text-right" && "flex-row-reverse"
                        )}
                        title={coluna.dica ? `${coluna.cabecalho} — ${coluna.dica}` : `Ordenar por ${coluna.cabecalho}`}
                      >
                        <span className="truncate">{coluna.cabecalho}</span>
                        <Icone
                          nome={ativa ? (ordenacao?.direcao === "asc" ? "chevron-cima" : "chevron-baixo") : "ordenar"}
                          className={cn("h-3 w-3 flex-none", ativa ? "text-acento" : "text-tinta-fraca")}
                        />
                      </button>
                    ) : (
                      <span className={cn("inline-flex items-center gap-1", coluna.dica && "cursor-help")} title={coluna.dica}>
                        {coluna.cabecalho}
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>

          {estados.carregando ? (
            <tbody>
              <tr>
                <td colSpan={totalColunas} className="p-0">
                  <EsqueletoTabela
                    linhas={densidade === "compacta" ? 12 : 10}
                    colunas={visiveis.map((coluna) => coluna.largura ?? "flex-1")}
                    alturaLinha={densidade === "compacta" ? "h-10" : "h-11"}
                  />
                </td>
              </tr>
            </tbody>
          ) : (
            <tbody>
              {usaVirtualizacao && intervalo.inicio > 0 ? (
                <tr aria-hidden="true" style={{ height: intervalo.inicio * alturaLinha }}>
                  <td colSpan={totalColunas} className="border-0 p-0" />
                </tr>
              ) : null}

              {linhas.slice(intervalo.inicio, intervalo.fim).map((linha, posicao) => {
                const indice = intervalo.inicio + posicao;
                const chave = chaves[indice];
                const selecionada = selecionadas.has(chave);
                const ativa = indice === indiceAtivo;
                return (
                  <tr
                    key={chave}
                    data-chave={chave}
                    data-linha={indice}
                    tabIndex={aoAbrirLinha || selecao ? (ativa || (indiceAtivo < 0 && indice === intervalo.inicio) ? 0 : -1) : undefined}
                    aria-selected={selecao ? selecionada : undefined}
                    onClick={(evento) => {
                      const alvo = evento.target as HTMLElement;
                      // Clique em controle interno é do controle: não abre a linha.
                      if (alvo.closest("button, a, input, label, select, textarea, [role='menuitem']")) return;
                      setIndiceAtivo(indice);
                      if (aoAbrirLinha) aoAbrirLinha(linha);
                    }}
                    onKeyDown={(evento) => {
                      if ((evento.key === "Enter" || evento.key === " ") && aoAbrirLinha && evento.target === evento.currentTarget) {
                        evento.preventDefault();
                        aoAbrirLinha(linha);
                      }
                    }}
                    onFocus={() => setIndiceAtivo(indice)}
                    className={cn(
                      "border-b border-traco transition-colors duration-120 last:border-0",
                      densidade === "compacta" ? "h-10" : "h-11",
                      aoAbrirLinha && "cursor-pointer",
                      selecionada ? "bg-acento-tenue/60" : "hover:bg-fundo-afundado",
                      ativa && "shadow-[inset_2px_0_0_0_var(--acento)]",
                      classeLinha?.(linha)
                    )}
                  >
                    {selecao ? (
                      <td className="w-10 px-2 align-middle" onClick={(evento) => evento.stopPropagation()}>
                        <span className="sr-only">
                          {selecionada ? "Linha selecionada" : "Linha não selecionada"}
                          {` — ${legenda}, linha ${indice + 1}`}
                        </span>
                        <Caixa
                          compacta
                          rotulo=""
                          aria-label={`Selecionar linha ${indice + 1}`}
                          checked={selecionada}
                          className="-my-1.5 px-0 hover:bg-transparent"
                          onChange={() => alternarSelecao(chave, indice)}
                          onClick={(evento) => {
                            if (evento.shiftKey) {
                              evento.preventDefault();
                              alternarSelecao(chave, indice, ultimaSelecionada ?? indice);
                            }
                          }}
                        />
                      </td>
                    ) : null}
                    {visiveis.map((coluna) => (
                      <td
                        key={coluna.id}
                        data-numerico={coluna.numerica || undefined}
                        className={cn(
                          "max-w-0 px-3 align-middle text-tinta",
                          densidade === "compacta" ? "py-1" : "py-1.5",
                          coluna.numerica ? "text-right nums" : coluna.alinhamento === "direita" ? "text-right" : coluna.alinhamento === "centro" ? "text-center" : "text-left",
                          coluna.largura,
                          coluna.classeCelula
                        )}
                      >
                        {coluna.celula(linha, { selecionada, ativa })}
                      </td>
                    ))}
                  </tr>
                );
              })}

              {temConteudo ? null : conteudoVazio}

              {usaVirtualizacao && intervalo.fim < linhas.length ? (
                <tr aria-hidden="true" style={{ height: (linhas.length - intervalo.fim) * alturaLinha }}>
                  <td colSpan={totalColunas} className="border-0 p-0" />
                </tr>
              ) : null}
            </tbody>
          )}
        </table>
      </div>

      {mostrarBarra ? (
        <div className="nao-imprimir absolute inset-x-0 bottom-0 z-20 border-t border-traco bg-superficie px-3 py-2 shadow-nivel1 animate-subir">
          <div className="flex flex-wrap items-center gap-3">
            <p className="nums flex-none text-sm font-medium text-tinta-forte" role="status" aria-live="polite">
              {selecao?.todasDoFiltro
                ? `Todas as ${numero(selecao?.totalNoFiltro ?? 0)} do filtro`
                : `${numero(selecionadas.size)} ${selecionadas.size === 1 ? "selecionada" : "selecionadas"}`}
            </p>
            {selecao?.todasDoFiltro && selecao.aoCancelarTudoDoFiltro ? (
              <button type="button" onClick={selecao.aoCancelarTudoDoFiltro} className="flex-none rounded-badge text-xs font-medium text-acento underline-offset-4 hover:underline">
                Cancelar seleção do filtro
              </button>
            ) : null}
            {!selecao?.todasDoFiltro && selecao?.aoSelecionarTudoDoFiltro && (selecao.totalNoFiltro ?? 0) > selecionadas.size ? (
              <button type="button" onClick={selecao.aoSelecionarTudoDoFiltro} className="flex-none rounded-badge text-xs font-medium text-acento underline-offset-4 hover:underline">
                Selecionar todas as {numero(selecao.totalNoFiltro)} do filtro
              </button>
            ) : null}
            <div className="flex flex-1 flex-wrap items-center justify-end gap-2">
              {barraDeSelecao?.({
                quantidade: selecao?.todasDoFiltro ? (selecao?.totalNoFiltro ?? 0) : selecionadas.size,
                limpar: () => {
                  selecao?.aoCancelarTudoDoFiltro?.();
                  selecao?.aoMudar(new Set<string>());
                },
              })}
              <button
                type="button"
                onClick={() => {
                  selecao?.aoCancelarTudoDoFiltro?.();
                  selecao?.aoMudar(new Set<string>());
                }}
                className="flex h-8 flex-none items-center rounded-controle px-2 text-xs font-medium text-tinta-suave transition-colors duration-120 hover:bg-fundo-afundado hover:text-tinta"
              >
                Limpar seleção
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {rodape ? <div className="nao-imprimir">{rodape}</div> : null}
    </div>
  );
}
