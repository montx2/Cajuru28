"use client";

import Link from "next/link";
import { Fragment, useEffect, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useCamada } from "@/lib/useCamada";
import { Botao, type TamanhoBotao, type VarianteBotao } from "./Botao";
import { CamadaFlutuante } from "./CamadaFlutuante";
import { Dica } from "./Dica";
import { Icone, type NomeIcone } from "./Icone";

export interface ItemMenu {
  id: string;
  rotulo: string;
  icone?: NomeIcone;
  aoClicar?: () => void;
  href?: string;
  tom?: "padrao" | "perigo";
  desabilitado?: boolean;
  /** Por que está indisponível — desabilitado sem explicação parece defeito. */
  motivo?: string;
  atalho?: string;
  selecionado?: boolean;
  /** Separador antes do item. */
  separarAcima?: boolean;
}

export interface MenuSuspensoProps {
  rotulo: string;
  itens: ItemMenu[];
  /** Ações junto a campos de preferência formam um diálogo, não um menu ARIA. */
  tipo?: "menu" | "dialog";
  icone?: NomeIcone;
  variante?: VarianteBotao;
  tamanho?: TamanhoBotao;
  alinhamento?: "esquerda" | "direita";
  largura?: string;
  children?: ReactNode;
  className?: string;
  dica?: string;
  aoAbrir?: () => void;
  /** Avatar/nome ou outro conteúdo do gatilho, preservando a semântica de menu. */
  conteudoGatilho?: ReactNode;
  classeGatilho?: string;
}

/**
 * Menu com o padrão ARIA completo (`menu` + `menuitem`): setas navegam, Home e
 * End vão às pontas, `Esc` fecha e devolve o foco ao gatilho. Item desabilitado
 * continua visível e explica o motivo — sumir com a ação deixa o operador sem
 * saber se o sistema quebrou ou se ele não pode.
 */
export function MenuSuspenso({ rotulo, itens, tipo = "menu", icone, variante = "sutil", tamanho = "md", alinhamento = "direita", largura = "w-60", children, className, dica, aoAbrir, conteudoGatilho, classeGatilho }: MenuSuspensoProps) {
  const camada = useCamada(tipo, aoAbrir);
  const lista = camada.painel;

  const habilitados = itens.filter((item) => !item.desabilitado);

  useEffect(() => {
    if (tipo !== "menu" || !camada.aberto || habilitados.length === 0) return;
    const primeiro = lista.current?.querySelector<HTMLElement>("[role='menuitem']:not([aria-disabled='true'])");
    primeiro?.focus();
    // `habilitados` é derivado de `itens`, que já é a dependência real do efeito.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camada.aberto, tipo]);

  function aoTeclar(evento: React.KeyboardEvent<HTMLDivElement>) {
    if (tipo !== "menu") return;
    const focaveis = Array.from(lista.current?.querySelectorAll<HTMLElement>("[role='menuitem']:not([aria-disabled='true'])") ?? []);
    if (focaveis.length === 0) return;
    const indice = focaveis.indexOf(document.activeElement as HTMLElement);
    if (evento.key === "ArrowDown") {
      evento.preventDefault();
      focaveis[(indice + 1) % focaveis.length].focus();
    } else if (evento.key === "ArrowUp") {
      evento.preventDefault();
      focaveis[(indice - 1 + focaveis.length) % focaveis.length].focus();
    } else if (evento.key === "Home") {
      evento.preventDefault();
      focaveis[0].focus();
    } else if (evento.key === "End") {
      evento.preventDefault();
      focaveis[focaveis.length - 1].focus();
    } else if (evento.key === "Tab") {
      camada.fechar();
    }
  }

  const gatilho = (
    <Botao
      variante={variante}
      tamanho={tamanho}
      onClick={camada.alternar}
      aria-label={icone || conteudoGatilho ? rotulo : undefined}
      {...camada.propsGatilho}
      className={cn(camada.aberto && "bg-fundo-afundado", classeGatilho)}
      iconeDireita={icone || conteudoGatilho ? undefined : <Icone nome="chevron-baixo" className="h-3.5 w-3.5" />}
      iconeEsquerda={icone ? <Icone nome={icone} className="h-4 w-4" /> : undefined}
      somenteIcone={Boolean(icone) && !conteudoGatilho}
    >
      {conteudoGatilho ?? (icone ? null : rotulo)}
    </Botao>
  );

  return (
    <div ref={camada.container} className={cn("relative", className)}>
      {dica ? <Dica texto={dica}>{gatilho}</Dica> : gatilho}
      {camada.aberto ? (
        <CamadaFlutuante
          ancora={camada.container}
          painel={lista}
          alinhamento={alinhamento}
          id={camada.idPainel}
          role={tipo}
          aria-label={rotulo}
          onKeyDown={aoTeclar}
          className={cn("py-1.5", largura)}
        >
          {children}
          {itens.map((item) => {
            const classe = cn(
              "flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm transition-colors duration-120",
              item.tom === "perigo" ? "text-erro hover:bg-erro-tenue" : "text-tinta hover:bg-fundo-afundado",
              item.desabilitado && "cursor-not-allowed opacity-55 hover:bg-transparent",
              item.selecionado && "font-medium text-tinta-forte"
            );
            const conteudo = (
              <>
                {item.icone ? <Icone nome={item.icone} className="h-4 w-4 flex-none text-tinta-suave" /> : <span className="h-4 w-4 flex-none" />}
                <span className="min-w-0 flex-1 truncate">{item.rotulo}</span>
                {item.selecionado ? <Icone nome="verificar" className="h-3.5 w-3.5 flex-none text-acento" /> : null}
                {item.atalho ? <kbd className="flex-none font-mono text-2xs text-tinta-fraca">{item.atalho}</kbd> : null}
              </>
            );
            const comum = {
              role: tipo === "menu" ? "menuitem" as const : undefined,
              "aria-disabled": item.desabilitado || undefined,
              title: item.motivo,
              className: classe,
              tabIndex: -1,
            };
            const separador = item.separarAcima ? <div role="separator" className="my-1 border-t border-traco" /> : null;

            if (item.desabilitado) {
              return (
                <Fragment key={item.id}>
                  {separador}
                  <span {...comum}>{conteudo}</span>
                </Fragment>
              );
            }
            if (item.href) {
              return (
                <Fragment key={item.id}>
                  {separador}
                  <Link
                    href={item.href}
                    {...comum}
                    onClick={() => {
                      camada.fechar();
                      item.aoClicar?.();
                    }}
                  >
                    {conteudo}
                  </Link>
                </Fragment>
              );
            }
            return (
              <Fragment key={item.id}>
                {separador}
                <button
                  type="button"
                  {...comum}
                  onClick={() => {
                    camada.fechar();
                    item.aoClicar?.();
                  }}
                >
                  {conteudo}
                </button>
              </Fragment>
            );
          })}
        </CamadaFlutuante>
      ) : null}
    </div>
  );
}

/** Separador e cabeçalho de grupo dentro do menu. */
export function MenuGrupo({ rotulo }: { rotulo?: string }) {
  return (
    <>
      <div aria-hidden="true" className="my-1 border-t border-traco" />
      {rotulo ? (
        <p role="presentation" className="px-3 pb-1 pt-1.5 text-2xs font-medium uppercase tracking-rotulo text-tinta-fraca">
          {rotulo}
        </p>
      ) : null}
    </>
  );
}
