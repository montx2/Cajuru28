"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { dataCurta, formatarCnpjCpf, numero } from "@/lib/format";
import { ultimosMeses } from "@/lib/periodo";
import { ROTAS, rotaVisivel } from "@/lib/rotas";
import { useTema } from "@/lib/tema";
import { useTeclaModificadora } from "@/lib/useTeclaModificadora";
import { useFocoPreso } from "@/lib/useFocoPreso";
import { useDebounced } from "@/lib/useDebounced";
import type { NomeIcone } from "@/components/ui/Icone";
import { Icone } from "@/components/ui/Icone";
import { useSessao } from "./ProvedorSessao";

interface ItemPaleta {
  id: string;
  rotulo: string;
  descricao?: string;
  icone: NomeIcone;
  grupo: string;
  atalho?: string;
  destino?: string;
  aoExecutar?: () => void;
}

interface GrupoPaleta {
  rotulo: string;
  itens: ItemPaleta[];
}

export interface PaletaComandosProps {
  aberto: boolean;
  aoFechar: () => void;
  aoAbrirAtalhos: () => void;
}

/**
 * Paleta de comandos (`Ctrl/⌘K`): navegação, ações e busca em um lugar.
 *
 * Buscar documento aqui exige período (a API responde 422 sem ele), então a
 * paleta usa os últimos três meses — o horizonte em que uma busca faz sentido
 * operacional — e o resultado já leva o período e o termo na URL.
 */
