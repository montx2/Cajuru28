"use client";

import { useLayoutEffect, useState, type HTMLAttributes, type RefObject } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";

interface Posicao { esquerda: number; topo: number; alturaMaxima: number }

export interface CamadaFlutuanteProps extends HTMLAttributes<HTMLDivElement> {
  ancora: RefObject<HTMLDivElement | null>;
  painel: RefObject<HTMLDivElement | null>;
  alinhamento?: "esquerda" | "direita";
}

/** Menus não pertencem ao overflow da tabela. O portal mantém a camada
 * inteira na viewport, acompanha rolagem/resize e abre para cima se necessário. */
export function CamadaFlutuante({ ancora, painel, alinhamento = "direita", className, style, children, ...props }: CamadaFlutuanteProps) {
  const [posicao, setPosicao] = useState<Posicao | null>(null);

  useLayoutEffect(() => {
    const alvo = ancora.current?.querySelector<HTMLElement>("[aria-haspopup]");
    const elemento = painel.current;
    if (!alvo || !elemento) return;

    function posicionar() {
      if (!alvo || !elemento) return;
      const margem = 12;
      const intervalo = 8;
      const gatilho = alvo.getBoundingClientRect();
      const largura = elemento.offsetWidth;
      const altura = elemento.scrollHeight;
      const abaixo = Math.max(0, window.innerHeight - gatilho.bottom - intervalo - margem);
      const acima = Math.max(0, gatilho.top - intervalo - margem);
      const abrirAcima = altura > abaixo && acima > abaixo;
      const alturaMaxima = Math.min(512, Math.max(margem, abrirAcima ? acima : abaixo));
      const preferida = alinhamento === "direita" ? gatilho.right - largura : gatilho.left;
      const esquerda = Math.max(margem, Math.min(preferida, window.innerWidth - largura - margem));
      const topo = abrirAcima ? Math.max(margem, gatilho.top - intervalo - Math.min(altura, alturaMaxima)) : Math.max(margem, Math.min(gatilho.bottom + intervalo, window.innerHeight - Math.min(altura, alturaMaxima) - margem));
      setPosicao((anterior) => anterior?.esquerda === esquerda && anterior.topo === topo && anterior.alturaMaxima === alturaMaxima ? anterior : { esquerda, topo, alturaMaxima });
    }

    posicionar();
    const observador = typeof ResizeObserver !== "undefined" ? new ResizeObserver(posicionar) : null;
    observador?.observe(elemento);
    window.addEventListener("resize", posicionar);
    window.addEventListener("scroll", posicionar, true);
    return () => {
      observador?.disconnect();
      window.removeEventListener("resize", posicionar);
      window.removeEventListener("scroll", posicionar, true);
    };
  }, [alinhamento, ancora, painel]);

  const conteudo = (
    <div
      ref={painel}
      className={cn("vidro rolagem-fina fixed z-flutuante max-w-[calc(100vw-24px)] overflow-y-auto rounded-cartao shadow-nivel1 animate-entrar", className)}
      style={{ ...style, left: posicao?.esquerda ?? 12, top: posicao?.topo ?? 12, maxHeight: posicao?.alturaMaxima ?? 512 }}
      {...props}
    >{children}</div>
  );
  return createPortal(
    props.role === "menu" ? <section aria-label={props["aria-label"] ?? "Menu de ações"}>{conteudo}</section> : conteudo,
    document.body
  );
}