export function PaletaComandos({ aberto, aoFechar, aoAbrirAtalhos }: PaletaComandosProps) {
  const router = useRouter();
  const { papel } = useSessao();
  const { alternar, tema } = useTema();
  const { simbolo } = useTeclaModificadora();
  const [montado, setMontado] = useState(false);
  const [busca, setBusca] = useState("");
  const [ativo, setAtivo] = useState(0);
  const [empresas, setEmpresas] = useState<Awaited<ReturnType<typeof api.listarEmpresas>> | null>(null);
  const [documentos, setDocumentos] = useState<Awaited<ReturnType<typeof api.listarDocumentos>> | null>(null);
  const [buscandoDocumentos, setBuscandoDocumentos] = useState(false);
  const lista = useRef<HTMLDivElement | null>(null);
  const buscaDebounced = useDebounced(busca.trim(), 350);
  const container = useFocoPreso<HTMLDivElement>({ ativo: aberto, aoFechar });

  useEffect(() => {
    setMontado(true);
  }, []);

  useEffect(() => {
    if (!aberto) {
      setBusca("");
      setAtivo(0);
      setDocumentos(null);
      return;
    }
    if (empresas !== null) return;
    let vivo = true;
    api
      .listarEmpresas()
      .then((dados) => {
        if (vivo) setEmpresas(dados);
      })
      .catch(() => {
        if (vivo) setEmpresas([]);
      });
    return () => {
      vivo = false;
    };
  }, [aberto, empresas]);

  // Busca de documentos só com termo útil: cada consulta custa tempo e cota.
  useEffect(() => {
    if (!aberto || buscaDebounced.length < 4) {
      setDocumentos(null);
      return;
    }
    let vivo = true;
    const periodo = ultimosMeses(3);
    setBuscandoDocumentos(true);
    api
      .listarDocumentos({ busca: buscaDebounced, data_inicio: periodo.inicio, data_fim: periodo.fim, limit: 6 })
      .then((dados) => {
        if (vivo) setDocumentos(dados);
      })
      .catch(() => {
        if (vivo) setDocumentos(null);
      })
      .finally(() => {
        if (vivo) setBuscandoDocumentos(false);
      });
    return () => {
      vivo = false;
    };
  }, [aberto, buscaDebounced]);

  const grupos = useMemo<GrupoPaleta[]>(() => {
    const termo = busca.trim().toLocaleLowerCase("pt-BR");
    const navega = ROTAS.filter((rota) => rotaVisivel(rota, papel))
      .filter((rota) => !termo || `${rota.titulo} ${rota.descricao ?? ""}`.toLocaleLowerCase("pt-BR").includes(termo))
      .map<ItemPaleta>((rota) => ({
        id: `rota-${rota.caminho}`,
        rotulo: rota.titulo,
        descricao: rota.descricao,
        icone: rota.icone,
        grupo: "Navegação",
        atalho: rota.tecla ? `g ${rota.tecla}` : undefined,
        destino: rota.caminho,
      }));

    const acoesBase: ItemPaleta[] = [
      {
        id: "acao-importacao",
        rotulo: "Disparar importação",
        descricao: "Escolher período, empresas e tipos",
        icone: "importacao",
        grupo: "Ações",
        destino: "/dashboard/importacoes",
      },
      {
        id: "acao-fechamento",
        rotulo: "Baixar fechamento do mês",
        descricao: "Relatório, CSV e folha de impressão",
        icone: "fechamento",
        grupo: "Ações",
        destino: "/dashboard/relatorios",
      },
      {
        id: "acao-certificados",
        rotulo: "Ver certificados que vencem",
        descricao: "Validade e última utilização dos A1",
        icone: "certificado",
        grupo: "Ações",
        destino: "/dashboard/certificados?filtro=vencendo",
      },
      {
        id: "acao-documentos-resumo",
        rotulo: "Buscar documentos só com resumo",
        descricao: "Completar XML pela chave de acesso",
        icone: "documento",
        grupo: "Ações",
        destino: "/dashboard/documentos?leiaute=resumo",
      },
      {
        id: "acao-atalhos",
        rotulo: "Ver atalhos de teclado",
        icone: "teclado",
        grupo: "Ações",
        atalho: "?",
        aoExecutar: () => {
          aoFechar();
          aoAbrirAtalhos();
        },
      },
      {
        id: "acao-tema",
        rotulo: tema === "escuro" ? "Usar tema claro" : "Usar tema escuro",
        descricao: "Preferência salva neste navegador",
        icone: tema === "escuro" ? "sol" : "lua",
        grupo: "Ações",
        aoExecutar: () => {
          alternar();
          aoFechar();
        },
      },
    ];
    const acoes = acoesBase.filter(
      (acao) =>
        !termo ||
        acao.rotulo.toLocaleLowerCase("pt-BR").includes(termo) ||
        (acao.descricao ?? "").toLocaleLowerCase("pt-BR").includes(termo)
    );

    const empresasEncontradas: ItemPaleta[] = (termo ? empresas ?? [] : [])
      .filter((empresa) => {
        const digitos = termo.replace(/\D/g, "");
        if (digitos.length >= 2) return empresa.cnpj_cpf.replace(/\D/g, "").includes(digitos);
        return empresa.razao_social.toLocaleLowerCase("pt-BR").includes(termo);
      })
      .slice(0, 6)
      .map((empresa) => ({
        id: `empresa-${empresa.id}`,
        rotulo: empresa.razao_social,
        descricao: `${formatarCnpjCpf(empresa.cnpj_cpf)} · ${empresa.uf || "sem UF"} · ${empresa.ativa ? "ativa" : "inativa"}`,
        icone: "empresa" as NomeIcone,
        grupo: "Empresas",
        destino: `/dashboard/empresa?id=${empresa.id}`,
      }));

    const periodo = ultimosMeses(3);
    const documentosEncontrados: ItemPaleta[] = (documentos ?? []).map((documento) => ({
      id: `documento-${documento.id}`,
      rotulo: `${documento.tipo.toUpperCase()} ${documento.numero ?? ""} · ${documento.emitente_nome ?? documento.destinatario_nome ?? "sem parte"}`,
      descricao: `${formatarCnpjCpf(documento.emitente_documento ?? "")} · ${dataCurta(documento.data_emissao)} · R$ ${numero(documento.valor_total)}`,
      icone: "documento" as NomeIcone,
      grupo: "Documentos (últimos 3 meses)",
      destino: `/dashboard/documentos?busca=${encodeURIComponent(documento.chave_acesso || String(documento.id))}&data_inicio=${periodo.inicio}&data_fim=${periodo.fim}`,
    }));

    const saida: GrupoPaleta[] = [];
    if (navega.length) saida.push({ rotulo: "Navegação", itens: navega });
    if (acoes.length) saida.push({ rotulo: "Ações", itens: acoes });
    if (empresasEncontradas.length) saida.push({ rotulo: "Empresas", itens: empresasEncontradas });
    if (documentosEncontrados.length) saida.push({ rotulo: "Documentos (últimos 3 meses)", itens: documentosEncontrados });
    if (buscandoDocumentos) saida.push({ rotulo: "Buscando documentos…", itens: [] });
    return saida;
  }, [alternar, aoAbrirAtalhos, aoFechar, busca, buscandoDocumentos, documentos, empresas, papel, tema]);

  const plano = useMemo(() => grupos.flatMap((grupo) => grupo.itens), [grupos]);

  useEffect(() => {
    setAtivo(0);
  }, [busca]);

  useEffect(() => {
    if (!aberto) return;
    const elemento = lista.current?.querySelector<HTMLElement>(`[data-indice="${ativo}"]`);
    elemento?.scrollIntoView({ block: "nearest" });
  }, [aberto, ativo]);

  function executar(item: ItemPaleta | undefined) {
    if (!item) return;
    if (item.aoExecutar) item.aoExecutar();
    else if (item.destino) {
      aoFechar();
      router.push(item.destino);
    }
  }

  function aoTeclar(evento: React.KeyboardEvent<HTMLInputElement>) {
    if (evento.key === "ArrowDown") {
      evento.preventDefault();
      setAtivo((atual) => (plano.length ? (atual + 1) % plano.length : 0));
    } else if (evento.key === "ArrowUp") {
      evento.preventDefault();
      setAtivo((atual) => (plano.length ? (atual - 1 + plano.length) % plano.length : 0));
    } else if (evento.key === "Enter") {
      evento.preventDefault();
      executar(plano[ativo]);
    }
  }

  if (!aberto || !montado) return null;
  let indiceCorrido = -1;

  return createPortal(
    <div className="fixed inset-0 z-modal flex items-start justify-center p-4 sm:p-6">
      <div aria-hidden="true" className="absolute inset-0 bg-grafite/50 animate-entrar" onClick={aoFechar} />
      <div
        ref={container}
        role="dialog"
        aria-modal="true"
        aria-label="Paleta de comandos"
        className="relative mt-[8vh] flex max-h-[70vh] w-full max-w-2xl flex-col overflow-hidden rounded-camada border border-traco bg-superficie shadow-nivel2 animate-subir"
      >
        <div className="flex items-center gap-3 border-b border-traco px-4">
          <Icone nome="busca" className="h-4 w-4 flex-none text-tinta-suave" />
          <input
            data-foco-inicial=""
            value={busca}
            onChange={(evento) => setBusca(evento.target.value)}
            onKeyDown={aoTeclar}
            placeholder="Buscar tela, empresa, documento ou ação"
            aria-label="Buscar comando"
            aria-controls="lista-comandos"
            role="combobox"
            aria-expanded="true"
            aria-autocomplete="list"
            autoComplete="off"
            className="h-14 min-w-0 flex-1 bg-transparent text-base text-tinta outline-none placeholder:text-tinta-suave"
          />
          <kbd className="flex-none rounded-badge border border-borda-controle bg-fundo-afundado px-1.5 py-0.5 font-mono text-2xs text-tinta-suave">Esc</kbd>
        </div>

        <div id="lista-comandos" ref={lista} role="listbox" aria-label="Resultados" className="rolagem-fina min-h-0 flex-1 overflow-y-auto py-2">
          {plano.length === 0 && !buscandoDocumentos ? (
            <p className="px-4 py-8 text-center text-sm text-tinta-suave">
              Nada encontrado para “{busca}”. Tente o nome de uma tela, um CNPJ ou parte de uma chave de acesso.
            </p>
          ) : null}

          {grupos.map((grupo) => (
            <section key={grupo.rotulo} className="mb-1 last:mb-0">
              {grupo.itens.length > 0 ? (
                <h3 className="px-4 pb-1 pt-2 text-2xs font-medium uppercase tracking-[.04em] text-tinta-fraca">{grupo.rotulo}</h3>
              ) : null}
              {grupo.itens.map((item) => {
                indiceCorrido += 1;
                const selecionado = indiceCorrido === ativo;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="option"
                    aria-selected={selecionado}
                    data-indice={indiceCorrido}
                    onMouseEnter={() => setAtivo(Number(indiceCorrido))}
                    onClick={() => executar(item)}
                    className={cn(
                      "flex w-full items-center gap-3 px-4 py-2 text-left transition-colors duration-120",
                      selecionado ? "bg-acento-tenue" : "hover:bg-fundo-afundado"
                    )}
                  >
                    <Icone nome={item.icone} className={cn("h-4 w-4 flex-none", selecionado ? "text-acento" : "text-tinta-suave")} />
                    <span className="min-w-0 flex-1">
                      <span className={cn("block truncate text-sm", selecionado ? "font-medium text-tinta-forte" : "text-tinta")}>{item.rotulo}</span>
                      {item.descricao ? <span className="block truncate text-xs text-tinta-suave">{item.descricao}</span> : null}
                    </span>
                    {item.atalho ? (
                      <kbd className="flex-none rounded-badge border border-traco bg-fundo-afundado px-1.5 py-0.5 font-mono text-2xs text-tinta-suave">
                        {item.atalho.replace("Ctrl", simbolo)}
                      </kbd>
                    ) : null}
                  </button>
                );
              })}
            </section>
          ))}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-traco bg-fundo-afundado px-4 py-2 text-2xs text-tinta-suave">
          <span className="flex items-center gap-3">
            <span>↑↓ navegar</span>
            <span>Enter abrir</span>
            <span>Esc fechar</span>
          </span>
          <span className="nums">{plano.length} resultados</span>
        </footer>
      </div>
    </div>,
    document.body
  );
}
